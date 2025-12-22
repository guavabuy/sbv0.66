from pathlib import Path
from typing import Optional

def read_text_file(path: Path) -> str:
    """
    安全读取文本文件，不存在或报错时返回空字符串。
    """
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

def ensure_dir(path: Path) -> Path:
    """
    确保目录存在。
    """
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
    return path

