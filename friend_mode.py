# friend_mode.py
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from web_search_wrapper import web_search
import hashlib


RouteLabel = Literal["Known", "Unknown", "Ambiguous"]

# --- 固定开头模板（验收断言用）---
KNOWN_PREFIX = "我对这件事情的观点是："
UNKNOWN_PREFIX = "我最近对这件事没有了解。"
UNKNOWN_SEARCH_PREFIX = "这些是我刚搜索到的内容："
AMBIGUOUS_PREFIX = "我目前对相关事情的了解："
AMBIGUOUS_INFER_PREFIX = "基于我的人物画像，我对你这个问题的推论是："


@dataclass
class Hit:
    id: Optional[str] = None
    score: Optional[float] = None
    text: str = ""
    source: Optional[str] = None


@dataclass
class RetrievalPack:
    """
    friend_mode 只依赖统一字段：hit_count / top_score / hits(text)
    """
    hit_count: int = 0
    top_score: float = 0.0
    hits: List[Hit] = field(default_factory=list)

    def __post_init__(self):
        # 如果上层没填 hit_count，就用 hits 数量推导
        if (self.hit_count is None or self.hit_count == 0) and self.hits:
            self.hit_count = len(self.hits)

        # 如果上层没填 top_score，就从 hits.score 推导
        if (self.top_score is None or self.top_score == 0.0) and self.hits:
            scores = [h.score for h in self.hits if isinstance(h.score, (int, float))]
            if scores:
                self.top_score = float(max(scores))

    @property
    def contexts(self) -> List[str]:
        # 兼容：把 hit.text 当作 contexts
        return [h.text for h in self.hits if h.text and h.text.strip()]


def _get_threshold(thresholds: Dict, key: str, default):
    try:
        return thresholds.get(key, default)
    except Exception:
        return default


def route_query(
    user_query: str,
    retrieval: RetrievalPack,
    thresholds: Dict,
) -> RouteLabel:
    """
    路由规则：
    - Known: hit_count >= min_hits 且 top_score >= high
    - Unknown: hit_count == 0 或 top_score < low
    - 其他：Ambiguous
    """
    low = float(_get_threshold(thresholds, "low", 0.25))
    high = float(_get_threshold(thresholds, "high", 0.55))
    min_hits = int(_get_threshold(thresholds, "min_hits", 3))

    hit_count = int(getattr(retrieval, "hit_count", 0) or 0)
    top_score = float(getattr(retrieval, "top_score", 0.0) or 0.0)

    if hit_count >= min_hits and top_score >= high:
        return "Known"
    if hit_count == 0 or top_score < low:
        return "Unknown"
    return "Ambiguous"

def _join_contexts(retrieval: RetrievalPack, max_chars: int = 1200) -> str:
    ctxs = retrieval.contexts
    if not ctxs:
        return ""
    text = "\n".join([c.strip() for c in ctxs if c and c.strip()])
    return text[:max_chars].strip()

def _format_corpus_contexts(retrieval: RetrievalPack, max_items: int = 3, max_chars: int = 520) -> str:
    """
    TG 友好：把语料片段压缩成最多 N 条短引用（总长度上限）。
    """
    ctxs = [c.strip() for c in (retrieval.contexts or []) if c and c.strip()]
    if not ctxs:
        return ""
    picked = ctxs[:max_items]
    lines: List[str] = []
    for c in picked:
        cc = c.replace("\n", " ").strip()
        if len(cc) > 180:
            cc = cc[:180].rstrip() + "…"
        lines.append(f"- {cc}")
    out = "\n".join(lines).strip()
    return out[:max_chars].strip()


