from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

import os

from core.modes import PROMPTS_DIR


class PromptError(ValueError):
    """Prompt 读取/校验失败。"""


@dataclass(frozen=True)
class _CacheEntry:
    mtime_ns: int
    text: str


_LOCK = threading.Lock()
_CACHE: Dict[Path, _CacheEntry] = {}


def _sanitize_prompt_name(prompt_name: str) -> str:
    """
    安全规则（可解释、最小）：
    - 只允许 prompts/ 目录下的单文件名（禁止子目录、禁止 ../）
    - 允许省略 .md
    """
    if prompt_name is None:
        raise PromptError("prompt_name 不能为空。")

    name = str(prompt_name).strip()
    if not name:
        raise PromptError("prompt_name 不能为空。")

    if ("/" in name) or ("\\" in name) or (".." in name):
        raise PromptError(f"非法 prompt_name（禁止子目录/路径穿越）: {prompt_name!r}")

    if not name.endswith(".md"):
        name = name + ".md"

    # 再次确保是“纯文件名”
    if Path(name).name != name:
        raise PromptError(f"非法 prompt_name: {prompt_name!r}")

    return name


def load_prompt(prompt_name: str) -> str:
    """
    读取 prompts/*.md 并缓存（基于文件 mtime 自动失效）。

    - 失败时抛出 PromptError / FileNotFoundError
    - 返回值会 strip()，并保证非空（否则抛 PromptError）
    """
    fname = _sanitize_prompt_name(prompt_name)
    # Card 6：允许通过环境变量覆盖 prompts 目录（迁移/测试用），默认仍是项目 prompts/
    base_dir = Path(os.getenv("SB_PROMPTS_DIR", "")).expanduser() if os.getenv("SB_PROMPTS_DIR") else PROMPTS_DIR
    path = base_dir / fname

    if not path.exists():
        raise FileNotFoundError(f"prompt 不存在: {fname}（期望路径: {path}）")
    if not path.is_file():
        raise PromptError(f"prompt 不是文件: {fname}（期望路径: {path}）")

    try:
        st = path.stat()
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1_000_000_000)))
    except Exception as e:
        raise PromptError(f"读取 prompt stat 失败: {fname}（{e}）") from e

    with _LOCK:
        hit = _CACHE.get(path)
        if hit and hit.mtime_ns == mtime_ns and (hit.text or "").strip():
            return hit.text

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        raise PromptError(f"读取 prompt 失败: {fname}（{e}）") from e

    out = (text or "").strip()
    if not out:
        raise PromptError(f"prompt 文件为空: {fname}")

    with _LOCK:
        _CACHE[path] = _CacheEntry(mtime_ns=mtime_ns, text=out)
    return out


def render_prompt(template: str, variables: Optional[Dict[str, object]] = None) -> str:
    """
    极简渲染：替换 {{key}}。
    """
    out = template or ""
    for k, v in (variables or {}).items():
        out = out.replace("{{" + str(k) + "}}", "" if v is None else str(v))
    return out


def _cache_info() -> Tuple[int, int]:  # pragma: no cover
    """
    返回 (cache_items, cache_chars) 便于调试观测。
    """
    with _LOCK:
        items = len(_CACHE)
        chars = sum(len(e.text or "") for e in _CACHE.values())
        return items, chars


def clear_prompt_cache() -> None:  # pragma: no cover
    with _LOCK:
        _CACHE.clear()


