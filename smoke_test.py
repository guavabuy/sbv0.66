#!/usr/bin/env python3
import os
import sys
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent

REQUIRED_PATHS = [
    "connectors/notion_sync.py",
    "connectors/x_sync.py",
    "ingest.py",
    "profile_update.py",
    "memory_retriever.py",
    "main.py",
    "auto_run.py",
    "requirements.txt",
    "data_sources/notion",
    "data_sources/x",
    "outputs",
    "state",
]

STATE_FILES = [
    "state/notion_state.json",
    "state/sync_state.json",
    "state/profile_state.json",
]

OUTPUT_FILES = [
    "outputs/corpus.jsonl",
    "outputs/user_profile.md",
    "outputs/brain_memory.md",
]

def run(cmd, env=None, allow_fail=False):
    print(f"\n$ {' '.join(cmd)}")
    p = subprocess.run(
        cmd,
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
    )
    if p.stdout:
        print(p.stdout)
    if p.stderr:
        print(p.stderr, file=sys.stderr)

    if p.returncode != 0 and not allow_fail:
        raise RuntimeError(f"Command failed ({p.returncode}): {' '.join(cmd)}")
    return p.returncode

def ensure_dirs():
    (ROOT / "data_sources" / "notion").mkdir(parents=True, exist_ok=True)
    (ROOT / "data_sources" / "x").mkdir(parents=True, exist_ok=True)
    (ROOT / "outputs").mkdir(parents=True, exist_ok=True)
    (ROOT / "state").mkdir(parents=True, exist_ok=True)

def ensure_state_files():
    # 给 state 文件一个最小默认结构（避免代码读不到直接炸）
    defaults = {
        "state/notion_state.json": {},
        "state/sync_state.json": {},
        "state/profile_state.json": {"last_line": 0},
    }
    for rel, content in defaults.items():
        p = ROOT / rel
        if not p.exists():
            p.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")

def sanity_check_tree():
    missing = []
    for rel in REQUIRED_PATHS:
        if not (ROOT / rel).exists():
            missing.append(rel)
    if missing:
        print("\n[FAIL] Missing required paths:")
        for m in missing:
            print(" -", m)
        print("\n请先确保这些文件/目录存在（你的截图里是存在的，但以实际仓库为准）。")
        sys.exit(2)

def file_nonempty(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0

def main():
    print("=== SBV Smoke Test ===")
    print("Python:", sys.version)
    print("Project root:", ROOT)

    sanity_check_tree()
    ensure_dirs()
    ensure_state_files()

    # 1) 先做 import 级别健康检查（最常见：依赖/语法/版本）
    print("\n=== 1) Import checks ===")
    modules = [
        "connectors.notion_sync",
        "connectors.x_sync",
        "ingest",
        "profile_update",
        "memory_retriever",
        "auto_run",
        "main",
    ]
    for m in modules:
        run([sys.executable, "-c", f"import {m}; print('OK import {m}')"])

    # 2) 尝试跑一次“同步层”
    # 说明：如果你没配 API key，这一步可能会失败 —— 我们允许失败，但会把错误打印出来
    print("\n=== 2) Sync layer (allowed to fail if no API keys) ===")
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    run([sys.executable, "connectors/notion_sync.py"], env=env, allow_fail=True)
    run([sys.executable, "connectors/x_sync.py"], env=env, allow_fail=True)

    # 3) 跑 ingest（把 data_sources 增量分块写入 corpus.jsonl）
    print("\n=== 3) Ingest ===")
    run([sys.executable, "ingest.py"], env=env)

    # 4) 跑画像更新（基于 corpus.jsonl 更新 user_profile + brain_memory）
    print("\n=== 4) Profile update ===")
    run([sys.executable, "profile_update.py"], env=env)

    # 5) 检查关键输出是否生成
    print("\n=== 5) Output checks ===")
    ok = True
    for rel in OUTPUT_FILES:
        p = ROOT / rel
        status = "OK" if file_nonempty(p) else "MISSING/EMPTY"
        print(f"{status}: {rel}")
        if status != "OK":
            ok = False

    if not ok:
        print("\n[FAIL] 关键产物缺失或为空。通常是 ingest / profile_update 中途报错或没有可处理的数据。")
        sys.exit(3)

    # 6) 非交互式 sanity：能否 import + 启动 main（不强行对话，避免卡住）
    print("\n=== 6) Main entry import OK (not launching interactive chat) ===")
    print("[PASS] Smoke test completed.")
    print("\n如果你要验证检索+对话：手动运行 `python main.py` 输入一句话即可。")

if __name__ == "__main__":
    main()
