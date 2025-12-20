## SBV Second Brain（v0.72 / 12.21版）

一个“可落盘、可增量更新”的个人 Second Brain：把 **Notion / X（Twitter）** 的内容同步到本地，做 **增量 ingest → 语料库**，再用 **画像 + 最近语料摘要 + 近期用户输入** 作为系统提示词注入，对话时可检索、可联网（可选）。

### 功能概览

- **同步数据源**
  - **Notion**：增量同步 Notion Database 中最近编辑的页面，落盘到 `data_sources/notion/`
  - **X / Twitter**：通过 RapidAPI 增量抓取指定账号的新推文，落盘到 `data_sources/x/<username>/`
- **语料加工（ingest）**
  - 扫描 `data_sources/`，对新增/变更文件做分块与加权，增量追加到 `outputs/corpus.jsonl`
  - 文件哈希断点保存在 `state/sync_state.json`（用于 ingest 增量）
- **画像更新**
  - `profile_update.py` 基于 corpus 的新增行，增量更新 `outputs/user_profile.md`
  - 断点保存在 `state/profile_state.json`（避免重复吸收同一批语料）
- **本地对话入口**
  - `main.py`：注入 `user_profile.md` + 最近30天语料摘要（从 `corpus.jsonl` 抽取）+ 最近用户输入记录（来自 `outputs/brain_memory.md`）
  - 支持工具：SerpAPI 搜索 + Jina 网页读取
- **Telegram 访客模式（可选）**
  - `tg_bot.py`：朋友可通过 Telegram 对话；默认不写入你的 `outputs/brain_memory.md`（不污染你的私密记忆）
  - 支持 **TG Friend Mode**：只影响 TG 的答复路由/模板（`TG_FRIEND_MODE=1`）
- **定时闭环（可选）**
  - `auto_run.py`：每天 12:00 自动执行 Notion/X 同步 → ingest →（有新增 chunk 才）画像更新

### 目录结构（你最常会用到的）

- `connectors/`：数据源同步（Notion / X）
- `data_sources/`：落盘的原始内容（供 ingest 处理）
- `outputs/`
  - `corpus.jsonl`：语料库（增量追加）
  - `user_profile.md`：长期画像（LLM 自动更新）
  - `brain_memory.md`：交互日志（main 会写；tg 默认不写）
  - `dialogs/`：Telegram 对话旁路日志（可选）
- `state/`：断点状态（Notion/X 同步 + ingest + profile_update）

## 快速开始

### 1) 安装依赖

建议 Python 3.10+。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 配置 `.env`

在项目根目录创建 `.env`（可以参考 `env.example`）。

#### 必填（本地对话 / 画像更新）

- **GOOGLE_API_KEY**：Gemini API Key（用于 `main.py` / `profile_update.py`）
- **SERPAPI_API_KEY**：SerpAPI Key（用于联网搜索；friend_mode / main 工具）

#### 可选（Notion 同步）

- **NOTION_API_KEY**
- **NOTION_DATABASE_ID**

#### 可选（X / Twitter 同步）

- **RAPIDAPI_KEY**
- **RAPIDAPI_HOST**
- **X_USERNAMES**：逗号分隔，例如 `mjpmaa,naval`

#### 可选（Telegram）

- **TELEGRAM_BOT_TOKEN**
- **TG_ALLOWED_CHAT_IDS**：可选白名单，逗号分隔
- **TG_MAX_TURNS**：每个 chat 保留的上下文轮数（默认 20）
- **TG_FRIEND_MODE**：`0/1`，开启 TG Friend Mode
- **TG_LOW_TH / TG_HIGH_TH / TG_MIN_HITS**：Friend Mode 路由阈值（见 `friend_mode_config.py`）
- **TG_SAVE_DIALOG**：`0/1`，是否把 TG 对话写入 `outputs/dialogs/*.jsonl`
- **TG_SAVE_DIALOG_DEBUG**：`0/1`，打印日志落盘调试信息

## 使用方法

### A) 先同步（可选）→ ingest → 更新画像

#### 同步 Notion

```bash
python3 connectors/notion_sync.py
```

#### 同步 X（单账号）

```bash
python3 -c "from connectors.x_sync import fetch_updates; print(fetch_updates('mjpmaa'))"
```

#### ingest（增量）

```bash
python3 ingest.py
```

#### 更新画像（只吸收 corpus 新增行）

```bash
python3 profile_update.py
```

### B) 本地对话（CLI）

```bash
python3 main.py
```

- 输入 `q` 或 `quit` 退出
- 输入 `daily` 会触发一个示例“24小时加密市场新闻”请求（便于测试工具链）

### C) 定时闭环（每天 12:00）

```bash
python3 auto_run.py
```

如果 `X_USERNAMES` 为空，则只跑 Notion 同步；如果两者都没新内容，会跳过 ingest/profile 更新。

### D) Telegram Bot（访客模式）

```bash
python3 tg_bot.py
```

默认行为：
- 朋友的对话 **不写入** 你的 `outputs/brain_memory.md`
- Bot 会注入 `user_profile.md` + 近30天语料摘要（不会注入你私聊的“最近用户输入记录”）

想启用 TG Friend Mode（只影响 TG 答复路由/模板）：

```bash
export TG_FRIEND_MODE=1
python3 tg_bot.py
```

## 自检（推荐）

```bash
python3 smoke_test.py
```

## 常见问题

### 1) 跑 `main.py` 提示缺少 Key

- **缺少 GOOGLE_API_KEY**：画像更新/对话模型无法调用
- **缺少 SERPAPI_API_KEY**：联网搜索不可用（不影响纯离线对话，但工具链会受限）

### 2) Notion/X 同步没内容

- Notion：确认 `NOTION_DATABASE_ID` 指向正确的 database，并且 token 有权限
- X：确认 `RAPIDAPI_KEY/RAPIDAPI_HOST` 正确；另外 `connectors/x_sync.py` 是增量抓取，只拉“上次最新 tweet id”之后的内容

### 3) 语料库越来越大怎么办？

- 这是 append-only 设计，建议定期备份 `outputs/corpus.jsonl`
- 如果你要“重做一遍分块”，可以运行：

```bash
python3 ingest.py --full
```
