## SBV Second Brain（v0.73 / 12.22版）

一个可落盘、可增量更新的个人 Second Brain：同步 Notion/X → ingest 成语料库 → 增量更新画像 → 用 `SecondBrain`（self/friend）统一回答（可联网）。

### 目录结构（核心）

- **`apps/`**：入口（只收发）
  - `apps/main.py`：CLI（self）
  - `apps/tg_bot.py`：Telegram（friend）
  - `apps/scheduler.py`：每日 12:00 定时任务（静默写日志）
- **`core/`**：SecondBrain / prompt_loader / privacy / tools / processor
- **`connectors/`**：Notion/X 同步 → 写入 `data/raw/`
- **`prompts/`**：Prompt 模板（`.md`）
- **`scripts/`**：数据管道脚本
  - `scripts/ingest.py`：raw → `data/corpus.jsonl`
  - `scripts/profile_update.py`：增量更新 `data/user_profile.md`
- **`data/`**：
  - `data/raw/`：原始内容（connectors 输出）
  - `data/corpus.jsonl`：语料库
  - `data/user_profile.md`：画像
  - `data/brain_memory.md`：私密日志（仅 self 模式会读；friend 永不读）
- **`logs/`**：
  - `logs/dialogs/`：TG 对话旁路日志（可选开关）
  - `logs/scheduler.log`：定时任务日志

### 快速开始

#### 1) 安装依赖

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

#### 2) 配置 `.env`

在项目根目录创建 `.env`（参考 `env.example`）。

- **必填**：
  - `GOOGLE_API_KEY`：对话/画像更新
  - `SERPAPI_API_KEY`：联网搜索（可选，但建议配）
- **可选（Notion）**：`NOTION_API_KEY`、`NOTION_DATABASE_ID`
- **可选（X）**：`RAPIDAPI_KEY`、`RAPIDAPI_HOST`、`X_USERNAMES=mjpmaa,naval`
- **可选（Telegram）**：`TELEGRAM_BOT_TOKEN`
- **可选（TG 日志）**：`TG_SAVE_DIALOG=1`（写入 `logs/dialogs/`）

### 使用方法

#### A) 同步 → ingest → 更新画像

```bash
python3 connectors/notion_sync.py
python3 -c "from connectors.x_sync import fetch_updates; print(fetch_updates('mjpmaa'))"
python3 scripts/ingest.py
python3 scripts/profile_update.py
```

补充说明：
- **Notion 初次同步**：若 `state/notion_state.json` 不存在或无 `last_synced_time`，会进行**全量同步**（抓取历史所有正文）；之后则按 `last_synced_time` 做增量同步。
- **X 增量同步**：状态写入 `state/x_state.json`（按用户名记录 `latest_id` / `user_id`），每条 tweet 单独落盘到 `data/raw/x/<username>/`。
- **ingest 增量**：`scripts/ingest.py` 使用 `state/sync_state.json` 记录 raw 文件的哈希（判断哪些文件变更/需要重新 ingest）；它和 connectors 的 state **不是一回事**。

#### B) CLI（self）

```bash
# 推荐（模块方式，路径更稳）
python3 -m apps.main
# 也支持直接运行脚本
python3 apps/main.py
```

#### C) Telegram（friend）

```bash
python3 -m apps.tg_bot
# 也支持：
python3 apps/tg_bot.py
```

#### D) 定时任务（每天 12:00，静默后台）

```bash
nohup python3 -m apps.scheduler >/dev/null 2>&1 &
```

（日志见 `logs/scheduler.log`；可用 `SB_SCHEDULE_AT=12:00` 改时间。）
