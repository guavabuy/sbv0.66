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
=======
# smoke_test.py
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Tuple

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

load_dotenv()

SMOKE_LLM = os.getenv("SMOKE_LLM", "1").strip() not in ("0", "false", "False")


def hr(title: str):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def ok(msg: str):
    print(f"✅ {msg}")


def warn(msg: str):
    print(f"⚠️ {msg}")


def fail(msg: str):
    print(f"❌ {msg}")


def safe_get_file_stat(path: str) -> Tuple[bool, int, float]:
    if not os.path.exists(path):
        return False, 0, 0.0
    st = os.stat(path)
    return True, st.st_size, st.st_mtime


def run_llm_once(llm, tools_by_name: Dict[str, Any], system_prompt: str, user_text: str) -> str:
    """最小一轮：支持 tool_calls"""
    messages: List[Any] = [SystemMessage(content=system_prompt), HumanMessage(content=user_text)]
    resp = llm.invoke(messages)

    if getattr(resp, "tool_calls", None):
        tool_outputs: List[Any] = []
        for tc in resp.tool_calls:
            name = tc.get("name")
            args = tc.get("args")
            tool_obj = tools_by_name.get(name)

            if tool_obj is None:
                tool_res = "未知工具"
            else:
                # langchain @tool 一般支持 .invoke(dict)
                if hasattr(tool_obj, "invoke"):
                    tool_res = tool_obj.invoke(args)
                else:
                    # 极端兜底
                    if isinstance(args, dict):
                        tool_res = tool_obj(**args)
                    else:
                        tool_res = tool_obj(args)

            tool_outputs.append(ToolMessage(tool_call_id=tc["id"], content=str(tool_res)))

        final_resp = llm.invoke(messages + [resp] + tool_outputs)
        return str(getattr(final_resp, "content", ""))
    return str(getattr(resp, "content", ""))


