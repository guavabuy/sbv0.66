import os
import json
import time
import requests
import re
from datetime import datetime
from dotenv import load_dotenv

# 加载配置
load_dotenv()
API_KEY = os.getenv("RAPIDAPI_KEY")
API_HOST = os.getenv("RAPIDAPI_HOST")

if not API_KEY or not API_HOST:
    print("❌ 错误: 请检查 .env 文件中的 API Key 和 Host 设置")
    exit()

# 基础配置
BASE_URL = f"https://{API_HOST}"
HEADERS = {
    "X-RapidAPI-Key": API_KEY,
    "X-RapidAPI-Host": API_HOST,
    "Content-Type": "application/json"
}

# --- ⚙️ 抓取设置 ---
MAX_PAGES = 10     # 想抓多少页？(每页约40条)
TIME_SLEEP = 2     # 翻页间隔秒数 (防封)
STATE_PATH = os.path.join("state", "sync_state.json")
DATA_DIR = os.path.join("data_sources", "x")


def convert_to_markdown(username, json_path):
    """将 JSON 转换为 Markdown"""
    print(f"⚙️ 正在将数据转换为 Markdown...")
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            all_pages = json.load(f) # 注意：这里读入的是一个列表（多页数据）
        
        # 准备 Markdown 头部
        md = f"# Twitter Archive: @{username}\n\n"
        md += f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n---\n\n"

        total_tweets = 0
        
        # 遍历每一页数据
        for page_data in all_pages:
            tweets = []
            try:
                # 适配 Twttr API 结构: result -> timeline -> instructions
                instructions = page_data.get('result', {}).get('timeline', {}).get('instructions', [])
                for instr in instructions:
                    if instr.get('type') == 'TimelineAddEntries':
                        tweets = instr.get('entries', [])
                        break
            except:
                continue

            # 遍历单页里的推文
            for entry in tweets:
                if not entry.get('entryId', '').startswith('tweet-'): continue
                try:
                    res = entry['content']['itemContent']['tweet_results']['result']
                    legacy = res.get('legacy') or res
                    
                    text = legacy.get('full_text', '').replace('\n', '\n> ')
                    date = legacy.get('created_at', '')
                    tid = legacy.get('id_str', '')
                    
                    # 写入 Markdown
                    md += f"### 📅 {date}\n\n> {text}\n\n"
                    md += f"🔗 [Link](https://twitter.com/{username}/status/{tid})\n\n---\n\n"
                    total_tweets += 1
                except: continue

        # 保存 Markdown
        md_path = json_path.replace('.json', '.md')
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md)
        print(f"✨ Markdown 笔记已生成: {md_path} (共 {total_tweets} 条)")
            
    except Exception as e:
        print(f"❌ 转换 Markdown 失败: {e}")

def save_to_json(username, all_data):
    """保存所有页的数据"""
    output_dir = "data_sources"
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    filename = os.path.join(output_dir, f"twitter_{username}_rapid.json")
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 数据已保存: {filename} (共 {len(all_data)} 页)")
    
    # 自动转换
    convert_to_markdown(username, filename)

def get_user_id(username):
    """获取用户 ID (适配 Twttr API)"""
    print(f"🔍 正在查询 @{username} 的 ID...")
    url = f"{BASE_URL}/user" 
    params = {"username": username}

    try:
        response = requests.get(url, headers=HEADERS, params=params)
        data = response.json()
        
        # 尝试多层提取
        try:
            return data.get("result", {}).get("data", {}).get("user", {}).get("result", {}).get("rest_id")
        except: pass
        
        if "rest_id" in data: return data["rest_id"]
        if "id" in data: return data["id"]
        
        print(f"⚠️ 未找到 ID: {str(data)[:100]}...")
        return None
    except Exception as e:
        print(f"❌ ID 查询出错: {e}")
        return None

def extract_cursor(data):
    """从一页数据中提取翻页用的 cursor"""
    # 1. 尝试从标准结构提取
    try:
        instructions = data.get('result', {}).get('timeline', {}).get('instructions', [])
        for instr in instructions:
            if instr.get('type') == 'TimelineAddEntries':
                entries = instr.get('entries', [])
                for entry in entries:
                    if str(entry.get('entryId', '')).startswith('cursor-bottom-'):
                        return entry['content']['itemContent']['value']
    except: pass
    
    # 2. 如果结构变了，用正则暴力提取
    data_str = json.dumps(data)
    # 寻找 value 字段中以 DAA 开头的长字符串
    matches = re.findall(r'"value"\s*:\s*"(DAA[^"]+)"', data_str)
    if matches:
        return matches[-1] # 返回最后一个 cursor (通常是下一页)
        
    return None

def _load_state() -> dict:
    try:
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}

def _save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def _get_x_users_state(state: dict) -> dict:
    state.setdefault("x_users", {})
    if not isinstance(state["x_users"], dict):
        state["x_users"] = {}
    return state["x_users"]

