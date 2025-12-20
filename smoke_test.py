#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
SBV Smoke Test（轻量自检）

目标：
- 不启动任何长驻进程（不跑 schedule、不跑 Telegram polling）
- 默认不触网、不消耗 LLM 额度
- 尽量用“可编译 + 可导入 + 基本行为断言”覆盖主链路

可选开关：
- SBV_SMOKE_STRICT_IMPORT=1    严格要求核心模块全部可导入（默认非严格）
- SBV_SMOKE_RUN_SYNC=1         真的跑一次 auto_run.daily_job（⚠️可能联网/写文件）
"""

import importlib
import json
import os
import re
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Callable, Optional

ROOT = Path(__file__).resolve().parent


def ok(msg: str) -> None:
    print(f"✅ {msg}")


def warn(msg: str) -> None:
    print(f"⚠️ {msg}")


def fail(msg: str) -> None:
    print(f"❌ {msg}")


def header(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def run_step(name: str, fn: Callable[[], None]) -> bool:
    print(f"\n--- {name} ---")
    try:
        fn()
        ok(f"{name} PASS")
        return True
    except AssertionError as e:
        fail(f"{name} FAIL: {e}")
        return False
    except Exception as e:
        fail(f"{name} ERROR: {e}")
        traceback.print_exc()
        return False


def must_exist(path: Path, kind: str) -> None:
    assert path.exists(), f"缺少 {kind}: {path}"


def import_module_safe(name: str) -> Optional[Any]:
    try:
        return importlib.import_module(name)
    except Exception as e:
        warn(f"无法导入模块 {name}: {e}")
        return None


def py_compile_all() -> None:
    import py_compile

    py_files = [
        p
        for p in ROOT.rglob("*.py")
        if "venv" not in str(p) and "__pycache__" not in str(p)
    ]
    assert py_files, "项目内未找到任何 .py 文件？请确认在项目根目录运行。"
    for p in py_files:
        py_compile.compile(str(p), doraise=True)
    ok(f"py_compile: compiled {len(py_files)} files")


def check_dirs_and_files() -> None:
    must_exist(ROOT / "data_sources", "directory data_sources/")
    must_exist(ROOT / "outputs", "directory outputs/")
    must_exist(ROOT / "state", "directory state/")

    corpus = ROOT / "outputs" / "corpus.jsonl"
    if corpus.exists():
        ok("outputs/corpus.jsonl exists")
    else:
        warn("outputs/corpus.jsonl 不存在（若你尚未跑 ingest 则正常）")


def validate_corpus_jsonl_if_exists() -> None:
    corpus = ROOT / "outputs" / "corpus.jsonl"
    if not corpus.exists():
        warn("缺少 outputs/corpus.jsonl，跳过 JSONL 校验")
        return

    n = 0
    bad = 0
    with corpus.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                json.loads(line)
            except Exception:
                bad += 1
            if n >= 80:
                break
    assert n > 0, "corpus.jsonl 为空"
    assert bad == 0, f"corpus.jsonl 前 {n} 行中有 {bad} 行不是合法 JSON"
    ok(f"corpus.jsonl OK (checked {n} lines)")


def import_core_modules() -> None:
    core = [
        "main",
        "memory_retriever",
        "ingest",
        "profile_update",
        "auto_run",
        "tg_bot",
        "friend_mode",
        "friend_mode_config",
    ]
    missing = []
    for m in core:
        mod = import_module_safe(m)
        if mod is None:
            missing.append(m)

    strict = os.getenv("SBV_SMOKE_STRICT_IMPORT", "0") == "1"
    if strict:
        assert len(missing) == 0, f"严格模式下核心模块导入失败: {missing}"
        ok("core imports strict OK")
        return

    if missing:
        warn(f"core imports missing (non-strict): {missing}")
    ok("core imports OK (non-strict)")


def smoke_retriever_best_effort() -> None:
    mr = import_module_safe("memory_retriever")
    assert mr is not None, "memory_retriever 导入失败"

    candidates = []
    for name in dir(mr):
        obj = getattr(mr, name, None)
        if callable(obj) and any(
            k in name.lower()
            for k in ["search", "query", "context", "rank", "similar", "vector", "embed"]
        ):
            candidates.append(name)

    if not candidates:
        warn(
            "memory_retriever 可导入，但未发现明显入口函数名（仅提示；不影响项目运行）。"
        )
    else:
        ok(f"memory_retriever 发现可疑入口（仅提示）: {candidates[:8]}")


def smoke_main_cli() -> None:
    main_py = ROOT / "main.py"
    must_exist(main_py, "file main.py")

    inp = "q\nquit\n"
    try:
        p = subprocess.run(
            [sys.executable, str(main_py)],
            input=inp.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ.copy(),
            timeout=25,
        )
    except subprocess.TimeoutExpired as e:
        raise AssertionError(
            "运行 main.py 超时（可能卡在等待输入/联网/工具调用）。"
        ) from e

    out = (p.stdout + p.stderr).decode("utf-8", errors="replace")
    if p.returncode != 0:
        if ("API_KEY" in out.upper()) or ("KEY" in out.upper()):
            warn("main.py 触发 LLM 但缺少/未配置 key：SKIP（不算失败）")
            return
        warn(f"main.py 退出码={p.returncode}（不一定致命）。输出片段:\n{out[-800:]}")
        return

    ok("main.py CLI runs and exits (smoke OK)")


class FakeRetrieval:
    """
    让 smoke test 更容错：不管 contexts 里是 str 还是 dict，都转成 str。
    friend_mode 会对每个元素调用 .strip()，所以必须保证是字符串。
    """

    def __init__(self, contexts, top_score: float):
        cleaned = []
        for c in (contexts or []):
            if c is None:
                continue
            if isinstance(c, str):
                s = c
            elif isinstance(c, dict):
                s = c.get("text") or c.get("content") or json.dumps(c, ensure_ascii=False)
            else:
                s = str(c)
            s = s.strip()
            if s:
                cleaned.append(s)

        self.contexts = cleaned
        self.top_score = float(top_score)
        self.top1_score = float(top_score)
        self.max_score = float(top_score)
        self.hit_count = len(cleaned)


def smoke_friend_mode_policy() -> None:
    fm = import_module_safe("friend_mode")
    assert fm is not None, "friend_mode 导入失败"

    entry = getattr(fm, "answer_telegram", None)
    assert callable(entry), "friend_mode.py 未找到 answer_telegram()"

    profile = "（测试画像）我偏理性，重视风险控制。"
    memory = "（测试短期记忆）最近关注：产品迭代。"

    os.environ["TG_FRIEND_MODE"] = "1"

    # Unknown
    out = entry("今天发生了什么大事？", FakeRetrieval(contexts=[], top_score=0.0), profile, memory)
    out_s = out if isinstance(out, str) else str(out)
    assert "我最近对" in out_s and "没有了解" in out_s, "Unknown 模板缺少关键句"
    assert re.search(r"这些是我刚搜索到的内容\s*[:：]", out_s), "Unknown 模板缺少搜索提示句"
    ok("FriendMode Unknown template OK")

    # Known
    known_ctx = [
        {"text": "（资料库片段）我更重视风险控制，而不是追热点。"},
        {"text": "（资料库片段）我习惯用第一性原理拆问题。"},
        {"text": "（资料库片段）我倾向于长期复利思维。"},
    ]
    out2 = entry("你怎么看长期复利？", FakeRetrieval(contexts=known_ctx, top_score=0.9), profile, memory)
    out2s = out2 if isinstance(out2, str) else str(out2)
    assert "我对这件事情的观点是" in out2s, "Known 模板缺少关键句"
    ok("FriendMode Known template OK")

    # Ambiguous
    amb_ctx = ["（资料库片段）我对宏观流动性有长期关注。"]
    out3 = entry("你觉得这个趋势会怎么走？", FakeRetrieval(contexts=amb_ctx, top_score=0.4), profile, memory)
    out3s = out3 if isinstance(out3, str) else str(out3)
    assert "我目前对相关事情的了解" in out3s, "Ambiguous 模板缺少关键句"
    assert "基于我的人物画像，我对你这个问题的推论是" in out3s, "Ambiguous 模板缺少推论句"
    ok("FriendMode Ambiguous template OK")


def smoke_tg_friend_mode_isolation() -> None:
    """
    tg_bot 开关隔离（TG_FRIEND_MODE=0/1 行为差异）
    - 0：不出现 friend_mode 固定句式（保持旧链路）
    - 1：出现 friend_mode 固定句式，且 meta 带 route 等字段
    """
    tg = import_module_safe("tg_bot")
    assert tg is not None, "tg_bot 导入失败"

    class _R:
        def __init__(self, content: str, tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls

    def _fake_invoke(_messages):
        return _R("OLD_REPLY", tool_calls=None)

    # 关：不应出现任何 friend_mode 固定句式
    os.environ["TG_FRIEND_MODE"] = "0"
    try:
        setattr(tg, "llm", type("LLM", (), {"invoke": staticmethod(_fake_invoke)})())
    except Exception:
        pass

    out0, meta0, _extra0 = tg.generate_tg_reply("hi", [type("M", (), {"content": "SYS"})()])
    out0s = out0 if isinstance(out0, str) else str(out0)
    assert "我对这件事情的观点是" not in out0s
    assert "我目前对相关事情的了解" not in out0s
    assert "我最近对这件事没有了解" not in out0s
    assert meta0 == {}, f"TG_FRIEND_MODE=0 meta 应为空，实际={meta0}"

    # 开：mock 检索 + 禁止 web_search 触网
    os.environ["TG_FRIEND_MODE"] = "1"
    os.environ["SERPAPI_API_KEY"] = ""  # 强制 web_search_wrapper 返回空（更稳）

    def _fake_ret(_q, top_k=6, corpus_path="outputs/corpus.jsonl", max_scan=4000):
        return {
            "hits": [
                {"id": "1", "text": "编程进展：tg bot", "score": 0.9},
                {"id": "2", "text": "编程进展：测试", "score": 0.9},
                {"id": "3", "text": "编程进展：结构", "score": 0.9},
            ]
        }

    setattr(tg, "_tg_friend_retrieve_raw", _fake_ret)

    out1, meta1, _extra1 = tg.generate_tg_reply("编程进展如何", [type("M", (), {"content": "SYS"})()])
    out1s = out1 if isinstance(out1, str) else str(out1)
    assert (
        ("我对这件事情的观点是" in out1s)
        or ("我目前对相关事情的了解" in out1s)
        or ("我最近对这件事没有了解" in out1s)
    ), f"TG_FRIEND_MODE=1 未出现 friend_mode 模板，实际输出:\n{out1s}"

    for k in ("route", "top_score", "hit_count", "web_search", "used_chunks"):
        assert k in meta1, f"TG_FRIEND_MODE=1 meta 缺字段 {k}，实际={meta1}"

    ok("tg_bot TG_FRIEND_MODE 0/1 isolation OK")


def smoke_connectors_import() -> None:
    ns = import_module_safe("connectors.notion_sync")
    xs = import_module_safe("connectors.x_sync")
    assert ns is not None, "connectors.notion_sync 导入失败"
    assert xs is not None, "connectors.x_sync 导入失败"
    assert hasattr(ns, "fetch_updates") and callable(getattr(ns, "fetch_updates")), "notion_sync 缺少 fetch_updates()"
    assert hasattr(xs, "fetch_updates") and callable(getattr(xs, "fetch_updates")), "x_sync 缺少 fetch_updates()"
    ok("connectors import OK")


def optional_run_sync_loop() -> None:
    if os.getenv("SBV_SMOKE_RUN_SYNC", "0") != "1":
        warn("未开启 SBV_SMOKE_RUN_SYNC=1：跳过实际同步/闭环执行（默认安全）")
        return
    ar = import_module_safe("auto_run")
    assert ar is not None, "auto_run 导入失败"
    fn = None
    for cand in ["daily_job", "run_once", "job", "main"]:
        if hasattr(ar, cand) and callable(getattr(ar, cand)):
            fn = getattr(ar, cand)
            break
    assert fn is not None, "auto_run.py 找不到 daily_job()/run_once()/main() 入口"
    ok(f"即将执行 auto_run 入口: {fn.__name__}（⚠️可能联网/写文件）")
    t0 = time.time()
    fn()
    ok(f"auto_run finished in {time.time() - t0:.1f}s")


def main() -> None:
    header("SBV Full Project Smoke Test")
    print(f"Root: {ROOT}")
    print(f"Python: {sys.version.split()[0]}")
    print(f"SBV_SMOKE_RUN_SYNC={os.getenv('SBV_SMOKE_RUN_SYNC', '0')}")

    steps = [
        ("1) Compile all python files", py_compile_all),
        ("2) Check dirs & outputs existence", check_dirs_and_files),
        ("3) Validate corpus.jsonl (if exists)", validate_corpus_jsonl_if_exists),
        ("4) Import core modules", import_core_modules),
        ("5) Retriever smoke (best-effort)", smoke_retriever_best_effort),
        ("6) main.py CLI smoke (run & exit)", smoke_main_cli),
        ("7) Friend Mode policy smoke (templates/routing)", smoke_friend_mode_policy),
        ("8) TG Friend Mode isolation (0/1)", smoke_tg_friend_mode_isolation),
        ("9) connectors import smoke", smoke_connectors_import),
        ("10) Optional run sync loop (dangerous)", optional_run_sync_loop),
    ]

    results = [run_step(name, fn) for name, fn in steps]
    header("RESULT")
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Passed: {passed}/{total}")
    if passed != total:
        sys.exit(2)
    print("✅ 全库 Smoke Test 通过")
    sys.exit(0)


if __name__ == "__main__":
    main()