def main():
    hr("0) 基础环境检查")
    required = ["GOOGLE_API_KEY", "SERPAPI_API_KEY"]
    for k in required:
        if not os.getenv(k):
            fail(f".env 缺少 {k}")
            sys.exit(1)
    ok("关键环境变量存在（GOOGLE_API_KEY / SERPAPI_API_KEY）")

    # -------------------- main.py --------------------
    hr("1) main.py 导入与基础链路检查")
    try:
        import main as sb_main
    except Exception as e:
        fail(f"导入 main.py 失败: {e}")
        traceback.print_exc()
        sys.exit(1)

    # health check（如果存在）
    try:
        if hasattr(sb_main, "system_health_check"):
            sb_main.system_health_check()
            ok("main.system_health_check() 通过")
        else:
            warn("main.py 没有 system_health_check()，跳过")
    except Exception as e:
        fail(f"main.system_health_check() 失败: {e}")
        traceback.print_exc()
        sys.exit(1)

    # 关键对象存在性
    for attr in ["llm", "search_tool", "read_url_tool"]:
        if not hasattr(sb_main, attr):
            fail(f"main.py 缺少 {attr}")
            sys.exit(1)
    ok("main: llm / search_tool / read_url_tool 均存在")

    # 记忆写入冒烟测试：写入 -> 校验文件增长 -> 立刻回滚截断（不污染）
    brain_path = getattr(sb_main, "LOG_FILE", "outputs/brain_memory.md")
    existed, size0, mtime0 = safe_get_file_stat(brain_path)
    try:
        if hasattr(sb_main, "save_to_brain"):
            sb_main.save_to_brain("SMOKE_TEST", "ping")
            existed2, size1, mtime1 = safe_get_file_stat(brain_path)
            if not existed2 or size1 <= size0:
                fail("main.save_to_brain() 未能写入/文件未增长")
                sys.exit(1)
            # 回滚：截断到原大小
            with open(brain_path, "r+b") as f:
                f.truncate(size0)
            ok("main.save_to_brain() 写入成功，并已回滚（不污染 brain_memory.md）")
        else:
            warn("main.py 没有 save_to_brain()，跳过记忆写入测试")
    except Exception as e:
        fail(f"记忆写入测试失败: {e}")
        traceback.print_exc()
        sys.exit(1)

    # main 的 LLM + 工具链路测试
    if SMOKE_LLM:
        hr("2) main.py LLM 一轮对话（含工具能力）")
        try:
            # prompt：优先用 get_dynamic_system_prompt，否则给个兜底
            if hasattr(sb_main, "get_dynamic_system_prompt"):
                prompt = sb_main.get_dynamic_system_prompt()
            else:
                prompt = "你是用户的 Second Brain，用一句话回复 OK。"

            tools_by_name = {
                "search_tool": sb_main.search_tool,
                "read_url_tool": sb_main.read_url_tool,
            }
            reply = run_llm_once(sb_main.llm, tools_by_name, prompt, "回复一个 OK（不要解释）")
            if not reply.strip():
                fail("main LLM 返回为空")
                sys.exit(1)
            ok(f"main LLM 返回正常（长度={len(reply)})")
        except Exception as e:
            fail(f"main LLM 链路失败: {e}")
            traceback.print_exc()
            sys.exit(1)
    else:
        warn("SMOKE_LLM=0：跳过 main LLM 调用（不消耗额度）")

    # -------------------- tg_bot.py --------------------
    hr("3) tg_bot.py 导入与“不会写入记忆”检查")
    try:
        import tg_bot as tg
    except Exception as e:
        fail(f"导入 tg_bot.py 失败: {e}")
        traceback.print_exc()
        sys.exit(1)

    # tg bot 不能污染 brain_memory
    existedA, sizeA, mtimeA = safe_get_file_stat(brain_path)

    # build system prompt（如果存在）
    try:
        if hasattr(tg, "build_system_prompt"):
            tg_prompt = tg.build_system_prompt()
            ok("tg_bot.build_system_prompt() 正常")
        elif hasattr(tg, "get_dynamic_system_prompt"):
            tg_prompt = tg.get_dynamic_system_prompt()
            ok("tg_bot.get_dynamic_system_prompt() 正常")
        else:
            tg_prompt = "你是 Guest 模式 Second Brain。"
            warn("tg_bot 无 prompt 构建函数，使用兜底 prompt")
    except Exception as e:
        fail(f"tg_bot prompt 构建失败: {e}")
        traceback.print_exc()
        sys.exit(1)

    # tg 的 LLM 一轮（不启动 Telegram polling）
    if SMOKE_LLM:
        hr("4) tg_bot.py LLM 一轮对话（不启动 Telegram，仅测核心推理链路）")
        try:
            if not hasattr(tg, "llm"):
                fail("tg_bot.py 缺少 llm")
                sys.exit(1)

            tools_by_name = {}
            if hasattr(tg, "search_tool") and hasattr(tg, "read_url_tool"):
                tools_by_name = {"search_tool": tg.search_tool, "read_url_tool": tg.read_url_tool}

            reply = run_llm_once(tg.llm, tools_by_name, tg_prompt, "回复一个 OK（不要解释）")
            if not reply.strip():
                fail("tg_bot LLM 返回为空")
                sys.exit(1)
            ok(f"tg_bot LLM 返回正常（长度={len(reply)})")
        except Exception as e:
            fail(f"tg_bot LLM 链路失败: {e}")
            traceback.print_exc()
            sys.exit(1)
    else:
        warn("SMOKE_LLM=0：跳过 tg_bot LLM 调用（不消耗额度）")

    # 再次确认 brain_memory 没变（tg 不应写入）
    time.sleep(0.2)
    existedB, sizeB, mtimeB = safe_get_file_stat(brain_path)
    if existedA and existedB and (sizeB != sizeA or mtimeB != mtimeA):
        fail("检测到 tg_bot 运行后 brain_memory.md 发生变化（这不应该发生）")
        sys.exit(1)
    ok("tg_bot 不污染 brain_memory.md ✅")

    hr("✅ Smoke Test 全部通过")
    print("你现在可以放心：main / tg_bot 的关键链路都还正常。")

>>>>>>> 1e022e7 (新增:tg端交互)

if __name__ == "__main__":
    main()
