# conversation_logger.py
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_BASE_DIR = Path(__file__).resolve().parent
_OUT_DIR = _BASE_DIR / "outputs" / "dialogs"

# ✅ 兜底：即使 tg_bot 没正确 load_dotenv，这里也尝试加载同目录 .env（不会影响其它业务）
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv(dotenv_path=_BASE_DIR / ".env")
except Exception:
    pass


def _is_enabled(env_key: str, default: str = "0") -> bool:
    v = (os.getenv(env_key, default) or "").strip().lower()
    return v in ("1", "true", "yes", "y", "on")


def log_telegram_turn(
    *,
    chat_id: int,
    user_id: Optional[int],
    username: Optional[str],
    user_text: str,
    bot_text: str,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Append-only 写入 Telegram 对话到本地 JSONL。
    设计目标：失败也不影响主流程（旁路日志）。
    """
    debug = _is_enabled("TG_SAVE_DIALOG_DEBUG", "0")
    enabled = _is_enabled("TG_SAVE_DIALOG", "0")

    if debug:
        print(f"📝 [TG-LOG] enabled={enabled} TG_SAVE_DIALOG={os.getenv('TG_SAVE_DIALOG')} out_dir={_OUT_DIR}")

    if not enabled:
        return

    try:
        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = _OUT_DIR / f"tg_{chat_id}.jsonl"

        row = {
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "channel": "telegram",
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "user_text": user_text,
            "bot_text": bot_text,
            "meta": meta or {},
        }

        # ✅ default=str：哪怕 meta 里混进复杂对象也不会炸
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")

        if debug:
            print(f"✅ [TG-LOG] wrote: {path}")
    except Exception as e:
        # 旁路日志：吞掉错误，绝不影响 tg 回复
        print(f"⚠️ [TG-LOG] 对话落盘失败（已忽略，不影响回复）: {e}")
