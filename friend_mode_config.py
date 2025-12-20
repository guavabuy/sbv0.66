# friend_mode_config.py
import os
from typing import Dict, Optional

DEFAULT_LOW_TH = 0.25
DEFAULT_HIGH_TH = 0.55
DEFAULT_MIN_HITS = 3


def _parse_bool_env(val: Optional[str]) -> bool:
    """
    DoD:
      - 默认 TG_FRIEND_MODE 不存在或为 "0" => False
      - 非法值也按 False（更安全，不会意外开启）
    """
    if val is None:
        return False
    v = val.strip().lower()
    if v in ("1", "true", "yes", "y", "on"):
        return True
    if v in ("0", "false", "no", "n", "off", ""):
        return False
    return False


def _parse_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except Exception:
        return default


def _parse_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except Exception:
        return default


def get_tg_friend_mode_enabled() -> bool:
    return _parse_bool_env(os.getenv("TG_FRIEND_MODE"))


def get_thresholds() -> Dict[str, float]:
    low = _parse_float_env("TG_LOW_TH", DEFAULT_LOW_TH)
    high = _parse_float_env("TG_HIGH_TH", DEFAULT_HIGH_TH)
    min_hits = _parse_int_env("TG_MIN_HITS", DEFAULT_MIN_HITS)
    return {"low": low, "high": high, "min_hits": min_hits}