def split_into_subquestions(text: str) -> List[str]:
    """
    Card 6 (V1): 混合问题分块。
    规则很粗，但要可控：
    - 连接词：另外/以及/同时/还有
    - 断句：；; 。.?？ 换行
    - 最多返回 3 段（避免刷屏）
    """
    t = (text or "").strip()
    if not t:
        return []

    # 先把常见连接词替换成统一分隔符
    for k in ("另外", "以及", "同时", "还有", "再问"):
        t = t.replace(k, "；")

    # 再按断句符号粗分
    parts: List[str] = []
    buf = ""
    seps = set(["；", ";", "。", "？", "?", "\n"])
    for ch in t:
        if ch in seps:
            if buf.strip():
                parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())

    # 去重：避免用户复制粘贴造成的重复块
    uniq: List[str] = []
    for p in parts:
        pp = p.strip().lstrip("，,、:：").strip()
        if pp and pp not in uniq:
            uniq.append(pp)

    return uniq[:3] if len(uniq) > 3 else uniq


def needs_fresh_info(user_query: str) -> bool:
    """
    Card 5: Ambiguous 情况下的“时效词”启发式。
    只做关键词规则（轻量、可解释）。
    """
    q = (user_query or "").strip().lower()
    if not q:
        return False

    keywords = [
        # 中文
        "今天", "最新", "刚发生", "刚刚", "现在", "当前", "实时",
        "价格", "多少钱", "报价", "涨跌", "行情",
        "日期", "几号", "几点", "时间", "北京时间",
        "新闻", "公告", "发布", "更新",
        "过去24小时", "24小时", "昨晚", "今早", "本周", "本月",
        # 英文
        "today", "latest", "just happened", "right now", "now", "current", "real-time",
        "price", "quote", "market", "rate",
        "date", "time",
        "news", "announcement", "release", "update",
    ]
    return any(k in q for k in keywords)


def is_high_risk(user_query: str) -> bool:
    """
    Card 7: 高风险领域免责声明触发（投资/医疗/法律）。
    仅关键词启发式，命中则在 Ambiguous 推论段末尾追加免责声明。
    """
    q = (user_query or "").strip().lower()
    if not q:
        return False

    keywords = [
        # 投资/交易
        "投资", "收益", "回报", "买", "卖", "买入", "卖出", "交易", "仓位", "杠杆", "合约", "期货", "期权",
        "股票", "基金", "币", "btc", "eth", "price", "buy", "sell", "profit", "roi",
        # 医疗
        "医疗", "诊断", "处方", "药", "用药", "副作用", "症状", "治疗", "检查", "手术", "医生",
        "diagnosis", "treatment", "medicine", "drug", "prescription",
        # 法律
        "法律", "诉讼", "起诉", "合同", "协议", "违约", "律师", "仲裁", "侵权", "责任",
        "lawsuit", "contract", "legal", "attorney",
    ]
    return any(k in q for k in keywords)


def _format_search_lines(results: List[dict], max_items: int = 5) -> List[str]:
    lines: List[str] = []
    for r in results[:max_items]:
        if not isinstance(r, dict):
            continue
        title = (r.get("title") or "").strip()
        snippet = (r.get("snippet") or "").strip()
        url = (r.get("url") or "").strip()
        head = title or ((snippet[:40] + "…") if len(snippet) > 40 else snippet)
        tail = f"（{url}）" if url else ""
        if head:
            lines.append(f"- {head}{tail}")
    return lines


def _chunk_id(hit: Hit, idx: int) -> str:
    """
    用于可观测性：优先用 hit.id，否则用文本 hash（短）。
    """
    if hit.id:
        return str(hit.id)
    h = hashlib.sha1((hit.text or "").encode("utf-8", errors="ignore")).hexdigest()[:12]
    return f"h{idx}:{h}"


def _telemetry_web_search(telemetry: Optional[Dict], query: str, k: int) -> List[dict]:
    """
    包装 web_search，用于记录调用情况（不会改变原行为）。
    """
    results: List[dict] = []
    ok = False
    try:
        results = web_search(query, k=k) or []
        ok = bool(results)
        return results
    finally:
        if telemetry is not None:
            telemetry.setdefault("web_search", []).append({
                "query": query,
                "k": k,
                "ok": ok,
                "n": len(results) if isinstance(results, list) else 0,
            })


def _is_cjk(s: str) -> bool:
    import re
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", s or ""))


