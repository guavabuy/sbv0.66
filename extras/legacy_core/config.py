from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional


def env_bool(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default).strip().lower() in ("1", "true", "yes", "y", "on"))


def env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if v is None:
        return str(default)
    return str(v).strip()


def env_int(name: str, default: str = "0") -> int:
    try:
        return int(env_str(name, default))
    except Exception:
        return int(default)


def env_float(name: str, default: str = "0") -> float:
    try:
        return float(env_str(name, default))
    except Exception:
        return float(default)


def weighting_mode() -> str:
    """
    核心保险丝：
    - legacy（默认）：强制视为关闭深度权重（即使误配 SB_DEPTH_ALPHA）
    - depth：允许深度权重生效（需配合 SB_DEPTH_ALPHA）
    """
    m = env_str("SB_WEIGHTING_MODE", "legacy").lower()
    return "depth" if m == "depth" else "legacy"


def telemetry_enabled() -> bool:
    return env_bool("SB_TELEMETRY", "0")


def _debug_log_path() -> str:
    # DEBUG MODE 固定路径（Cursor 运行时会采集该 NDJSON）
    return "/Users/jpma/Desktop/sbv0.72 12.21版/.cursor/debug.log"


# region agent log
def debug_log(*, hypothesis_id: str, location: str, message: str, data: Optional[dict] = None) -> None:
    """
    写入 NDJSON debug 日志（仅 SB_TELEMETRY=1 时启用）。
    禁止写入密钥/隐私字段；仅写权重与结构化调试信息。
    """
    if not telemetry_enabled():
        return
    payload = {
        "sessionId": "debug-session",
        # 优先使用 SB_DEBUG_RUN_ID，兼容旧 SB_RUN_ID
        "runId": env_str("SB_DEBUG_RUN_ID", env_str("SB_RUN_ID", "run1")),
        "hypothesisId": str(hypothesis_id),
        "location": str(location),
        "message": str(message),
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        # 确保目录存在（某些环境下 .cursor/ 可能不存在）
        Path(_debug_log_path()).parent.mkdir(parents=True, exist_ok=True)
        with open(_debug_log_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        # debug 失败不能影响主流程
        pass
# endregion


def log_telemetry(msg: str) -> None:
    if telemetry_enabled():
        try:
            print(f"[telemetry] {msg}")
        except Exception:
            pass


