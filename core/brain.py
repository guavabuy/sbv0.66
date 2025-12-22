from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional, Sequence

from core.modes import BrainMode, MODE_TO_PROMPT_MD
from core.prompt_loader import load_prompt, render_prompt
from core.privacy import apply_privacy_gate
from core.settings import settings
from core.utils.io_helper import read_text_file
from core.retrieval import get_recent_corpus_snippets, load_recent_user_memory
from core.llm_provider import get_llm_backend, normalize_reply


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
    Core Brain 主体。
    统一职责入口：上下文构建、模式切换、隐私闸门、LLM 调用。
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
        llm_provider: Optional[str] = None,
        llm_model: Optional[str] = None,
        temperature: float = 0.3,
        timeout: int = 30,
        max_retries: int = 2,
        enable_tools: bool = True,
        max_turns: int = 20,
    ) -> None:
        self.mode: BrainMode = self._validate_mode(mode)
        self.days = int(days)
        self.max_corpus_items = int(max_corpus_items)
        self.max_user_memory_entries = int(max_user_memory_entries)

        # 路径初始化：优先使用传入路径，否则使用 settings 默认路径
        self.profile_path = Path(profile_path) if profile_path else settings.get_data_path("user_profile.md")
        self.corpus_path = Path(corpus_path) if corpus_path else settings.get_data_path("corpus.jsonl")
        self.brain_memory_path = Path(brain_memory_path) if brain_memory_path else settings.get_data_path("brain_memory.md")

        self.llm_provider = llm_provider or settings.DEFAULT_LLM_PROVIDER
        self.llm_model = llm_model or settings.DEFAULT_LLM_MODEL
        self.temperature = float(temperature)
        self.timeout = int(timeout)
        self.max_retries = int(max_retries)
        self.enable_tools = bool(enable_tools)

        self.max_turns = int(max_turns)
        self._llm = None  # lazy init

        # 初始化会话
        ctx = self.load_context()
        system_prompt = self.build_prompt(ctx)
        self._messages = self._new_session(system_prompt)

    def answer(self, user_input: str) -> str:
        text = (user_input or "").strip()
        if not text:
            return ""

        from langchain_core.messages import HumanMessage
        human = HumanMessage(content=text)
        send_messages = list(self._messages) + [human]

        reply, extra_messages = self.call_llm(send_messages)

        self._messages.append(human)
        if extra_messages:
            self._messages.extend(extra_messages)

        self._trim_history()
        return reply

    def switch_mode(self, mode: BrainMode) -> None:
        self.mode = self._validate_mode(mode)
        ctx = self.load_context()
        system_prompt = self.build_prompt(ctx)
        self._messages = self._new_session(system_prompt)

    def load_context(self) -> BrainContext:
        """
        加载上下文，集成隐私网关。
        """
        candidates = [self.profile_path, self.corpus_path, self.brain_memory_path]
        allowed = set(apply_privacy_gate(self.mode, candidates))

        user_profile = read_text_file(self.profile_path) if self.profile_path in allowed else ""

        recent_corpus = get_recent_corpus_snippets(
            corpus_path=self.corpus_path,
            days=self.days,
            max_items=self.max_corpus_items,
        ) if self.corpus_path in allowed else ""

        private_memory = ""
        if self.brain_memory_path in allowed:
            private_memory = load_recent_user_memory(
                log_path=self.brain_memory_path,
                max_entries=self.max_user_memory_entries,
            )

        return BrainContext(
            user_profile=user_profile,
            recent_corpus=recent_corpus,
            private_memory=private_memory,
        )

    def build_prompt(self, ctx: BrainContext) -> str:
        prompt_name = MODE_TO_PROMPT_MD.get(self.mode)
        try:
            template = load_prompt(prompt_name)
        except Exception:
            template = "你是一个友好的助手。请用清晰、礼貌、简洁的方式回答用户。"

        return render_prompt(
            template,
            {
                "mode": self.mode,
                "user_profile": (ctx.user_profile or "").strip(),
                "recent_corpus": (ctx.recent_corpus or "").strip(),
                "private_memory": (ctx.private_memory or "").strip(),
            },
        ).strip()

    def call_llm(self, messages: Sequence[Any]) -> tuple[str, List[Any]]:
        llm = self._get_llm()
        response = llm.invoke(list(messages))
        reply = normalize_reply(response.content)
        return reply, [response]

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
        if self.max_turns <= 0:
            return
        max_msgs = 1 + self.max_turns * 6
        if len(self._messages) <= max_msgs:
            return
        self._messages = [self._messages[0]] + self._messages[-(max_msgs - 1):]

    def _get_llm(self):
        if self._llm is None:
            self._llm = get_llm_backend(
                provider=self.llm_provider,
                model=self.llm_model,
                temperature=self.temperature,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._llm
