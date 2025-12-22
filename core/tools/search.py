from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class SearchResult:
    title: str = ""
    url: Optional[str] = None
    snippet: str = ""
    source: str = "serpapi"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def search_web(query: str, k: int = 5) -> List[SearchResult]:
    """
    SerpAPI 搜索（core 工具层）。

    设计目标：
    - 缺少 SERPAPI_API_KEY 时优雅降级：返回 []
    - 任何异常都不抛出：返回 []
    """
    q = (query or "").strip()
    if not q:
        return []

    api_key = os.getenv("SERPAPI_API_KEY")
    if not api_key:
        return []

    try:
        from langchain_community.utilities import SerpAPIWrapper
    except Exception:
        return []

    try:
        search = SerpAPIWrapper(serpapi_api_key=api_key)

        # 优先结构化 results()
        if hasattr(search, "results"):
            try:
                res = search.results(q)  # type: ignore[attr-defined]
                parsed = _parse_serpapi_results(res, k=k)
                if parsed:
                    return parsed
            except Exception:
                pass

        # fallback: run() 返回 string
        text = search.run(q)
        t = (str(text) if text is not None else "").strip()
        if not t:
            return []
        return [SearchResult(title="", url=None, snippet=t[:800], source="serpapi")]
    except Exception:
        return []


def _parse_serpapi_results(res: Any, k: int = 5) -> List[SearchResult]:
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

    out: List[SearchResult] = []
    kk = max(1, int(k or 5))
    for item in organic[:kk]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or ""
        snippet = item.get("snippet") or item.get("content") or ""
        url: Optional[str] = item.get("link") or item.get("url")
        source = item.get("source") or item.get("displayed_link") or (url or "serpapi")
        out.append(SearchResult(title=str(title), url=url, snippet=str(snippet), source=str(source)))
    return out


