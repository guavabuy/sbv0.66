import os
import json
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

CORPUS_PATH = "outputs/corpus.jsonl"
PROFILE_PATH = "outputs/user_profile.md"
PROFILE_STATE = "state/profile_state.json"

def _load_state():
    if not os.path.exists(PROFILE_STATE):
        return {"last_line": 0}
    with open(PROFILE_STATE, "r", encoding="utf-8") as f:
        return json.load(f)

def _save_state(state):
    with open(PROFILE_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def _read_new_chunks(max_items=40):
    if not os.path.exists(CORPUS_PATH):
        return [], 0

    state = _load_state()
    last_line = int(state.get("last_line", 0))

    with open(CORPUS_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    new_lines = lines[last_line:]
    state["last_line"] = len(lines)
    _save_state(state)

    chunks = []
    for ln in new_lines:
        try:
            obj = json.loads(ln)
            chunks.append(obj)
        except:
            pass

    # 按权重排序，取最有价值的部分（省 token）
    chunks.sort(key=lambda x: float(x.get("weight", 0.0)), reverse=True)
    return chunks[:max_items], len(new_lines)

def update_user_profile():
    if not os.getenv("GOOGLE_API_KEY"):
        print("❌ 缺少 GOOGLE_API_KEY，无法更新画像")
        return False

    chunks, raw_new_line_count = _read_new_chunks()
    if not chunks:
        print("💤 没有新增 chunk，跳过画像更新。")
        return False

    old_profile = ""
    if os.path.exists(PROFILE_PATH):
        with open(PROFILE_PATH, "r", encoding="utf-8") as f:
            old_profile = f.read().strip()

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

    resp = llm.invoke([("system", system), ("human", user)])
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
