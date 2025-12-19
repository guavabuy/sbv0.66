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
from typing import Dict, List

from dotenv import load_dotenv
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters
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

def _default_normalize_reply(reply):
    if not isinstance(reply, list):
        return reply
    clean_text = ""
    for item in reply:
        if isinstance(item, dict) and "text" in item:
            clean_text += item["text"]
    return clean_text

normalize_reply = getattr(sb_main, "normalize_reply", _default_normalize_reply)


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
    await update.message.reply_text("已重置本次会话上下文 ✅")


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
