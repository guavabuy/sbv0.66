import os
import json
import requests
import datetime
from pathlib import Path
from dotenv import load_dotenv

# 项目根目录（connectors/ 的上一级）
_BASE = Path(__file__).resolve().parents[1]
try:
    load_dotenv(dotenv_path=_BASE / ".env")
except Exception:
    # 在某些环境（权限/无 .env）下允许导入；真实运行时可依赖环境变量
    pass
NOTION_KEY = os.getenv("NOTION_API_KEY")
DATABASE_ID = os.getenv("NOTION_DATABASE_ID")

# ✅ 避免和 ingest 的 sync_state.json 冲突
STATE_FILE = str(_BASE / "state" / "notion_state.json")

headers = {
    "Authorization": f"Bearer {NOTION_KEY}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

def _parse_iso(ts: str) -> datetime.datetime:
    # Notion 经常是 ...Z
    if ts.endswith("Z"):
        ts = ts.replace("Z", "+00:00")
    return datetime.datetime.fromisoformat(ts)

def _safe_filename(s: str) -> str:
    return "".join(c if c.isalnum() or c in "._-+" else "_" for c in s)

def fetch_page_content(page_id: str) -> str:
    block_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    try:
        response = requests.get(block_url, headers=headers, timeout=20)
        if response.status_code != 200:
            return "[API 限制无法读取内容]"

        blocks = response.json().get("results", [])
        content_text = ""

        for block in blocks:
            b_type = block.get("type")
            if b_type == "paragraph":
                rich_text = block.get("paragraph", {}).get("rich_text", [])
                for rt in rich_text:
                    content_text += rt.get("plain_text", "")
                content_text += "\n"
            elif b_type and "heading" in b_type:
                rich_text = block.get(b_type, {}).get("rich_text", [])
                heading = "".join(rt.get("plain_text", "") for rt in rich_text)
                if heading.strip():
                    content_text += f"\n【{heading.strip()}】\n"

        return content_text.strip() if content_text.strip() else "[该笔记没有文本内容]"
    except Exception as e:
        return f"[读取错误: {e}]"

def fetch_updates() -> int:
    print(">>> 🔄 开始智能同步 Notion...")
    if not NOTION_KEY or not DATABASE_ID:
        print("⚠️ [Notion] 缺少 NOTION_API_KEY 或 NOTION_DATABASE_ID，跳过同步")
        return 0

    last_synced_time = ""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
            last_synced_time = state.get("last_synced_time", "")
            print(f"🕒 上次同步时间: {last_synced_time}")

    if not last_synced_time:
        # 初次运行：全量同步（抓取历史所有正文）
        # 用 1970-01-01 作为“最早时间”，避免 Notion 对非常早的年份兼容性问题
        print("🆕 初次运行：将进行 Notion 全量同步（抓取历史所有正文）...")
        last_synced_dt = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    else:
        last_synced_dt = _parse_iso(last_synced_time)

    query_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    out_dir = str(_BASE / "data" / "raw" / "notion")
    os.makedirs(out_dir, exist_ok=True)

    # Notion 数据库 query 有分页（最多 100/页）
    start_cursor = None
    total_candidates = 0
    new_count = 0
    newest_dt = last_synced_dt

    while True:
        payload = {
            "page_size": 100,
            "filter": {
                "timestamp": "last_edited_time",
                "last_edited_time": {"on_or_after": last_synced_dt.isoformat()},
            },
            # 稳定排序：从旧到新，方便观察全量同步进度
            "sorts": [{"timestamp": "last_edited_time", "direction": "ascending"}],
        }
        if start_cursor:
            payload["start_cursor"] = start_cursor

        response = requests.post(query_url, json=payload, headers=headers, timeout=30)
        if response.status_code != 200:
            print(f"❌ 数据库连接失败: {response.text}")
            return 0

        data = response.json()
        results = data.get("results", [])
        has_more = bool(data.get("has_more"))
        start_cursor = data.get("next_cursor")

        if not results and total_candidates == 0:
            print("✅ 没有发现新内容。")
            current_time_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump({"last_synced_time": current_time_iso}, f, ensure_ascii=False, indent=2)
            return 0

        total_candidates += len(results)
        if results:
            print(f"📦 本页发现 {len(results)} 条候选笔记（累计 {total_candidates}），正在抓取正文...")

        for page in results:
            page_id = page["id"]
            last_edit = page["last_edited_time"]
            last_edit_dt = _parse_iso(last_edit)

            # 二次保险：Notion 过滤是 on_or_after（包含断点时刻本身）
            if last_edit_dt <= last_synced_dt:
                continue

            props = page.get("properties", {})
            title = "无标题"
            for _, val in props.items():
                if val.get("id") == "title" and val.get("title"):
                    title = val["title"][0]["plain_text"]
                    break

            print(f"   -> 正在读取: {title} ...")
            content = fetch_page_content(page_id)

            # ✅ 每篇笔记一个文件：避免 ingest 反复把旧内容吃进去
            safe_ts = _safe_filename(last_edit_dt.isoformat())
            safe_title = _safe_filename(title)[:80]
            file_path = os.path.join(out_dir, f"{safe_ts}_{page_id}_{safe_title}.md")

            doc = (
                f"# {title}\n"
                f"- source: notion\n"
                f"- notion_page_id: {page_id}\n"
                f"- last_edited_time: {last_edit}\n\n"
                f"{content}\n"
            )

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(doc)

            new_count += 1
            if last_edit_dt > newest_dt:
                newest_dt = last_edit_dt

        if not has_more:
            break

    # 只要有新内容，就把断点推进到最新一篇的时间
    if new_count > 0:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_synced_time": newest_dt.isoformat()}, f, ensure_ascii=False, indent=2)
        print(f"🎉 成功同步 {new_count} 条笔记正文！")
    else:
        print("✅ 结果都是旧的，无需更新。")

    return new_count

if __name__ == "__main__":
    fetch_updates()