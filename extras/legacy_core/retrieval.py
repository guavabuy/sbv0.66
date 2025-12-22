from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import debug_log, env_bool, env_float, log_telemetry, weighting_mode
from .weighting import compute_cog_weight, score_depth, score_time


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _infer_dt_from_notion_filename(file_path: str) -> Optional[datetime]:
    m = re.search(
        r"/notion/([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}_[0-9]{2}_[0-9]{2}[^_/]*)_",
        (file_path or "").replace("\\", "/"),
    )
    if not m:
        return None
    ts = m.group(1).replace("_", ":")
    if "+" not in ts and "Z" not in ts:
        ts = ts + "+00:00"
    return _parse_dt(ts)


def _iter_last_lines(path: Path, max_lines: int) -> Iterable[str]:
    """
    轻量 tail：不做复杂 seek，直接读全文后截断（对 max_lines 较小足够）。
    未来 corpus 变大可替换为真正的 tail 实现。
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    if max_lines <= 0:
        return lines
    return lines[-int(max_lines) :]


def _tokenize(text: str) -> List[str]:
    """
    轻量分词：
    - 英文/数字：按 word
    - 中文：按连续中文串做 2-gram（比按单字更稳）
    """
    t = (text or "").lower()
    out: List[str] = []

    out.extend(re.findall(r"[a-z0-9]{2,}", t))

    for m in re.finditer(r"[\u4e00-\u9fff]+", t):
        s = m.group(0)
        if len(s) == 1:
            out.append(s)
            continue
        for i in range(len(s) - 1):
            out.append(s[i : i + 2])

    return out


def base_similarity(query: str, text: str) -> float:
    """
    base_similarity ∈ [0,1]：用 token overlap 的 cosine（binary）近似。
    """
    q = _tokenize(query)
    d = _tokenize(text)
    if not q or not d:
        return 0.0
    qset = set(q)
    dset = set(d)
    inter = len(qset & dset)
    if inter <= 0:
        return 0.0
    return float(min(1.0, inter / math.sqrt(len(qset) * len(dset))))


@dataclass
class RetrievalHit:
    uid: str
    text: str
    source: str
    file_path: str
    created_at: Optional[str]
    meta: Dict[str, Any]
    source_id: Optional[str]
    base_similarity: float
    depth_score: float
    age_days: Optional[float]
    cog_weight: float
    time_weight: float
    final_score: float


def rerank_with_weights(
    hits: List[RetrievalHit],
    *,
    enable_cog: bool,
    enable_decay: bool,
) -> List[RetrievalHit]:
    """
    只做“排序阶段”的融合打分：
    final_score = base_similarity * (cog_weight if enable_cog else 1) * (time_weight if enable_decay else 1)
    """
    for h in hits:
        mult = 1.0
        if enable_cog:
            mult *= float(h.cog_weight)
        if enable_decay:
            mult *= float(h.time_weight)
        h.final_score = float(h.base_similarity) * mult
    hits.sort(key=lambda x: x.final_score, reverse=True)
    return hits


def retrieve_from_corpus(
    *,
    corpus_path: Path,
    query: str,
    top_k: int = 6,
    max_scan: int = 4000,
    min_similarity: float = 0.05,
    now: Optional[datetime] = None,
) -> List[RetrievalHit]:
    """
    从 corpus.jsonl 扫描候选 → 计算 base_similarity → 附加 cog/time 权重 → 只在排序阶段融合。
    """
    q = (query or "").strip()
    if not q:
        return []
    if not corpus_path.exists() or not corpus_path.is_file():
        return []

    now_dt = now if now is not None else datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    # 开关与配置
    decay_enabled = env_bool("SB_DECAY_ENABLED", "0")
    decay_window_days = env_float("SB_DECAY_WINDOW_DAYS", "15")
    decay_half_life_days = env_float("SB_DECAY_HALF_LIFE_DAYS", "3")
    decay_floor = env_float("SB_DECAY_FLOOR", "0.05")

    mode = weighting_mode()
    depth_alpha = env_float("SB_DEPTH_ALPHA", "0")
    if mode != "depth":
        depth_alpha = 0.0  # 保险丝：legacy 强制关闭深度权重
    # 进一步保险：只有 alpha != 0 才启用 cog_weight 乘子
    # （否则即使 corpus 里历史遗留 cog_weight != 1，也不会在默认配置下影响排序）
    cog_enabled = (mode == "depth" and abs(depth_alpha) > 1e-12)

    # region agent log
    debug_log(
        hypothesis_id="H1",
        location="core/retrieval.py:retrieve_from_corpus",
        message="enter",
        data={
            "top_k": int(top_k),
            "max_scan": int(max_scan),
            "min_similarity": float(min_similarity),
            "decay_enabled": bool(decay_enabled),
            "cog_enabled": bool(cog_enabled),
            "weighting_mode": mode,
            "depth_alpha": float(depth_alpha),
        },
    )
    # endregion agent log

    hits: List[RetrievalHit] = []
    for ln in _iter_last_lines(corpus_path, int(max_scan)):
        try:
            obj = json.loads(ln)
        except Exception:
            continue

        text = (obj.get("text") or "").strip()
        if not text:
            continue

        sim = base_similarity(q, text)
        if sim < float(min_similarity):
            continue

        source = obj.get("source", "unknown")
        file_path = obj.get("file_path", "") or ""
        created_at = obj.get("created_at")

        # CARD-06：时间戳缺失 -> time_weight=1（默认不改变旧行为）
        # 因此这里仅在显式 created_at 存在时才解析时间；缺失时不从文件名推断。
        dt = _parse_dt(created_at) if created_at else None
        age_days: Optional[float] = None
        if dt is not None:
            age_days = (now_dt - dt).total_seconds() / 86400.0
            if age_days < 0:
                age_days = 0.0

        tw = 1.0
        # created_at 缺失：保持 time_weight=1（不做衰减）
        if decay_enabled and created_at:
            tw = score_time(
                dt,
                now=now_dt,
                window_days=decay_window_days,
                half_life_days=decay_half_life_days,
                floor=decay_floor,
            )

        # 向后兼容策略（CARD-06）：
        # - depth_score 缺失：按 0.5（中性，不逼重 ingest）
        # - cog_weight 缺失：按 1
        # - 时间戳缺失：time_weight=1（score_time 内部已处理）
        #
        # cog_weight：仅在启用时才读取/计算；否则强制 1（保证 legacy 不被历史数据影响）
        ds_val = obj.get("depth_score", None)
        if ds_val is None:
            ds_val = 0.5
        try:
            ds_f = float(ds_val)
        except Exception:
            ds_f = 0.5

        cw = 1.0
        if cog_enabled:
            cw = obj.get("cog_weight", None)
            if cw is None:
                cw = compute_cog_weight(float(ds_f), alpha=float(depth_alpha))
        try:
            cw_f = float(cw)
        except Exception:
            cw_f = 1.0

        meta = obj.get("meta") or {}
        source_id = None
        if isinstance(meta, dict):
            source_id = meta.get("id") or meta.get("url")
        if not source_id:
            source_id = obj.get("uid") or None

        hit = RetrievalHit(
            uid=str(obj.get("uid") or ""),
            text=text,
            source=str(source),
            file_path=str(file_path),
            created_at=str(created_at) if created_at else None,
            meta=meta,
            source_id=str(source_id) if source_id else None,
            base_similarity=float(sim),
            depth_score=float(ds_f),
            age_days=float(age_days) if age_days is not None else None,
            cog_weight=float(cw_f),
            time_weight=float(tw),
            final_score=float(sim),  # 初始=base；后续 rerank 再融合
        )
        hits.append(hit)

    # 去重（避免同一条记录被重复召回污染 topK）
    # 现实中 corpus.jsonl 可能因为手工追加/异常运行产生重复行；ingest 也不会强制去重。
    # 这里做最小侵入的去重：优先按 uid；uid 缺失则用 (source,file_path,created_at,text_head)。
    before_n = len(hits)
    best_by_key: Dict[str, RetrievalHit] = {}
    for h in hits:
        if h.uid:
            key = f"uid:{h.uid}"
        else:
            head = (h.text or "")[:120]
            key = f"fp:{h.source}|{h.file_path}|{h.created_at or ''}|{head}"

        prev = best_by_key.get(key)
        if prev is None:
            best_by_key[key] = h
            continue
        # 保留更高 base_similarity 的那个；若相同，保留已有（保持稳定）
        if float(h.base_similarity) > float(prev.base_similarity):
            best_by_key[key] = h

    hits = list(best_by_key.values())
    after_n = len(hits)
    # region agent log
    debug_log(
        hypothesis_id="H7",
        location="core/retrieval.py:retrieve_from_corpus",
        message="dedup",
        data={"before": int(before_n), "after": int(after_n), "dropped": int(before_n - after_n)},
    )
    # endregion agent log

    # 只在排序阶段融合（按你的公式）
    rerank_with_weights(hits, enable_cog=cog_enabled, enable_decay=decay_enabled)

    top = hits[: int(top_k)]
    if top:
        log_telemetry(
            f"retrieve topK: mode={mode} decay={decay_enabled} alpha={depth_alpha} k={len(top)}"
        )
        for i, h in enumerate(top, 1):
            log_telemetry(
                " ".join(
                    [
                        f"#{i}",
                        f"final={h.final_score:.4f}",
                        f"sim={h.base_similarity:.3f}",
                        f"depth={h.depth_score:.3f}",
                        f"cog={h.cog_weight:.3f}",
                        f"age_days={(f'{h.age_days:.1f}' if h.age_days is not None else 'NA')}",
                        f"time={h.time_weight:.3f}",
                        f"src={h.source}",
                        f"source_id={h.source_id or 'NA'}",
                    ]
                )
            )
            # region agent log
            debug_log(
                hypothesis_id="H2",
                location="core/retrieval.py:retrieve_from_corpus",
                message="top_hit",
                data={
                    "rank": int(i),
                    "uid": h.uid,
                    "source": h.source,
                    "source_id": h.source_id,
                    "sim": float(h.base_similarity),
                    "depth_score": float(h.depth_score),
                    "cog_weight": float(h.cog_weight),
                    "age_days": h.age_days,
                    "time_weight": float(h.time_weight),
                    "final_score": float(h.final_score),
                },
            )
            # endregion agent log

    # region agent log
    debug_log(
        hypothesis_id="H3",
        location="core/retrieval.py:retrieve_from_corpus",
        message="exit",
        data={"returned": len(top), "uids": [h.uid for h in top]},
    )
    # endregion agent log

    return top