def _normalize(s: str) -> str:
    import re
    if not s:
        return ""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def _extract_terms(s: str) -> List[str]:
    """
    仅用于“子问题->命中 hit.text”过滤的轻量分词（不引入额外依赖）。
    """
    import re
    s = _normalize(s)
    if not s:
        return []
    if _is_cjk(s):
        tokens = re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]{2,}", s)
        chars = re.findall(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]", s)
        bigrams = ["".join(chars[i:i + 2]) for i in range(0, max(0, len(chars) - 1))]
        return [t for t in (tokens + bigrams) if t]
    return re.findall(r"[a-z0-9]{2,}", s)


def _subpack_for_query(retrieval: RetrievalPack, subq: str) -> RetrievalPack:
    """
    Card 6: 从“整体检索结果”里，为某个 subquestion 选出更相关的 hits。
    V1：只做关键词子串匹配；命中越多，top_score 越高（用于路由）。
    """
    terms = _extract_terms(subq)
    if not terms or not retrieval or not retrieval.hits:
        return RetrievalPack(hit_count=0, top_score=0.0, hits=[])

    scored_hits: List[Tuple[float, Hit]] = []
    for h in retrieval.hits:
        text = _normalize(h.text)
        if not text:
            continue
        hit_terms = 0
        for t in set(terms):
            if t and t in text:
                hit_terms += 1
        if hit_terms <= 0:
            continue

        # 用覆盖率作为“伪 score”；如果命中本身带 score，则优先使用它作为路由依据
        pseudo = hit_terms / max(1, len(set(terms)))
        base_score = float(h.score) if isinstance(h.score, (int, float)) else float(pseudo)
        scored_hits.append((base_score, h))

    if not scored_hits:
        return RetrievalPack(hit_count=0, top_score=0.0, hits=[])

    scored_hits.sort(key=lambda x: x[0], reverse=True)
    hits = [h for _, h in scored_hits]
    top_score = float(max(s for s, _ in scored_hits))
    return RetrievalPack(hit_count=len(hits), top_score=top_score, hits=hits)


def _render_one(
    user_query: str,
    retrieval: RetrievalPack,
    user_profile: str,
    brain_memory: str,
    thresholds: Dict,
    telemetry: Optional[Dict] = None,
    seg_idx: Optional[int] = None,
) -> str:
    route = route_query(user_query, retrieval, thresholds)
    ctx = _join_contexts(retrieval)

    if telemetry is not None:
        telemetry.setdefault("segments", []).append({
            "idx": seg_idx,
            "query": user_query,
            "route": route,
            "top_score": float(getattr(retrieval, "top_score", 0.0) or 0.0),
            "hit_count": int(getattr(retrieval, "hit_count", 0) or 0),
            "used_chunks": [_chunk_id(h, i) for i, h in enumerate(getattr(retrieval, "hits", []) or [])][:12],
        })

    if route == "Unknown":
        results = _telemetry_web_search(telemetry, user_query, k=5)
        if not results:
            return (
                f"{UNKNOWN_PREFIX}\n\n"
                "这些是我刚搜索到的内容：\n"
                "我现在搜不到相关信息（可能是网络不可用或搜索服务不可用）。"
            )


        # 压缩：最多 3 条
        lines = _format_search_lines(results, max_items=3)
        if not lines:
            return (
                f"{UNKNOWN_PREFIX}\n\n"
                "这些是我刚搜索到的内容：\n"
                "我现在搜不到相关信息（可能是网络不可用或搜索服务不可用）。"
            )
        return (
            f"{UNKNOWN_PREFIX}\n\n"
            f"{UNKNOWN_SEARCH_PREFIX}\n"
            + "\n".join(lines[:3])
        )

    if route == "Known":
        parts = [KNOWN_PREFIX]
        # 压缩：只展示少量片段
        brief_ctx = _format_corpus_contexts(retrieval, max_items=3, max_chars=520)
        if brief_ctx:
            parts.append(f"\n我在你的资料库里找到的相关片段是：\n{brief_ctx}\n")
        parts.append(
            "\n我的建议：\n"
            "- 你先说清楚你更在意：收益/风险/效率/学习哪个？\n"
            "- 我再给你 1 个最小可执行的下一步。"
        )
        return "\n".join(parts).strip()

    parts = [AMBIGUOUS_PREFIX]
    brief_ctx = _format_corpus_contexts(retrieval, max_items=3, max_chars=520)
    if brief_ctx:
        parts.append(f"\n我在你的资料库里找到的“可能相关”片段是：\n{brief_ctx}\n")
    else:
        parts.append("\n你的资料库里没有特别直接命中的片段，我先基于线索做推断。\n")

    if needs_fresh_info(user_query):
        results = _telemetry_web_search(telemetry, user_query, k=5)
        if results:
            # 压缩：最多 3 条
            lines = _format_search_lines(results, max_items=3)
            if lines:
                parts.append("\n我补充查了一下最新信息（联网）：\n" + "\n".join(lines) + "\n")
        else:
            parts.append("\n我尝试联网补充最新信息，但现在搜不到（可能是网络不可用或搜索服务不可用）。\n")

    parts.append(
        f"\n{AMBIGUOUS_INFER_PREFIX}\n"
        "我先给你一个合理假设；你补 1-2 个关键条件我就能更确定。\n"
        "直接回我：你的目标 + 你最担心什么。"
    )
    if is_high_risk(user_query):
        parts.append("这只是我的推论/不构成建议。")
    return "\n".join(parts).strip()


