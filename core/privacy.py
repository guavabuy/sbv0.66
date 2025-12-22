from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Sequence, Union


PRIVATE_BASENAMES = {
    # Card 3：私密日志（物理隔离入口）
    "brain_memory.md",
}


def exclude_file(path_or_name: Union[str, Path]) -> bool:
    """
    判断一个文件是否属于“默认应被隐私闸门排除”的私密文件。
    规则：只看 basename（物理隔离），避免路径变化绕过。
    """
    try:
        p = Path(str(path_or_name))
        return p.name in PRIVATE_BASENAMES
    except Exception:
        return False


def should_include_private(mode: str) -> bool:
    """
    默认安全：仅 self 模式允许注入私密文件；其他/未知模式一律不允许。
    """
    m = (mode or "").strip().lower()
    return m == "self"


def apply_privacy_gate(mode: str, files_to_load: Sequence[Union[str, Path]]) -> List[Path]:
    """
    输入“候选要加载的文件列表”，输出“通过隐私闸门后允许加载的文件列表”。

    强约束：
    - mode != self 时，任何被标记为私密的文件（如 brain_memory.md）都会被过滤掉
    - 未知 mode 也按非 self 处理（默认拒绝），保证未来新增模式默认安全
    """
    allow_private = should_include_private(mode)

    out: List[Path] = []
    seen = set()
    for f in files_to_load or []:
        try:
            p = Path(str(f))
        except Exception:
            continue

        # 去重：保持顺序
        key = str(p)
        if key in seen:
            continue
        seen.add(key)

        if (not allow_private) and exclude_file(p):
            continue
        out.append(p)

    return out


