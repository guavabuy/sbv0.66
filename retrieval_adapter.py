# retrieval_adapter.py
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from friend_mode import Hit, RetrievalPack


_SCORE_KEYS = ("score", "similarity", "sim", "cosine", "rerank_score", "distance")
_TEXT_KEYS = ("text", "content", "chunk", "page_content", "document", "doc", "context")
_ID_KEYS = ("id", "doc_id", "chunk_id", "uuid")
_SOURCE_KEYS = ("source", "url", "path", "file", "origin")


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _get_first(d: Dict, keys: Tuple[str, ...]) -> Any:
    for k in keys:
        if k in d:
            return d.get(k)
    return None


def _doc_to_hit(doc: Any, score: Optional[float] = None) -> Hit:
    # LangChain Document 兼容：doc.page_content + doc.metadata
    text = ""
    doc_id = None
    source = None

    if hasattr(doc, "page_content"):
        text = getattr(doc, "page_content") or ""
        meta = getattr(doc, "metadata", None) or {}
        if isinstance(meta, dict):
            doc_id = meta.get("id") or meta.get("doc_id") or meta.get("chunk_id")
            source = meta.get("source") or meta.get("url") or meta.get("path")
    elif isinstance(doc, str):
        text = doc
    elif isinstance(doc, dict):
        text = str(_get_first(doc, _TEXT_KEYS) or "")
        doc_id = _get_first(doc, _ID_KEYS)
        source = _get_first(doc, _SOURCE_KEYS)
        s = _get_first(doc, _SCORE_KEYS)
        if _is_number(s):
            score = float(s)
    else:
        # 兜底：尽量 stringify
        text = str(doc)

    return Hit(id=str(doc_id) if doc_id is not None else None,
               score=float(score) if _is_number(score) else None,
               text=text,
               source=str(source) if source is not None else None)


def adapt_retrieval(raw: Any) -> RetrievalPack:
    """
    任意 raw -> RetrievalPack
    适配失败 => 空 pack（=> friend_mode 会 Unknown）
    """
    try:
        if raw is None:
            return RetrievalPack(hit_count=0, top_score=0.0, hits=[])

        if isinstance(raw, RetrievalPack):
            return raw

        hits: List[Hit] = []

        # 1) dict 结构（你测试用的就是这个）
        if isinstance(raw, dict):
            possible_hits = (
                raw.get("hits")
                or raw.get("results")
                or raw.get("matches")
                or raw.get("documents")
                or raw.get("data")
            )
            if isinstance(possible_hits, list):
                for item in possible_hits:
                    hits.extend(_adapt_one_item(item))

            # 兼容 {"context": "..."} / {"contexts":[...]}
            ctx = raw.get("context") or raw.get("contexts")
            if isinstance(ctx, str) and ctx.strip():
                hits.append(Hit(text=ctx.strip()))
            elif isinstance(ctx, list):
                for c in ctx:
                    if isinstance(c, str) and c.strip():
                        hits.append(Hit(text=c.strip()))

        # 2) list/tuple 结构
        elif isinstance(raw, (list, tuple)):
            for item in raw:
                hits.extend(_adapt_one_item(item))

        # 3) 单对象
        else:
            hits.append(_doc_to_hit(raw, None))

        # 过滤空文本
        valid_hits = [h for h in hits if h.text and str(h.text).strip()]
        hit_count = len(valid_hits)

        scores = [h.score for h in valid_hits if _is_number(h.score)]
        top_score = float(max(scores)) if scores else 0.0

        return RetrievalPack(hit_count=hit_count, top_score=top_score, hits=valid_hits)

    except Exception:
        return RetrievalPack(hit_count=0, top_score=0.0, hits=[])


def _adapt_one_item(item: Any) -> List[Hit]:
    out: List[Hit] = []

    # tuple: (doc/text, score)
    if isinstance(item, tuple) and len(item) == 2:
        a, b = item
        if _is_number(b):
            out.append(_doc_to_hit(a, float(b)))
            return out
        if _is_number(a):
            out.append(_doc_to_hit(b, float(a)))
            return out
        out.append(_doc_to_hit(item, None))
        return out

    # dict hit: {"text": "...", "score": 0.6}
    if isinstance(item, dict):
        text = _get_first(item, _TEXT_KEYS)
        score = _get_first(item, _SCORE_KEYS)
        doc_id = _get_first(item, _ID_KEYS) if "_ID_KEYS" in globals() else item.get("id")
        source = _get_first(item, _SOURCE_KEYS) if "_SOURCE_KEYS" in globals() else item.get("source")

        # 嵌套 document 结构：{"document": {...}, "score": ...}
        if isinstance(text, dict):
            out.append(_doc_to_hit(text, float(score) if _is_number(score) else None))
            return out

        out.append(
            Hit(
                id=str(doc_id) if doc_id is not None else None,
                score=float(score) if _is_number(score) else None,
                text=str(text) if text is not None else "",
                source=str(source) if source is not None else None,
            )
        )
        return out

    # Document / string / other
    out.append(_doc_to_hit(item, None))
    return out