import time
import schedule
import datetime
from connectors/notion_sync import fetch_updates
from ingest import ingest
from profile_update import update_user_profile

def daily_job():
    print(f"\n⏰ [Scheduler] 12:00 到点啦！开始执行每日同步任务...")
    print(f"🕒 当前时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    try:
        new_notes_count = fetch_updates()

        if new_notes_count and new_notes_count > 0:
            print(f"⚡️ Notion 新增/更新 {new_notes_count} 篇，开始 ingest...")

            result = ingest(full=False)  # 你的新版 ingest.py
            added = int(result.get("added_chunks", 0))
            print(f"🧩 ingest 新增 chunks: {added}")

            if added > 0:
                print("🧠 开始更新 user_profile.md ...")
                update_user_profile()

            print("✅ [Success] 每日更新完成！")
        else:
            print("💤 Notion 没有新内容，跳过 ingest/profile。")

    except Exception as e:
        print(f"❌ [Error] 自动任务出错: {e}")

    print("--------------------------------------------------\n")

schedule.every().day.at("12:00").do(daily_job)

print(">>> 🚀 自动化管家已启动")
print(">>> 📅 计划任务: 每天 12:00 Notion -> ingest -> user_profile.md")
print(">>> (请保持此终端窗口开启，或者后面我们再把它做成后台服务)")

while True:
    schedule.run_pending()
    time.sleep(1)
