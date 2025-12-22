from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core import SecondBrain
from infra.conversation_logger import log_telegram_turn


# chat_id -> SecondBrain（每个会话一个实例，隔离上下文）
_BRAINS: Dict[int, SecondBrain] = {}
_LOCKS: Dict[int, asyncio.Lock] = {}


def _get_lock(chat_id: int) -> asyncio.Lock:
    if chat_id not in _LOCKS:
        _LOCKS[chat_id] = asyncio.Lock()
    return _LOCKS[chat_id]


def _get_brain(chat_id: int) -> SecondBrain:
    if chat_id not in _BRAINS:
        max_turns = int(os.getenv("TG_MAX_TURNS", "20"))
        enable_tools = (os.getenv("TG_ENABLE_TOOLS", "1").strip() in ("1", "true", "yes", "y", "on"))
        _BRAINS[chat_id] = SecondBrain(mode="friend", max_turns=max_turns, enable_tools=enable_tools)
    return _BRAINS[chat_id]


async def _handle_message(update, context) -> None:
    """
    Telegram message handler（固定 mode=friend）。
    只负责收发，不拼 prompt、不读数据文件、不做工具逻辑。
    """
    message = getattr(update, "message", None)
    if message is None:
        return

    chat_id = int(getattr(getattr(message, "chat", None), "id", 0) or 0)
    text = (getattr(message, "text", "") or "").strip()
    if not chat_id or not text:
        return

    lock = _get_lock(chat_id)
    async with lock:
        brain = _get_brain(chat_id)
        try:
            reply = brain.answer(text)
        except Exception as e:
            reply = f"系统错误：{e}"

        try:
            await message.reply_text(reply)
        except Exception:
            # 发送失败也不要炸
            pass

        # 旁路日志（不影响回复）
        try:
            user = getattr(message, "from_user", None)
            log_telegram_turn(
                chat_id=chat_id,
                user_id=getattr(user, "id", None),
                username=getattr(user, "username", None),
                user_text=text,
                bot_text=reply,
                meta={"mode": "friend"},
            )
        except Exception:
            pass


def main() -> None:
    """
    Telegram 入口（固定 mode=friend）。
    """
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        raise RuntimeError("缺少 TELEGRAM_BOT_TOKEN。请在 .env 或环境变量中配置。")

    # 延迟 import：避免在测试/无依赖环境 import apps.tg_bot 时直接失败
    from telegram.ext import Application, MessageHandler, filters

    app = Application.builder().token(token).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_message))
    app.run_polling()


if __name__ == "__main__":
    main()


