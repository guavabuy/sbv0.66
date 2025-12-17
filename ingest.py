import os
import json
import hashlib
import argparse
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Iterable, List, Dict, Any, Optional, Tuple

DATA_DIR = "data_sources"
STATE_PATH = "state/sync_state.json"
OUT_CORPUS = "outputs/corpus.jsonl"

# ---------- utilities ----------

def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_PATH):
        return {"files": {}, "updated_at": None}
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: Dict[str, Any]) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def iter_files(root: str) -> Iterable[str]:
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if fn.startswith("."):
                continue
            yield os.path.join(dirpath, fn)

def guess_source(path: str) -> str:
    p = path.replace("\\", "/").lower()
    if "/notion/" in p:
        return "notion"
    if "/x/" in p or "/twitter/" in p:
        return "x"
    if "/trades/" in p or "/hyperliquid/" in p:
        return "trades"
    return "unknown"

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

# ---------- weighting (v0 heuristics) ----------

SOURCE_BASE_WEIGHT = {
    "notion": 0.65,
    "x": 0.35,
    "trades": 0.80,
    "unknown": 0.40,
}

KEYWORDS_BOOST = [
    "原则", "框架", "复盘", "策略", "逻辑", "假设", "如果", "因此", "结论",
    "I think", "my rule", "thesis", "framework", "if", "therefore", "because"
]

def content_signal(text: str) -> float:
    t = text.strip()
    if not t:
        return 0.1

    # 纯链接/过短降权
    if len(t) < 40:
        return 0.25
    if t.startswith("http://") or t.startswith("https://"):
        return 0.2

    score = 1.0

    # 长度加成（到一定上限）
    score *= min(1.4, 0.8 + len(t) / 2000)

    # 结构化关键词加成
    hit = sum(1 for k in KEYWORDS_BOOST if k.lower() in t.lower())
    score *= min(1.6, 1.0 + hit * 0.08)

    return max(0.1, min(2.0, score))

def compute_weight(source: str, text: str) -> float:
    base = SOURCE_BASE_WEIGHT.get(source, 0.4)
    sig = content_signal(text)
    return round(base * sig, 4)

# ---------- chunking ----------

def chunk_text(text: str, max_chars: int = 1200, overlap: int = 120) -> List[str]:
    t = " ".join(text.split())
    if len(t) <= max_chars:
        return [t]
    out = []
    start = 0
    while start < len(t):
        end = min(len(t), start + max_chars)
        out.append(t[start:end])
        if end == len(t):
            break
        start = max(0, end - overlap)
    return out

# ---------- parsers (keep flexible) ----------

def read_text_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def parse_json_file(path: str) -> Any:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return json.load(f)

def extract_items(path: str, source: str) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Return: list of (text, extra_meta)
    Supports:
      - .md/.txt: as one document
      - .json: tries to interpret as list of posts, otherwise dumps fields
    """
    ext = os.path.splitext(path)[1].lower()

    if ext in [".md", ".txt"]:
        text = read_text_file(path)
        return [(text, {})]

    if ext == ".json":
        data = parse_json_file(path)

        # case 1: list of tweets/posts
        if isinstance(data, list):
            items = []
            for obj in data:
                if isinstance(obj, dict):
                    txt = obj.get("text") or obj.get("content") or obj.get("full_text") or ""
                    if not txt:
                        continue
                    meta = {
                        "id": obj.get("id") or obj.get("tweet_id") or obj.get("uuid"),
                        "url": obj.get("url"),
                        "created_at": obj.get("created_at") or obj.get("time"),
                    }
                    items.append((txt, meta))
            if items:
                return items

        # case 2: dict with posts field
        if isinstance(data, dict):
            for key in ["tweets", "posts", "items", "data"]:
                if key in data and isinstance(data[key], list):
                    items = []
                    for obj in data[key]:
                        if isinstance(obj, dict):
                            txt = obj.get("text") or obj.get("content") or ""
                            if not txt:
                                continue
                            meta = {"id": obj.get("id"), "created_at": obj.get("created_at")}
                            items.append((txt, meta))
                    if items:
                        return items

            # fallback: stringify dict (not ideal but keeps you moving)
            return [(json.dumps(data, ensure_ascii=False), {"json_fallback": True})]

    # unknown file type: read as text
    try:
        return [(read_text_file(path), {"binary_as_text": True})]
    except Exception:
        return []

# ---------- data model ----------

@dataclass
class MemoryChunk:
    uid: str
    source: str
    file_path: str
    created_at: Optional[str]
    ingested_at: str
    weight: float
    text: str
    meta: Dict[str, Any]

def make_uid(source: str, file_path: str, idx: int, text: str) -> str:
    h = hashlib.sha1()
    h.update(source.encode("utf-8"))
    h.update(file_path.encode("utf-8"))
    h.update(str(idx).encode("utf-8"))
    h.update(text[:200].encode("utf-8", errors="ignore"))
    return h.hexdigest()

# ---------- main ingest ----------

def ingest(full: bool = False) -> Dict[str, Any]:
    state = load_state()
    seen_files: Dict[str, str] = state.get("files", {})

    new_chunks: List[MemoryChunk] = []

    for path in iter_files(DATA_DIR):
        rel = path.replace("\\", "/")
        file_hash = sha256_file(path)

        if (not full) and rel in seen_files and seen_files[rel] == file_hash:
            continue  # unchanged

        source = guess_source(rel)
        items = extract_items(path, source)

        for item_text, extra in items:
            # split into chunks
            chunks = chunk_text(item_text)
            for i, ck in enumerate(chunks):
                w = compute_weight(source, ck)
                uid = make_uid(source, rel, i, ck)
                new_chunks.append(MemoryChunk(
                    uid=uid,
                    source=source,
                    file_path=rel,
                    created_at=extra.get("created_at"),
                    ingested_at=now_iso(),
                    weight=w,
                    text=ck,
                    meta=extra,
                ))

        # update state for this file
        seen_files[rel] = file_hash

    # append to corpus.jsonl
    if new_chunks:
        with open(OUT_CORPUS, "a", encoding="utf-8") as f:
            for mc in new_chunks:
                f.write(json.dumps(asdict(mc), ensure_ascii=False) + "\n")

    state["files"] = seen_files
    save_state(state)

    return {
        "added_chunks": len(new_chunks),
        "corpus": OUT_CORPUS,
        "state": STATE_PATH,
    }

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="force re-ingest all files")
    args = ap.parse_args()

    result = ingest(full=args.full)
    print(json.dumps(result, ensure_ascii=False, indent=2))