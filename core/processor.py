from __future__ import annotations

from typing import Any, Dict


def run_incremental_ingest(*, full: bool = False) -> Dict[str, Any]:
    """
    增量处理（Card 6 结构下默认写入 data/corpus.jsonl）。

    这里做“core 层统一入口”的薄封装，便于 apps/scheduler 调用；
    具体实现复用现有 ingest.py（避免重复逻辑）。
    """
    from scripts.ingest import ingest

    return ingest(full=bool(full))


def update_user_profile_incremental() -> bool:
    """
    画像增量更新（读取 data/corpus.jsonl 新增行，写入 data/user_profile.md）。
    复用 profile_update.py 的实现。
    """
    from scripts.profile_update import update_user_profile

    return bool(update_user_profile())


