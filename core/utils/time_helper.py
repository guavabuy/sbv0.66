from datetime import datetime, timezone
import re
from typing import Optional

def parse_dt(s: str) -> Optional[datetime]:
    """
    统一解析 ISO 格式时间字符串。
    """
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def infer_dt_from_notion_filename(file_path: str) -> Optional[datetime]:
    """
    从 Notion 导出的文件名中提取时间戳。
    """
    m = re.search(
        r"/notion/([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}_[0-9]{2}_[0-9]{2}[^_/]*)_",
        (file_path or "").replace("\\", "/"),
    )
    if not m:
        return None
    ts = m.group(1).replace("_", ":")
    if "+" not in ts and "Z" not in ts:
        ts = ts + "+00:00"
    return parse_dt(ts)