def _extract_tweets_from_page(page_data: dict) -> list:
    tweets = []
    try:
        instructions = page_data.get("result", {}).get("timeline", {}).get("instructions", [])
        entries = []
        for instr in instructions:
            if instr.get("type") == "TimelineAddEntries":
                entries = instr.get("entries", [])
                break

        for entry in entries:
            if not str(entry.get("entryId", "")).startswith("tweet-"):
                continue
            try:
                res = entry["content"]["itemContent"]["tweet_results"]["result"]
                legacy = res.get("legacy") or res
                tid = legacy.get("id_str") or ""
                if not tid:
                    continue
                tweets.append({
                    "id": str(tid),
                    "created_at": legacy.get("created_at", ""),
                    "text": (legacy.get("full_text", "") or "").strip(),
                })
            except Exception:
                continue
    except Exception:
        pass
    return tweets

def fetch_updates(username: str, max_pages: int = 2) -> int:
    """
    增量抓取：只抓“上次最新 tweet id”之后的新贴文。
    进度写入 state/sync_state.json -> x_users[username].latest_id
    新内容落盘到 data_sources/x/<username>/tweets_<timestamp>.md（利于 ingest 增量）
    返回：新增 tweet 数
    """
    username = (username or "").strip().lstrip("@")
    if not username:
        print("⚠️ [X] username 为空，跳过")
        return 0

    state = _load_state()
    x_users = _get_x_users_state(state)
    u = x_users.setdefault(username, {})

    user_id = u.get("user_id")
    if not user_id:
        user_id = get_user_id(username)
        if not user_id:
            print(f"❌ [X] 无法获取 @{username} 的 user_id")
            return 0
        u["user_id"] = user_id

    last_seen_id = u.get("latest_id")
    print(f"🐦 [X] @{username} 增量同步开始 (last_seen_id={last_seen_id})")

    url = f"{BASE_URL}/user-tweets"
    cursor = None
    raw_pages = []
    collected = []
    stop = False

    for _ in range(max_pages):
        params = {"user": user_id, "include_replies": "false", "count": 40}
        if cursor:
            params["cursor"] = cursor

        resp = requests.get(url, headers=HEADERS, params=params)
        if resp.status_code != 200:
            print(f"❌ [X] 请求失败: {resp.status_code} {resp.text[:120]}")
            break

        data = resp.json()
        raw_pages.append(data)

        for t in _extract_tweets_from_page(data):
            if last_seen_id and t["id"] == last_seen_id:
                stop = True
                break
            collected.append(t)

        if stop:
            break

        next_cursor = extract_cursor(data)
        if not next_cursor or next_cursor == cursor:
            break
        cursor = next_cursor
        time.sleep(TIME_SLEEP)

    # 去重
    uniq = []
    seen = set()
    for t in collected:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        uniq.append(t)

    if not uniq:
        print(f"💤 [X] @{username} 没有新贴文")
        return 0

    # 更新 latest_id（取最大）
    try:
        latest_id = str(max(int(t["id"]) for t in uniq))
    except Exception:
        latest_id = uniq[0]["id"]

    u["latest_id"] = latest_id
    u["last_sync_at"] = datetime.now().isoformat(timespec="seconds")
    _save_state(state)

    # 写新增文件（每次一个新 md）
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(DATA_DIR, username)
    os.makedirs(out_dir, exist_ok=True)

    md_path = os.path.join(out_dir, f"tweets_{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# X Incremental: @{username}\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"New tweets: {len(uniq)}\n\n---\n\n")
        for t in uniq:
            text = (t["text"] or "").replace("\n", "\n> ")
            f.write(f"### 📅 {t['created_at']}\n\n> {text}\n\n")
            f.write(f"🔗 [Link](https://twitter.com/{username}/status/{t['id']})\n\n---\n\n")

    raw_path = os.path.join(out_dir, f"raw_{ts}.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_pages, f, ensure_ascii=False, indent=2)

    print(f"✅ [X] @{username} 新增 {len(uniq)} 条，已写入: {md_path}")
    return len(uniq)

def fetch_all_tweets(username, user_id):
    """主抓取循环"""
    print(f"🚀 开始抓取...")
    url = f"{BASE_URL}/user-tweets"
    
    all_pages = []
    cursor = None
    page = 0
    
    while page < MAX_PAGES:
        page += 1
        print(f"📄 第 {page} 页...", end="", flush=True)
        
        params = {
            "user": user_id,
            "include_replies": "false",
            "count": 40
        }
        if cursor:
            params["cursor"] = cursor
            
        try:
            response = requests.get(url, headers=HEADERS, params=params)
            
            if response.status_code != 200:
                print(f" ❌ 失败: {response.status_code}")
                break
                
            data = response.json()
            all_pages.append(data)
            print(" ✅", end="")
            
            # 找下一页的 cursor
            next_cursor = extract_cursor(data)
            if next_cursor and next_cursor != cursor:
                cursor = next_cursor
                print(f" (找到下一页)")
                time.sleep(TIME_SLEEP)
            else:
                print(" (已到末尾)")
                break
                
        except Exception as e:
            print(f"\n❌ 出错: {e}")
            break
            
    # 循环结束后保存
    if all_pages:
        save_to_json(username, all_pages)
    else:
        print("❌ 未抓取到数据")

if __name__ == "__main__":
    target_user = input("请输入用户名: ").strip()
    if target_user:
        uid = get_user_id(target_user)
        if uid:
            print(f"✅ ID: {uid}")
            fetch_all_tweets(target_user, uid)
        else:
            print("❌ 无法获取 ID")