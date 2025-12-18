import os
import json
import time
import random
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

CORPUS_PATH = "outputs/corpus.jsonl"
PROFILE_PATH = "outputs/user_profile.md"
PROFILE_STATE = "state/profile_state.json"

def _is_overload_error(e: Exception) -> bool:
    msg = str(e)
    return ("503" in msg) or ("overloaded" in msg.lower()) or ("UNAVAILABLE" in msg)

def _retry(callable_fn, retries=6, base_delay=2.0, max_delay=30.0):
    """
    只对 503/overloaded 做重试；其他错误直接抛出。
    """
    for i in range(retries):
        try:
            return callable_fn()
        except Exception as e:
            if not _is_overload_error(e):
                raise
            sleep_s = min(max_delay, base_delay * (2 ** i) + random.random())
            print(f"⚠️ [LLM] 503/overloaded，第 {i+1}/{retries} 次重试，{sleep_s:.1f}s 后再试…")
            time.sleep(sleep_s)
    raise RuntimeError("LLM 503/overloaded：多次重试仍失败")

def _load_state():
    if not os.path.exists(PROFILE_STATE):
        return {"last_line": 0}
    with open(PROFILE_STATE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_state(state):
    with open(PROFILE_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def _read_new_chunks(max_items=40):
    # 1. 如果文件不存在，直接返回空列表和0
    if not os.path.exists(CORPUS_PATH):
        return [], 0

    # 2. 读取旧的状态
    state = _load_state()
    last_line = int(state.get("last_line", 0))

    # 3. 读取文件所有行
    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    # 【关键修复】无论是否有新内容，先确定现在的总行数
    new_last_line = len(lines)

    # 4. 截取新增加的行
    new_lines = lines[last_line:]

    chunks = []
    for ln in new_lines:
        try:
            obj = json.loads(ln)
            chunks.append(obj)
        except:
            pass

    # 【关键修复】必须把 chunks 和 new_last_line 都返回出去
    return chunks, new_last_line

def update_user_profile():
    if not os.getenv("GOOGLE_API_KEY"):
        print("❌ 缺少 GOOGLE_API_KEY，无法更新画像")
        return False
        
    state = _load_state()
    chunks, new_last_line = _read_new_chunks()
    old_last_line = int(state.get("last_line", 0))
    raw_new_line_count = new_last_line - old_last_line

    if not chunks:
        print("💤 没有新增 chunk，跳过画像更新。")
        return False

    old_profile = ""
    if os.path.exists(PROFILE_PATH):
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            old_profile = f.read().strip()
            state = _load_state()
            state["last_line"] = new_last_line
            _save_state(state)


    # 压缩 evidence
    evidence = []
    for c in chunks:
        text = (c.get("text") or "").strip().replace("\n", " ")
        text = text[:500]
        evidence.append(
            f"- source={c.get('source')} weight={c.get('weight')} file={c.get('file_path')} created_at={c.get('created_at')}\n"
            f"  text={text}"
        )
    evidence_block = "\n".join(evidence)

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", temperature=0.2)

    system = (
        "你是“用户画像更新器”。你的任务：根据新增证据，更新 user_profile.md。\n"
        "规则：\n"
        "1) 输出必须是 Markdown（不是 JSON）。\n"
        "2) 尽量保持稳定，只做增量更新，不要因为少量证据推翻旧结论。\n"
        "3) 任何新增结论都要在“证据日志”里写明来源（source/file/created_at）。\n"
        "4) 文风：简洁、像备忘录。\n"
        "请使用固定结构：\n"
        "# 核心性格与偏好\n"
        "# 决策与学习风格\n"
        "# 交易风格与风险偏好\n"
        "# 常见盲点与纠偏提醒\n"
        "# 近期关注与假设（可变化）\n"
        "# 证据日志（自动追加）\n"
    )

    user = (
        f"【旧画像】\n{old_profile if old_profile else '(空)'}\n\n"
        f"【新增证据（本次新增 {raw_new_line_count} 行 corpus）】\n{evidence_block}\n\n"
        "请输出更新后的完整 user_profile.md 内容。"
    )
    prompt = f"{system}\n\n{user}"
    resp = _retry(lambda: llm.invoke(prompt))
    new_profile = (resp.content or "").strip()

    if not new_profile:
        print("❌ 模型输出为空，跳过写入。")
        return False

    with open(PROFILE_PATH, "w", encoding="utf-8") as f:
        f.write(new_profile + "\n")

    print(f"✅ user_profile.md 已更新（吸收 {len(chunks)} 条高权重证据）")
    return True

if __name__ == "__main__":
    update_user_profile()
