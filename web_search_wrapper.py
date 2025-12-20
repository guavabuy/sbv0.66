from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def web_search(query: str, k: int = 5) -> List[Dict[str, Any]]:
    """
    统一的联网搜索 wrapper。

    返回:
      list[dict]，每项尽量包含：title/snippet/source/url（缺失则为 None 或空）

    设计目标：
    - 仅在 friend_mode 的 Unknown（或必要 Ambiguous）调用
    - 永不抛异常：失败直接返回 []
    """
    q = (query or "").strip()
    if not q:
        return []

    # 目前默认走 SerpAPI（仓库已依赖 langchain-community + google-search-results）
    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return []

    try:
        from langchain_community.utilities import SerpAPIWrapper
    except Exception:
        return []

    try:
        search = SerpAPIWrapper(serpapi_api_key=api_key)

        # 优先使用 results()（如果可用），它通常返回结构化 dict
        if hasattr(search, "results"):
            try:
                res = search.results(q)  # type: ignore[attr-defined]
                parsed = _parse_serpapi_results(res, k=k)
                if parsed:
                    return parsed
            except Exception:
                # 忽略，继续 fallback
                pass

        # fallback：run() 通常返回 string
        text = search.run(q)
        if text and str(text).strip():
            return [{
                "title": "",
                "snippet": str(text)[:800],
                "source": "serpapi",
                "url": None,
            }]
        return []
    except Exception:
        return []


def _parse_serpapi_results(res: Any, k: int = 5) -> List[Dict[str, Any]]:
    if not isinstance(res, dict):
        return []

    organic = (
        res.get("organic_results")
        or res.get("organic")
        or res.get("results")
        or res.get("items")
    )
    if not isinstance(organic, list):
        return []

    out: List[Dict[str, Any]] = []
    for item in organic[: max(1, int(k or 5))]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        snippet = item.get("snippet") or item.get("content") or ""
        url: Optional[str] = item.get("link") or item.get("url")
        source = item.get("source") or item.get("displayed_link") or (url or "serpapi")
        out.append({
            "title": title,
            "snippet": snippet,
            "source": source,
            "url": url,
        })
    return out


