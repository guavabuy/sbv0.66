from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


_LOGIC_PHRASES_ZH = [
    "因为",
    "所以",
    "因此",
    "结论",
    "假设",
    "推导",
    "综上",
    "由此",
    "前提",
    "推论",
    "归纳",
    "演绎",
    "证明",
    "反例",
    "机制",
    "原因",
    "结果",
    "目的",
    "例如",
    "比如",
]

_LOGIC_PHRASES_EN = [
    "because",
    "therefore",
    "thus",
    "hence",
    "conclusion",
    "assume",
    "suppose",
    "derive",
    "proof",
    "premise",
    "infer",
    "in summary",
]


def score_depth(text: str, meta: Optional[Dict[str, Any]] = None) -> float:
    """
    轻量“深度评分器”，输出 0~1。

    设计目标：
    - 计算成本极低（纯字符串/正则）
    - 可解释（长度/逻辑词/线程结构）
    - 不依赖外部模型/向量库
    """
    t = (text or "").strip()
    if not t:
        return 0.0

    n = len(t)

    # 1) len_score：log 缩放，避免超长无限增益
    # 经验上 2k 字左右已足够“信息密度”表达，之后增益递减。
    len_score = _clamp(math.log1p(n) / math.log1p(2000.0))

    # 2) logic_score：逻辑词密度（中英混合）
    t_lower = t.lower()
    hits = 0
    for k in _LOGIC_PHRASES_ZH:
        hits += t.count(k)
    for k in _LOGIC_PHRASES_EN:
        hits += t_lower.count(k)

    # 以“每 ~250 字出现 1 个逻辑词”为基准；2x 密度以上直接封顶
    denom = max(50.0, float(n))
    density = hits * 250.0 / denom  # ~= hits / (n/250)
    logic_score = _clamp(density / 2.0)

    # 3) thread_score：thread/编号结构 bonus（从 meta 或文本推断）
    thread_score = 0.0
    if isinstance(meta, dict):
        thread_len = meta.get("thread_len") or meta.get("thread_size") or meta.get("thread_count")
        try:
            if thread_len is not None and int(thread_len) >= 3:
                thread_score = 1.0
        except Exception:
            pass

    if thread_score <= 0.0:
        # X 常见：1/8、2/8…；或内容里出现多行编号 1. 2. 3.
        frac_hits = len(re.findall(r"\b\d+\s*/\s*\d+\b", t))
        enum_hits = len(re.findall(r"(?m)^\s*\d+\s*[\.\)、\)]\s+", t))
        if frac_hits >= 2 or enum_hits >= 2:
            thread_score = 1.0
        elif frac_hits == 1 or enum_hits == 1:
            thread_score = 0.5

    # 组合：长度/逻辑占大头；thread 作为 bonus
    depth = 0.45 * len_score + 0.40 * logic_score + 0.15 * thread_score
    return float(_clamp(depth))


def compute_cog_weight(depth_score: float, alpha: float = 0.0) -> float:
    """
    认知权重：1 + alpha*(depth_score-0.5)

    - alpha=0 时恒为 1（feature flag 关闭，确保旧行为完全不变）
    """
    ds = _clamp(float(depth_score))
    a = float(alpha or 0.0)
    w = 1.0 + a * (ds - 0.5)
    # 轻微保护：避免被配置成负数/0
    return float(max(0.1, w))


def score_time(
    ts: Optional[Any],
    *,
    now: Optional[datetime] = None,
    window_days: float = 15.0,
    half_life_days: float = 3.0,
    floor: float = 0.05,
) -> float:
    """
    时间权重（遗忘曲线，0~1），两段式窗口策略：

    - 窗口内（<= window_days）：exp(-ln(2)*age_days/half_life_days)
    - 窗口外（> window_days）：floor（仍可召回，但明显更弱）

    约定：
    - ts 缺失/解析失败：返回 1（避免无时间数据被意外降权，保持“最小侵入”）
    - 未来时间：按 age_days=0 处理
    """
    if ts is None:
        return 1.0

    dt: Optional[datetime] = None
    if isinstance(ts, datetime):
        dt = ts
    elif isinstance(ts, str):
        s = ts.strip()
        if not s:
            return 1.0
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return 1.0
    else:
        return 1.0

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    now_dt = now if now is not None else datetime.now(timezone.utc)
    if now_dt.tzinfo is None:
        now_dt = now_dt.replace(tzinfo=timezone.utc)

    age_days = (now_dt - dt).total_seconds() / 86400.0
    if age_days < 0:
        age_days = 0.0

    w_days = float(window_days or 0.0)
    hl = float(half_life_days or 0.0)
    fl = float(floor if floor is not None else 0.0)

    # window_days <= 0：退化为全局 floor（但仍 clamp 到 0~1）
    if w_days <= 0:
        return float(_clamp(fl))

    # half_life_days 非法：退化为窗口内常量 1，窗口外 floor
    if hl <= 0:
        return 1.0 if age_days <= w_days else float(_clamp(fl))

    if age_days <= w_days:
        # exp(-ln2 * age/hl) == 2^(-age/hl)
        wt = math.exp(-math.log(2.0) * age_days / hl)
        return float(_clamp(wt))

    return float(_clamp(fl))


