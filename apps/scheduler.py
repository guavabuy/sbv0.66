from __future__ import annotations

import os
import sys
import time
import traceback
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import schedule

from connectors.notion_sync import fetch_updates as notion_fetch_updates
from connectors.x_sync import fetch_updates as x_fetch_updates
from core.processor import run_incremental_ingest, update_user_profile_incremental


_LOG_DIR = _ROOT / "logs"
_LOG_PATH = _LOG_DIR / "scheduler.log"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _append_log(line: str) -> None:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    with _LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")


def _run_step(name: str, fn: Callable[[], object]) -> bool:
    """
    单步执行：异常捕获 + 记录，保证 scheduler 不崩。
    """
    try:
        _append_log(f"[{_now()}] step.start {name}")
        fn()
        _append_log(f"[{_now()}] step.ok {name}")
        return True
    except Exception:
        _append_log(f"[{_now()}] step.fail {name}\n{traceback.format_exc()}")
        return False


def _get_x_usernames() -> list[str]:
    raw = (os.getenv("X_USERNAMES") or "").strip()
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        u = (part or "").strip().lstrip("@")
        if u and u not in out:
            out.append(u)
    return out


def run_daily_job() -> None:
    """
    每日任务：按顺序执行
    1) Notion sync
    2) X sync（按 X_USERNAMES）
    3) ingest（增量）
    4) profile_update（增量）

    关键要求：静默运行
    - 同步/处理过程中产生的 print 全部重定向到 logs/scheduler.log
    - 任何异常不抛出到外层（防止 scheduler 退出）
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    def _do_job() -> None:
        print(f"\n[{_now()}] job.start daily")

        _run_step("notion_sync.fetch_updates", lambda: notion_fetch_updates())

        usernames = _get_x_usernames()
        if usernames:
            for u in usernames:
                _run_step(f"x_sync.fetch_updates @{u}", lambda u=u: x_fetch_updates(u))
        else:
            print(f"[{_now()}] step.skip x_sync.fetch_updates (X_USERNAMES empty)")

        _run_step("ingest.ingest(incremental)", lambda: run_incremental_ingest(full=False))
        _run_step("profile_update.update_user_profile", lambda: update_user_profile_incremental())

        print(f"[{_now()}] job.end daily")

    # 默认静默：把同步过程的 print 都重定向到 logs/scheduler.log
    # 测试模式（前台观察）可用 SB_SCHEDULER_FOREGROUND=1 关闭重定向，让终端直接滚动输出
    foreground = (os.getenv("SB_SCHEDULER_FOREGROUND") or "").strip().lower() in ("1", "true", "yes", "y", "on")
    if foreground:
        _do_job()
        return

    with _LOG_PATH.open("a", encoding="utf-8") as f, redirect_stdout(f), redirect_stderr(f):
        _do_job()


def _everyday_at(hhmm: str = "12:00") -> None:
    schedule.clear()
    schedule.every().day.at(hhmm).do(run_daily_job)


def main() -> None:
    """
    后台常驻循环（需要你单独启动一个进程）。

    - 默认每天 12:00 执行 run_daily_job
    - 全程不向 stdout/stderr 打印（只写 logs/scheduler.log）
    """
    # 默认生产：12:00
    # 测试：若未显式设置 SB_SCHEDULE_AT，则自动用“当前时间 + 1 分钟”，避免等到明天中午
    sb_schedule_at = (os.getenv("SB_SCHEDULE_AT") or "").strip()
    if sb_schedule_at:
        hhmm = sb_schedule_at
        test_mode = False
    else:
        hhmm = (datetime.now().replace(second=0, microsecond=0) + timedelta(minutes=1)).strftime("%H:%M")
        test_mode = True
    tick = float(os.getenv("SB_SCHEDULER_TICK_SECONDS", "1.0") or 1.0)

    _everyday_at(hhmm)
    _append_log(f"[{_now()}] scheduler.start at={hhmm} tick={tick} test_mode={test_mode}")

    if test_mode:
        # 前台观察：默认打开 foreground，让你能在终端看到同步/ingest 输出滚动
        os.environ.setdefault("SB_SCHEDULER_FOREGROUND", "1")
        print(f"[{_now()}] scheduler.test_mode enabled, will run at {hhmm} (in ~1 minute)")
        print(f"[{_now()}] logs: {_LOG_PATH}")

    # 可选：启动时立即跑一次（便于验证）
    if (os.getenv("SB_RUN_ON_START") or "").strip() in ("1", "true", "yes", "y", "on"):
        try:
            run_daily_job()
        except Exception:
            _append_log(f"[{_now()}] job.fail_on_start\n{traceback.format_exc()}")

    while True:
        try:
            schedule.run_pending()
        except Exception:
            # 不让 scheduler loop 退出
            _append_log(f"[{_now()}] scheduler.loop_error\n{traceback.format_exc()}")
        time.sleep(max(0.2, tick))


if __name__ == "__main__":
    main()


