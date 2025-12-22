from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.modes import BrainMode, MODE_TO_PROMPT_MD
from core.prompt_loader import load_prompt, render_prompt
from core.privacy import apply_privacy_gate


@dataclass(frozen=True)
class BrainContext:
    """
    SecondBrain 的“已加载上下文”快照（纯数据，便于测试）。
    """

    user_profile: str = ""
    recent_corpus: str = ""
    private_memory: str = ""


class SecondBrain:
    """
    Core Brain 主体（Card 1）。

    统一职责入口：
    - 上下文构建（load_context）
    - 模式切换（self/friend）
    - 隐私闸门（friend 不加载私密日志）
    - 工具调用（LLM tool calls 的统一执行）

    注意：
    - 这里只做业务逻辑，不做任何 CLI/TG 的消息收发。
    - 这里默认不落盘写入 brain_memory.md（日志/持久化由上层 App 决定）。
    """

    def __init__(
        self,
        mode: BrainMode = "self",
        *,
        days: int = 30,
        max_corpus_items: int = 18,
        max_user_memory_entries: int = 12,
        profile_path: Optional[str] = None,
        corpus_path: Optional[str] = None,
        brain_memory_path: Optional[str] = None,
        # Card 2：prompt 由 mode 映射到 prompts/*.md（不再需要传 prompt 文件名）
        llm_provider: str = "google_genai",
        llm_model: str = "gemini-2.5-flash",
        temperature: float = 0.3,
        timeout: int = 30,
        max_retries: int = 2,
        enable_tools: bool = True,
        max_turns: int = 20,
    ) -> None:
        self._root = Path(__file__).resolve().parents[1]

        self.mode: BrainMode = self._validate_mode(mode)
        self.days = int(days)
        self.max_corpus_items = int(max_corpus_items)
        self.max_user_memory_entries = int(max_user_memory_entries)

        # Card 6：默认使用 data/ 目录；兼容旧 outputs/（若 data 不存在则回退）
        data_dir = Path(os.getenv("SB_DATA_DIR", "")).expanduser() if os.getenv("SB_DATA_DIR") else (self._root / "data")
        legacy_dir = self._root / "outputs"

        def _pick(p_new: Path, p_old: Path) -> Path:
            return p_new if p_new.exists() else p_old

        self.profile_path = (
            Path(profile_path)
            if profile_path
            else _pick(data_dir / "user_profile.md", legacy_dir / "user_profile.md")
        )
        self.corpus_path = (
            Path(corpus_path)
            if corpus_path
            else _pick(data_dir / "corpus.jsonl", legacy_dir / "corpus.jsonl")
        )
        self.brain_memory_path = (
            Path(brain_memory_path)
            if brain_memory_path
            else _pick(data_dir / "brain_memory.md", legacy_dir / "brain_memory.md")
        )

        self.llm_provider = str(llm_provider or "").strip() or "google_genai"
        self.llm_model = str(llm_model or "").strip() or "gemini-2.5-flash"
        self.temperature = float(temperature)
        self.timeout = int(timeout)
        self.max_retries = int(max_retries)
        self.enable_tools = bool(enable_tools)

        self.max_turns = int(max_turns)
        self._llm = None  # lazy init

        # 初始化会话：system prompt + 空历史
        ctx = self.load_context()
        system_prompt = self.build_prompt(ctx)
        self._messages = self._new_session(system_prompt)

    # -----------------------------
    # Public API
    # -----------------------------
    def answer(self, user_input: str) -> str:
        """
        App 层唯一入口：给定用户输入，返回模型文本回复。
        """
        text = (user_input or "").strip()
        if not text:
            return ""

        from langchain_core.messages import HumanMessage

        self._messages.append(HumanMessage(content=text))
        reply, extra_messages = self.call_llm(self._messages)
        if extra_messages:
            self._messages.extend(extra_messages)

        # 裁剪历史，避免无限增长（仅内存，不落盘）
        self._trim_history()
        return reply

    def switch_mode(self, mode: BrainMode) -> None:
        """
        模式切换（Card 1）：重建上下文与 system prompt，并重置会话历史。
        """
        self.mode = self._validate_mode(mode)
        ctx = self.load_context()
        system_prompt = self.build_prompt(ctx)
        self._messages = self._new_session(system_prompt)

    # -----------------------------
    # Step 1: load_context()
    # -----------------------------
    def load_context(self) -> BrainContext:
        """
        从本地数据源加载上下文：
        - 画像：data/user_profile.md（兼容旧 outputs/）
        - 最近 N 天摘要：data/corpus.jsonl（兼容旧 outputs/）
        - 私密日志：data/brain_memory.md（仅 self 模式；兼容旧 outputs/）
        """
        # Card 3：任何上下文构建的文件读取都必须先过隐私闸门（物理隔离）
        candidates = [self.profile_path, self.corpus_path, self.brain_memory_path]
        allowed = set(apply_privacy_gate(self.mode, candidates))

        user_profile = self._read_text_file(self.profile_path) if self.profile_path in allowed else ""

        recent_corpus = self._get_recent_corpus_snippets(
            corpus_path=self.corpus_path,
            days=self.days,
            max_items=self.max_corpus_items,
        ) if self.corpus_path in allowed else ""

        private_memory = ""
        if self.brain_memory_path in allowed:
            private_memory = self._load_recent_user_memory(
                log_path=self.brain_memory_path,
                max_entries=self.max_user_memory_entries,
            )

        return BrainContext(
            user_profile=user_profile,
            recent_corpus=recent_corpus,
            private_memory=private_memory,
        )

    # -----------------------------
    # Step 2: build_prompt()
    # -----------------------------
    def build_prompt(self, ctx: BrainContext) -> str:
        """
        从 prompts/ 读取模板并注入 context。
        """
        prompt_name = MODE_TO_PROMPT_MD.get(self.mode)
        template = ""
        try:
            template = load_prompt(prompt_name)
        except Exception:
            # prompt 缺失/损坏时，降级到最小可用 prompt（避免崩溃；但不在 .py 内硬编码长 prompt）
            template = "你是一个友好的助手。请用清晰、礼貌、简洁的方式回答用户。"

        rendered = render_prompt(
            template,
            {
                "mode": self.mode,
                "user_profile": (ctx.user_profile or "").strip(),
                "recent_corpus": (ctx.recent_corpus or "").strip(),
                "private_memory": (ctx.private_memory or "").strip(),
            },
        )
        return (rendered or "").strip()

    # -----------------------------
    # Step 3: call_llm()
    # -----------------------------
    def call_llm(self, messages: Sequence[Any]) -> tuple[str, List[Any]]:
        """
        统一 LLM 调用入口（含 tools 的二段调用）。
        返回 (reply_text, extra_messages_to_append)
        """
        llm = self._get_llm()

        response = llm.invoke(list(messages))
        if getattr(response, "tool_calls", None):
            from langchain_core.messages import ToolMessage

            tool_outputs: List[Any] = []
            for tool_call in response.tool_calls:
                name = tool_call.get("name")
                args = tool_call.get("args") or {}
                res = self._invoke_tool(name, args)
                tool_outputs.append(
                    ToolMessage(tool_call_id=tool_call.get("id"), content=str(res))
                )

            final_response = llm.invoke(list(messages) + [response] + tool_outputs)
            reply = self._normalize_reply(final_response.content)
            return reply, [response] + tool_outputs + [final_response]

        reply = self._normalize_reply(response.content)
        return reply, [response]

    # -----------------------------
    # Internals
    # -----------------------------
    @staticmethod
    def _validate_mode(mode: str) -> BrainMode:
        m = (mode or "").strip().lower()
        if m not in ("self", "friend"):
            raise ValueError(f"非法 mode={mode!r}（仅允许 'self' / 'friend'）")
        return m  # type: ignore[return-value]

    def _new_session(self, system_prompt: str) -> List[Any]:
        from langchain_core.messages import SystemMessage

        return [SystemMessage(content=system_prompt)]

    def _trim_history(self) -> None:
        """
        仅保留最近 N 轮对话（不含 system prompt）。
        粗略策略：把 user/assistant/tool messages 视作一条条追加，按数量截断。
        """
        if self.max_turns <= 0:
            return
        # 1 个 turn ~ 2 条消息（user+assistant），加 tool/extra 余量
        max_msgs = 1 + self.max_turns * 6
        if len(self._messages) <= max_msgs:
            return
        self._messages = [self._messages[0]] + self._messages[-(max_msgs - 1):]

    @staticmethod
    def _read_text_file(path: Path) -> str:
        try:
            if not path.exists() or not path.is_file():
                return ""
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    @staticmethod
    def _normalize_reply(reply: Any) -> str:
        # Gemini 有时返回 list[dict{text:...}]
        if not isinstance(reply, list):
            return str(reply) if reply is not None else ""
        clean_text = ""
        for item in reply:
            if isinstance(item, dict) and "text" in item:
                clean_text += str(item.get("text") or "")
        return clean_text

    # -------- corpus snippets (path-aware) --------
    @staticmethod
    def _parse_dt(s: str) -> Optional[datetime]:
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None

    @staticmethod
    def _infer_dt_from_notion_filename(file_path: str) -> Optional[datetime]:
        m = re.search(
            r"/notion/([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}_[0-9]{2}_[0-9]{2}[^_/]*)_",
            (file_path or "").replace("\\", "/"),
        )
        if not m:
            return None
        ts = m.group(1).replace("_", ":")
        if "+" not in ts and "Z" not in ts:
            ts = ts + "+00:00"
        return SecondBrain._parse_dt(ts)

    @staticmethod
    def _get_recent_corpus_snippets(
        *,
        corpus_path: Path,
        days: int = 30,
        max_items: int = 18,
        max_chars: int = 260,
    ) -> str:
        try:
            if not corpus_path.exists() or not corpus_path.is_file():
                return ""
            lines = corpus_path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return ""

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=int(days))

        items: List[Dict[str, Any]] = []
        for ln in lines:
            try:
                obj = json.loads(ln)
            except Exception:
                continue

            source = obj.get("source", "unknown")
            file_path = obj.get("file_path", "")
            created_at = obj.get("created_at")

            dt = SecondBrain._parse_dt(created_at) if created_at else None
            if dt is None and source == "notion":
                dt = SecondBrain._infer_dt_from_notion_filename(file_path)

            if dt is None or dt < cutoff:
                continue

            text = (obj.get("text") or "").strip().replace("\n", " ")
            if not text:
                continue

            items.append(
                {
                    "dt": dt,
                    "source": source,
                    "weight": float(obj.get("weight", 0.0)),
                    "text": text[: int(max_chars)],
                }
            )

        items.sort(key=lambda x: (x["dt"], x["weight"]), reverse=True)
        picked = items[: int(max_items)]
        if not picked:
            return ""

        out: List[str] = [f"【最近{int(days)}天 Notion/X 摘要（从语料库自动抽取）】"]
        for it in picked:
            dt_str = it["dt"].astimezone(timezone.utc).strftime("%Y-%m-%d")
            out.append(f"- {dt_str} | {it['source']} | w={it['weight']:.3f} | {it['text']}")
        return "\n".join(out)

    # -------- private memory (self-only) --------
    @staticmethod
    def _load_recent_user_memory(log_path: Path, max_entries: int = 12) -> str:
        """
        从 brain_memory.md 里只提取最近的 User 输入（带时间戳的块），用于回答“最近/近期”类问题。
        兼容 main.py 的落盘格式。
        """
        if not log_path.exists() or not log_path.is_file():
            return ""
        try:
            content = log_path.read_text(encoding="utf-8")
        except Exception:
            return ""

        brain_sep = "-" * 30
        blocks = [b.strip() for b in content.split(brain_sep) if b.strip()]

        user_blocks: List[str] = []
        for b in blocks:
            m = re.search(r"\*\*\[(.*?)\]\s*(.*?):\*\*", b)
            if not m:
                continue
            source = (m.group(2) or "").strip().lower()
            if source in ("user", "用户"):
                user_blocks.append(b)

        return "\n\n".join(user_blocks[-int(max_entries) :])

    # -------- LLM + tools --------
    def _get_llm(self):
        if self._llm is not None:
            return self._llm

        # 延迟 import：避免纯 load_context/build_prompt 的使用场景被 langchain 绑死
        from dotenv import load_dotenv
        from langchain_google_genai import ChatGoogleGenerativeAI

        load_dotenv()

        if self.llm_provider != "google_genai":
            raise NotImplementedError(
                f"llm_provider={self.llm_provider!r} 尚未接入（已预留接口：OpenAI/DeepSeek 可在后续卡片适配）"
            )

        if not os.getenv("GOOGLE_API_KEY"):
            raise RuntimeError("缺少 GOOGLE_API_KEY，无法调用 google_genai。")

        llm = ChatGoogleGenerativeAI(
            model=self.llm_model,
            temperature=self.temperature,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

        self._tools_by_name: Dict[str, Any] = {}
        if self.enable_tools:
            tools = self._build_tools()
            self._tools_by_name = {getattr(t, "name", ""): t for t in tools if getattr(t, "name", "")}
            llm = llm.bind_tools(tools)

        self._llm = llm
        return self._llm

    def _build_tools(self) -> List[Any]:
        """
        默认工具集合（可后续扩展为注入式 registry）。
        """
        from langchain_core.tools import tool
        from core.tools.search import search_web
        from core.tools.read_url import read_url

        @tool
        def search_tool(query: str):
            """当需要验证事实、查询新闻或生成摘要时使用。"""
            results = search_web(query, k=5)
            # 统一返回结构（JSON 可序列化）
            if not results:
                if not os.getenv("SERPAPI_API_KEY"):
                    return [
                        {
                            "title": "",
                            "url": None,
                            "snippet": "工具不可用：未配置 SERPAPI_API_KEY。",
                            "source": "serpapi",
                        }
                    ]
                return [
                    {
                        "title": "",
                        "url": None,
                        "snippet": "未检索到有效结果（或搜索失败）。",
                        "source": "serpapi",
                    }
                ]
            return [r.to_dict() for r in results]

        @tool
        def read_url_tool(url: str):
            """读取网页内容（通过 r.jina.ai 转换为可读文本）。"""
            return read_url(url)

        return [search_tool, read_url_tool]

    def _invoke_tool(self, name: Optional[str], args: Any) -> Any:
        if not name:
            return "未知工具"
        tool_obj = getattr(self, "_tools_by_name", {}).get(name)
        if tool_obj is None:
            return "未知工具"
        try:
            # langchain tool 统一入口：invoke(dict)
            return tool_obj.invoke(args or {})
        except Exception as e:
            return f"工具调用失败: {e}"


