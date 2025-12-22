import os
import time
import requests
from dotenv import load_dotenv

# 🔴 请把你的 Notes 数据库 ID 填在这里！
TARGET_DATABASE_ID = "64645e465929452f8d3b0d5a0b53ba43"
headers = {}

# --- 获取单个页面正文的函数 (复用之前的逻辑) ---
def fetch_page_content(page_id):
    content_text = ""
    block_url = f"https://api.notion.com/v1/blocks/{page_id}/children"
    has_more = True
    next_cursor = None
    
    while has_more:
        params = {"page_size": 100}
        if next_cursor: params["start_cursor"] = next_cursor
        
        try:
            resp = requests.get(block_url, headers=headers, params=params)
            if resp.status_code != 200: break
            data = resp.json()
            
            for block in data.get("results", []):
                b_type = block.get("type")
                # 提取段落、标题、列表
                if b_type in ["paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item", "numbered_list_item"]:
                    rich_text = block.get(b_type, {}).get("rich_text", [])
                    if rich_text:
                        text = rich_text[0].get("plain_text", "")
                        if "heading" in b_type: text = f"\n## {text}"
                        if "list" in b_type: text = f"- {text}"
                        content_text += text + "\n"
            
            has_more = data.get("has_more", False)
            next_cursor = data.get("next_cursor")
        except:
            break
            
    return content_text

# --- 主程序：遍历数据库 ---
def import_all():
    # 运行时再加载 .env（读不到也不影响 import；真实运行时依赖环境变量）
    try:
        load_dotenv()
    except Exception:
        pass

    notion_key = os.getenv("NOTION_API_KEY")
    global headers
    headers = {
        "Authorization": f"Bearer {notion_key}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }

    if "请把" in TARGET_DATABASE_ID:
        print("❌ 错误：请先在代码第 11 行填入正确的 DATABASE ID！")
        return

    print(f">>> 🚀 准备全量导出数据库: {TARGET_DATABASE_ID}")
    
    # 确保保存目录存在
    if not os.path.exists("data/raw"):
        os.makedirs("data/raw", exist_ok=True)

    # 查询数据库 (分页处理，以防你有几百篇日记)
    query_url = f"https://api.notion.com/v1/databases/{TARGET_DATABASE_ID}/query"
    has_more = True
    next_cursor = None
    total_count = 0

    while has_more:
        payload = {"page_size": 50} # 每次取50篇
        if next_cursor: payload["start_cursor"] = next_cursor
        
        resp = requests.post(query_url, json=payload, headers=headers)
        if resp.status_code != 200:
            print(f"❌ 读取数据库失败: {resp.text}")
            break
            
        data = resp.json()
        pages = data.get("results", [])
        
        print(f"📦 本批次获取 {len(pages)} 篇笔记，开始下载内容...")

        for page in pages:
            page_id = page["id"]
            
            # 尝试获取标题
            props = page.get("properties", {})
            title = "未命名笔记"
            # 自动寻找 title 类型的字段
            for key, val in props.items():
                if val["id"] == "title" and val["title"]:
                    title = val["title"][0]["plain_text"]
                    break
            
            # 为了防止文件名非法字符 (比如 / 或 :)，简单清洗一下
            safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '-', '_')]).strip()
            if not safe_title: safe_title = f"note_{page_id[:4]}"

            print(f"   -> 正在下载: 《{title}》", end="...", flush=True)
            
            # 下载正文
            content = fetch_page_content(page_id)
            
            # 保存文件
            filename = f"data/raw/{safe_title}.txt"
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"标题: {title}\n")
                f.write(f"原文链接: {page.get('url')}\n")
                f.write("-" * 20 + "\n")
                f.write(content)
            
            print(" ✅ 完成")
            total_count += 1
            time.sleep(0.5) # 休息一下，温柔一点

        has_more = data.get("has_more", False)
        next_cursor = data.get("next_cursor")

    print(f"\n🎉 全部完成！共导入 {total_count} 篇笔记。")
    print("👉 别忘了运行 'python3 scripts/ingest.py' 来消化它们！")

if __name__ == "__main__":
    import_all()


