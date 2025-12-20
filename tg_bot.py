"""
Telegram 接入脚本（Guest 模式）
- 让朋友通过 Telegram 与你的 Second Brain 对话
- 朋友的消息/回复不会写入 outputs/brain_memory.md（不污染你的记忆）
- 会在内存里为每个 chat 维护短期上下文（进程重启即消失）

用法：
1) 在 .env 里加入：TELEGRAM_BOT_TOKEN=xxxxx
2) pip install -U python-telegram-bot
3) python3 tg_bot.py
"""

import asyncio
import os
<<<<<<< HEAD
from typing import Dict, List
=======
import json
import re
from typing import Any, Dict, List, Tuple
>>>>>>> d7e1b9a (archive: friend_mode + tg integration + smoke test)

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
<<<<<<< HEAD
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

import main as sb_main  # 直接导入模块，避免某些常量不存在导致 ImportError
from memory_retriever import get_recent_corpus_snippets

load_dotenv()

# 兼容：有些 main.py 里可能没定义 PROMPT_SEP / normalize_reply 等，这里做兜底
PROMPT_SEP = getattr(sb_main, "PROMPT_SEP", "-" * 20)
get_dynamic_system_prompt = getattr(sb_main, "get_dynamic_system_prompt")
read_url_tool = getattr(sb_main, "read_url_tool")
search_tool = getattr(sb_main, "search_tool")
system_health_check = getattr(sb_main, "system_health_check")
llm = getattr(sb_main, "llm")
=======
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from conversation_logger import log_telegram_turn

# 注意：为了让 tests 在“缺少某些第三方依赖/沙盒限制”时也能 import tg_bot，
# 这里对 main 做容错导入；真实运行 tg_bot.py 时仍会正常使用 main 的 llm/tools。
try:
    import main as sb_main  # type: ignore
except Exception:  # pragma: no cover
    sb_main = None

from memory_retriever import get_recent_corpus_snippets
from friend_mode_config import get_tg_friend_mode_enabled, get_thresholds

from pathlib import Path
_DOTENV_PATH = Path(__file__).resolve().parent / ".env"
# 测试/沙盒里 .env 可能不可读（权限/过滤），这里不要阻塞 import
try:  # pragma: no cover
    load_dotenv(dotenv_path=_DOTENV_PATH)
except Exception:
    pass

# 兼容：有些 main.py 里可能没定义 PROMPT_SEP / normalize_reply 等，这里做兜底
PROMPT_SEP = getattr(sb_main, "PROMPT_SEP", "-" * 20) if sb_main else "-" * 20

def _missing_main(*_args, **_kwargs):  # pragma: no cover
    raise RuntimeError("tg_bot 运行需要 main.py 及其依赖；当前环境无法导入 main。")

get_dynamic_system_prompt = getattr(sb_main, "get_dynamic_system_prompt", _missing_main)
read_url_tool = getattr(sb_main, "read_url_tool", _missing_main)
search_tool = getattr(sb_main, "search_tool", _missing_main)
system_health_check = getattr(sb_main, "system_health_check", _missing_main)
llm = getattr(sb_main, "llm", None)
>>>>>>> d7e1b9a (archive: friend_mode + tg integration + smoke test)

def _default_normalize_reply(reply):
    if not isinstance(reply, list):
        return reply
    clean_text = ""
    for item in reply:
        if isinstance(item, dict) and "text" in item:
            clean_text += item["text"]
    return clean_text

normalize_reply = getattr(sb_main, "normalize_reply", _default_normalize_reply)

