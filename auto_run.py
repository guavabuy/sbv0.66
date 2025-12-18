import time
import schedule
import datetime
from connectors.notion_sync import fetch_updates
from connectors.x_sync import fetch_updates as fetch_x_updates
from ingest import ingest
from profile_update import update_user_profile
import os
from dotenv import load_dotenv
from connectors.x_sync import fetch_updates as fetch_x_updates

load_dotenv()
X_USERS = [u.strip().lstrip("@") for u in os.getenv("X_USERNAMES", "").split(",") if u.strip()]

def daily_job():
    print(f"\n⏰ [Scheduler] 12:00 到点啦！开始执行每日同步任务...")
    print(f"🕒 当前时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        new_notes_count = fetch_updates()

        new_notes_count = fetch_updates() or 0

        new_x_count = 0
        for u in X_USERS:
            try:
                new_x_count += int(fetch_x_updates(u) or 0)
            except Exception as e:
                print(f"⚠️ [X] @{u} 同步失败：{e}")

        total_updates = int(new_notes_count) + int(new_x_count)
        print(f"📌 同步结果：Notion {new_notes_count}，X {new_x_count}，合计 {total_updates}")

        if total_updates > 0:
            print(f"⚡️ 检测到新内容，开始 ingest...")

            result = ingest(full=False)
            added = int(result.get("added_chunks", 0))
            print(f"🧩 ingest 新增 chunks: {added}")

            if added > 0:
                print("🧠 开始更新 user_profile.md ...")
                update_user_profile()

            print("✅ [Success] 每日更新完成！")
        else:
            print("💤 Notion/X 都没有新内容，跳过 ingest/profile。")

    except Exception as e:
        print(f"❌ [Error] 自动任务出错: {e}")

    print("--------------------------------------------------\n")

if __name__ == "__main__":
    schedule.every().day.at("12:00").do(daily_job)

    print(">>> 🚀 自动化管家已启动")
    print(">>> 📅 计划任务: 每天 12:00 Notion -> ingest -> user_profile.md")
    print(">>> (请保持此终端窗口开启，或者后面我们再把它做成后台服务)")

    while True:
        schedule.run_pending()
        time.sleep(1)
