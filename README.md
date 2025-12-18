## 当前功能（sbv0.66）

* **同步 Notion / X** 内容到 `data_sources/`（支持增量，进度存 `state/`）
* **定时任务**：`auto_run.py` 每天 12:00 执行一次闭环（也支持 `--run-once` 手动触发）
* **语料加工**：`ingest.py` 将 `data_sources/` 新增/变更内容增量写入 `outputs/corpus.jsonl`
* **画像与短期记忆**：`profile_update.py` 基于 `corpus.jsonl` 更新

  * `outputs/user_profile.md`（长期画像，备份 `user_profile.bak.md`）
  * `outputs/brain_memory.md`（短期记忆，最近 30 天）
* **对话检索**：`main.py` 调用 `memory_retriever.py` 检索 `corpus.jsonl`，组合画像+短期记忆进入对话