<<<<<<< HEAD
=======
def _tg_is_cjk(s: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", s or ""))


def _tg_norm(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _tg_terms(q: str) -> List[str]:
    q = _tg_norm(q)
    if not q:
        return []
    if _tg_is_cjk(q):
        tokens = re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{2,}", q)
        chars = re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", q)
        bigrams = ["".join(chars[i:i + 2]) for i in range(0, max(0, len(chars) - 1))]
        return [t for t in (tokens + bigrams) if t]
    return re.findall(r"[a-z0-9]{2,}", q)


def _tg_score_overlap(terms: List[str], text: str) -> float:
    if not terms:
        return 0.0
    doc = _tg_norm(text)
    if not doc:
        return 0.0
    hit = 0
    for t in set(terms):
        if t and t in doc:
            hit += 1
    return hit / max(1, len(set(terms)))


def _tg_friend_retrieve_raw(
    query: str,
    top_k: int = 6,
    corpus_path: str = "outputs/corpus.jsonl",
    max_scan: int = 4000,
) -> Dict[str, Any]:
    """
    仅供 tg friend_mode 使用的最小检索：
    - 扫描 outputs/corpus.jsonl 的尾部（append-only）
    - 用关键词覆盖率做粗 score
    返回结构可被 retrieval_adapter.adapt_retrieval 适配。
    """
    q = (query or "").strip()
    if not q:
        return {"query": q, "hits": []}

    try:
        with open(corpus_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return {"query": q, "hits": []}

    lines = lines[-max_scan:] if max_scan and len(lines) > max_scan else lines
    terms = _tg_terms(q)

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        text = (obj.get("text") or "").strip()
        if not text:
            continue
        base = _tg_score_overlap(terms, text)
        if base <= 0:
            continue
        # 弱加成：权重/新近性不在 tg_bot 里做复杂处理，避免侵入
        score = float(min(1.0, max(0.0, base)))
        scored.append((score, {
            "id": obj.get("uid") or obj.get("id"),
            "score": score,
            "text": text,
            "source": obj.get("source"),
            "path": obj.get("file_path"),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    hits = [h for _, h in scored[: max(1, int(top_k or 6))]]
    return {"query": q, "hits": hits}


def generate_tg_reply(text: str, messages: List) -> Tuple[str, Dict[str, Any], List]:
    """
    Card 8：tg_bot 最小侵入接入点（纯函数，便于测试）。
    - TG_FRIEND_MODE!=1：保持旧链路（LLM+tools）
    - TG_FRIEND_MODE==1：走 friend_mode.answer_telegram（只影响 TG）
    """
    if get_tg_friend_mode_enabled():
        # 懒加载：开关关闭时不触碰 friend_mode 依赖，确保旧行为不变
        from retrieval_adapter import adapt_retrieval
        from friend_mode import answer_telegram_with_meta

        raw = _tg_friend_retrieve_raw(
            text,
            top_k=int(os.getenv("TG_RETRIEVE_TOP_K", "6")),
            corpus_path=os.getenv("TG_CORPUS_PATH", "outputs/corpus.jsonl"),
            max_scan=int(os.getenv("TG_RETRIEVE_MAX_SCAN", "4000")),
        )
        pack = adapt_retrieval(raw)
        thresholds = get_thresholds()

        # TG Guest 模式：不额外注入你的私密画像/私聊记忆
        reply, meta = answer_telegram_with_meta(
            user_query=text,
            retrieval=pack,
            user_profile="",
            brain_memory="",
            thresholds=thresholds,
        )
        # 控制台可观测性（DoD）：至少能看到 route/top_score/hit_count/web_search/used_chunks
        print(f"[TG_FRIEND_MODE] route={meta.get('route')} top_score={meta.get('top_score')} hit_count={meta.get('hit_count')} web_search={meta.get('web_search')} used_chunks={meta.get('used_chunks')}")
        return reply, meta, [AIMessage(content=reply)]

    # 旧链路：LLM + tools
    if llm is None:
        raise RuntimeError("llm 未初始化（main.py 未能导入或未提供 llm）。")

    response = llm.invoke(messages)
    if getattr(response, "tool_calls", None):
        tool_outputs = []
        for tool_call in response.tool_calls:
            if tool_call["name"] == "read_url_tool":
                res = read_url_tool.invoke(tool_call["args"])
            elif tool_call["name"] == "search_tool":
                res = search_tool.invoke(tool_call["args"])
            else:
                res = "未知工具"
            tool_outputs.append(ToolMessage(tool_call_id=tool_call["id"], content=str(res)))
        final_response = llm.invoke(messages + [response] + tool_outputs)
        reply = normalize_reply(final_response.content)
        extra = [response] + tool_outputs + [final_response]
        return reply, {}, extra

    reply = normalize_reply(response.content)
    return reply, {}, [response]

>>>>>>> d7e1b9a (archive: friend_mode + tg integration + smoke test)

# 每个 chat 保留多少“轮”上下文（不落盘，纯内存）
MAX_TURNS = int(os.getenv("TG_MAX_TURNS", "20"))  # 20 轮≈40条消息（user+assistant）

# 可选：限制允许使用的 Telegram chat_id（逗号分隔），不填则不限制
# 例：TG_ALLOWED_CHAT_IDS=123,456
_ALLOWED = os.getenv("TG_ALLOWED_CHAT_IDS", "").strip()
ALLOWED_CHAT_IDS = {int(x) for x in _ALLOWED.split(",") if x.strip().isdigit()} if _ALLOWED else set()

SYSTEM_PROMPT: str = ""
SESSIONS: Dict[int, List] = {}        # chat_id -> messages
LOCKS: Dict[int, asyncio.Lock] = {}   # chat_id -> lock（避免并发乱序）


def build_system_prompt() -> str:
    """
    给 Telegram 对话使用的 system prompt。
    注意：这里不会注入 outputs/brain_memory.md 的“最近用户输入记录”，避免把你的私聊记忆暴露给朋友。
    但会保留 user_profile + 近30天 corpus 注入（与 main.py 的个性化来源一致）。
    """
    prompt = get_dynamic_system_prompt()

    try:
        recent_corpus = get_recent_corpus_snippets(days=30, max_items=18)
        if recent_corpus.strip():
            prompt += f"\n\n{PROMPT_SEP}\n{recent_corpus}\n{PROMPT_SEP}"
            print("🧠 [TG] 已注入最近30天 Notion/X 语料摘要。")
    except Exception as e:
        print(f"⚠️ [TG] 注入最近语料失败: {e}")

    return prompt


def _get_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in LOCKS:
        LOCKS[chat_id] = asyncio.Lock()
    return LOCKS[chat_id]


def _get_session(chat_id: int) -> List:
    if chat_id not in SESSIONS:
        SESSIONS[chat_id] = [SystemMessage(content=SYSTEM_PROMPT)]
    return SESSIONS[chat_id]


def _trim_session(messages: List) -> List:
    # 保留 SystemMessage + 最近 MAX_TURNS 轮（≈2*MAX_TURNS 条）
    if not messages:
        return messages
    system = messages[0:1]
    tail = messages[1:]
    keep = tail[-(MAX_TURNS * 2):]
    return system + keep


async def _send_long_text(update: Update, text: str) -> None:
    # Telegram 单条上限 4096，分段发送
    CHUNK = 3500
    for i in range(0, len(text), CHUNK):
        await update.message.reply_text(text[i:i + CHUNK])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return

    await update.message.reply_text(
        "👋 你好！这里是一个 Guest 模式的 Second Brain。\n"
        "✅ 你的消息不会被写入我的长期记忆（不落盘）。\n\n"
        "命令：/reset 重置上下文"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return

    chat_id = update.effective_chat.id
    SESSIONS[chat_id] = [SystemMessage(content=SYSTEM_PROMPT)]
<<<<<<< HEAD
    await update.message.reply_text("已重置本次会话上下文 ✅")
=======
    reply = "已重置本次会话上下文 ✅"
    await update.message.reply_text(reply)
>>>>>>> d7e1b9a (archive: friend_mode + tg integration + smoke test)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text:
        return
    if ALLOWED_CHAT_IDS and update.effective_chat.id not in ALLOWED_CHAT_IDS:
        return

    chat_id = update.effective_chat.id
    text = update.message.text.strip()
    if not text:
        return

    # 复用 main.py 的快捷指令（如果你 main.py 里也有这个习惯）
    if text.lower() == "daily":
        text = "请搜索过去24小时 Crypto 市场新闻，总结3个核心要点。"

    lock = _get_lock(chat_id)
    async with lock:
        await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

        messages = _get_session(chat_id)
        messages.append(HumanMessage(content=text))

        try:
<<<<<<< HEAD
            response = await asyncio.to_thread(llm.invoke, messages)
        except Exception as e:
            messages.pop()  # 回滚本次 user 输入
            await update.message.reply_text(f"❌ AI 调用错误: {e}")
            return

        if getattr(response, "tool_calls", None):
            tool_outputs = []
            for tool_call in response.tool_calls:
                if tool_call["name"] == "read_url_tool":
                    res = read_url_tool.invoke(tool_call["args"])
                elif tool_call["name"] == "search_tool":
                    res = search_tool.invoke(tool_call["args"])
                else:
                    res = "未知工具"
                tool_outputs.append(ToolMessage(tool_call_id=tool_call["id"], content=str(res)))

            try:
                final_response = await asyncio.to_thread(llm.invoke, messages + [response] + tool_outputs)
            except Exception as e:
                await update.message.reply_text(f"❌ 工具链调用错误: {e}")
                return

            reply = normalize_reply(final_response.content)

            # 只存内存，不写入任何 outputs 文件
            messages.append(response)
            messages.extend(tool_outputs)
            messages.append(final_response)
        else:
            reply = normalize_reply(response.content)
            messages.append(response)

        SESSIONS[chat_id] = _trim_session(messages)
        await _send_long_text(update, reply if reply else "（空响应）")


def main() -> None:
=======
            reply, meta, extra_msgs = await asyncio.to_thread(generate_tg_reply, text, messages)
        except Exception as e:
            messages.pop()  # 回滚本次 user 输入
            await update.message.reply_text(f"❌ 调用错误: {e}")
            return

        # 旧链路需要把 assistant/tool turn 也写入 session；friend_mode 则写入 AIMessage
        if extra_msgs:
            messages.extend(extra_msgs)

        SESSIONS[chat_id] = _trim_session(messages)

        final_text = reply if reply else "（空响应）"
        log_telegram_turn(
            chat_id=chat_id,
            user_id=getattr(update.effective_user, "id", None),
            username=getattr(update.effective_user, "username", None),
            user_text=text,
            bot_text=final_text,
            meta=meta if (meta and get_tg_friend_mode_enabled()) else None,
        )

        await _send_long_text(update, final_text)

def main() -> None:
    # 运行时再尝试加载一次（如果 import 时失败）
    try:
        load_dotenv(dotenv_path=_DOTENV_PATH)
    except Exception:
        pass

>>>>>>> d7e1b9a (archive: friend_mode + tg integration + smoke test)
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise SystemExit("❌ 缺少 TELEGRAM_BOT_TOKEN，请在 .env 中配置。")

    # 复用 main.py 的健康检查
    system_health_check()

    global SYSTEM_PROMPT
    SYSTEM_PROMPT = build_system_prompt()

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("🤖 Telegram Guest Bot 已启动。")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