def answer_telegram(
    user_query: str,
    retrieval: RetrievalPack,
    user_profile: str,
    brain_memory: str,
    thresholds: Optional[Dict] = None,
) -> str:
    thresholds = thresholds or {"low": 0.25, "high": 0.55, "min_hits": 3}

    # Card 6: 如果能粗分成多段，则每段分别 route+render
    subqs = split_into_subquestions(user_query)
    if len(subqs) >= 2:
        rendered: List[str] = []
        for i, sq in enumerate(subqs):
            subpack = _subpack_for_query(retrieval, sq)
            rendered.append(_render_one(sq, subpack, user_profile, brain_memory, thresholds, telemetry=None, seg_idx=i))
        return "\n\n".join([r.strip() for r in rendered if r and r.strip()]).strip()

    return _render_one(user_query, retrieval, user_profile, brain_memory, thresholds, telemetry=None, seg_idx=0)


def answer_telegram_with_meta(
    user_query: str,
    retrieval: RetrievalPack,
    user_profile: str,
    brain_memory: str,
    thresholds: Optional[Dict] = None,
) -> Tuple[str, Dict]:
    """
    Card 9：可观测性版本。返回 (text, meta)。
    meta 字段至少包含：route/top_score/hit_count/web_search/used_chunks（按 segments 形式记录）。
    """
    thresholds = thresholds or {"low": 0.25, "high": 0.55, "min_hits": 3}
    telemetry: Dict = {"segments": [], "web_search": []}

    subqs = split_into_subquestions(user_query)
    if len(subqs) >= 2:
        rendered: List[str] = []
        for i, sq in enumerate(subqs):
            subpack = _subpack_for_query(retrieval, sq)
            rendered.append(_render_one(sq, subpack, user_profile, brain_memory, thresholds, telemetry=telemetry, seg_idx=i))
        text = "\n\n".join([r.strip() for r in rendered if r and r.strip()]).strip()
    else:
        text = _render_one(user_query, retrieval, user_profile, brain_memory, thresholds, telemetry=telemetry, seg_idx=0)

    # 聚合字段（便于 tg_bot/日志直接看）
    segs = telemetry.get("segments") or []
    telemetry["route"] = [s.get("route") for s in segs]
    telemetry["top_score"] = [s.get("top_score") for s in segs]
    telemetry["hit_count"] = [s.get("hit_count") for s in segs]
    telemetry["used_chunks"] = [s.get("used_chunks") for s in segs]
    return text, telemetry