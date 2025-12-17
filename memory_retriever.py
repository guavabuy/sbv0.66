# memory_retriever.py
import json
import re
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

CORPUS_PATH = "outputs/corpus.jsonl"

def _parse_dt(s: str) -> Optional[datetime]:
    if not s:
        return None
    try:
        # 兼容 "Z"
        s2 = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s2)
    except Exception:
        return None

def _infer_dt_from_notion_filename(file_path: str) -> Optional[datetime]:
    # 你 notion 文件名类似：data_sources/notion/2025-12-17T10_44_22+00_00_xxx.md
    m = re.search(r"/notion/([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}_[0-9]{2}_[0-9]{2}[^_/]*)_", file_path.replace("\\", "/"))
    if not m:
        return None
    ts = m.group(1)
    # 把 "_" 还原成 ":"，只对时间部分替换
    ts = ts.replace("T", "T").replace("_", ":")
    # 可能把 +00_00 也替换成 +00:00
    ts = ts.replace("+", "+").replace(":+", "+")
    ts = ts.replace("+00:00", "+00:00")  # 无伤
    # 最稳：把最后一个 "+HH:MM" 修好
    ts = re.sub(r"\+([0-9]{2}):([0-9]{2})", r"+\1:\2", ts)

    # 如果没有时区，默认 UTC
    if "+" not in ts and "Z" not in ts:
        ts = ts + "+00:00"

    return _parse_dt(ts)

def get_recent_corpus_snippets(days: int = 30, max_items: int = 18, max_chars: int = 260) -> str:
    try:
        with open(CORPUS_PATH, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return ""

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    items: List[Dict[str, Any]] = []
    for ln in lines:
        try:
            obj = json.loads(ln)
        except Exception:
            continue

        source = obj.get("source", "unknown")
        file_path = obj.get("file_path", "")
        created_at = obj.get("created_at")

        dt = _parse_dt(created_at) if created_at else None
        if dt is None and source == "notion":
            dt = _infer_dt_from_notion_filename(file_path)

        # 没时间戳的先不纳入“最近”
        if dt is None:
            continue
        if dt < cutoff:
            continue

        text = (obj.get("text") or "").strip().replace("\n", " ")
        if not text:
            continue

        items.append({
            "dt": dt,
            "source": source,
            "weight": float(obj.get("weight", 0.0)),
            "file_path": file_path,
            "text": text[:max_chars]
        })

    # 最近优先，其次权重
    items.sort(key=lambda x: (x["dt"], x["weight"]), reverse=True)

    picked = items[:max_items]
    if not picked:
        return ""

    # 简单分组输出
    out = []
    out.append(f"【最近{days}天 Notion/X 摘要（从语料库自动抽取）】")
    for it in picked:
        dt_str = it["dt"].astimezone(timezone.utc).strftime("%Y-%m-%d")
        out.append(f"- {dt_str} | {it['source']} | w={it['weight']:.3f} | {it['text']}")
    return "\n".join(out)
