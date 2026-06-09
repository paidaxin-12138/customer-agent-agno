<!-- Copyright (c) 2026 paidaxin-12138 — CC BY-NC 4.0 — see LICENSE -->

# CLAUDE.md

面向 Claude Code（claude.ai/code）及在本仓库内协作的助手：**Python 电商 AI 客服桌面应用**（PyQt6），当前主力渠道为**拼多多** seller WebSocket + 商家后台 HTTP Cookie；可选接入**拼多多开放平台**（`gw-api.pinduoduo.com/api/router`，签名调用）。

---

## 项目概述

- **桌面 UI**：PyQt6 + PyQt-Fluent-Widgets，入口 `app.py` → `ui/main_ui.py`。
- **AI**：Agno + OpenAI 兼容 LLM；知识库门面 `Agent/CustomerAgent/agent_knowledge.py`，实现拆分为 `knowledge_storage.py`（LanceDB/JSON）、`knowledge_indexer.py`（建索引）、`knowledge_retriever.py`（检索）。架构图见 `docs/architecture.md`。
- **拼多多**：推荐入口 `Channel/pinduoduo/pdd_channel.py`（`PDDChannel`）；WebSocket 实现拆分为 `ws_*` 模块（`ws_account` 启停会话、`ws_inbound_pipeline` 入站、`ws_lifecycle` 清理等）。出站 HTTP 见 `utils/API/send_message.py`（`mms.pinduoduo.com`）；开放平台封装见 `utils/API/open_platform_client.py`，物流见 `utils/API/logistics.py`。
- **消息链**：`handler_chain()` 顺序为：**AddressChangeHandler** → **OrderLogisticsHandler** → **ImageVideoHumanHandler** → **AfterSalesApplyHandler** → **BuyerEmotionHandler** → **KeywordDetectionHandler** → **AIReplyHandler** → **CatchAllHandler**（未回复由 Consumer + `fallback_reply` 安抚）。出站文本统一 `Message/handlers/channel_send.py`。
- **阶段常量**：`core/session_stages.py`（中性包，避免 Agent ↔ Message 循环依赖）。
- **会话状态**：SQLite（`chat_sessions` / `chat_messages`）为权威；UI Hub 经 `database/session_store.py` 刷新摘要与未读。
- **配置**：`config.py` 线程安全读取 `config.json`；开放平台密钥放在 `pinduoduo_open`（见默认 `config_base`）。

---

## 常用命令

### 启动

```bash
source .venv/bin/activate && python app.py   # macOS / Linux
.venv\Scripts\activate && python app.py      # Windows
```

### 依赖（uv）

```bash
uv sync
uv add <package>
uv sync --upgrade
uv sync --group dev    # pytest、black 等
uv run black Agent/CustomerAgent/knowledge_*.py   # 知识库模块格式化
```

### Playwright（登录拼多多商家后台）

```bash
uv run playwright install chromium
# 或 python scripts/install_playwright.py（若仓库提供）
```

### 打包

```bash
python scripts/build_win_exe.py --clean   # 需在 Windows 上
python scripts/build_exe.py
```

### 测试

```bash
uv run python -m pytest test/
```

可选本地工具：`black .`、`mypy .`、`flake8 .`（项目未强制 CI）。

---

## 架构要点

### 消息与处理器

| 组件 | 路径 | 职责 |
|------|------|------|
| 队列与消费者 | `Message/core/queue.py`、`consumer.py` | 异步消费；`metadata` 注入 `shop_id`/`user_id`/`from_uid` |
| 改址 | `Message/handlers/address_change_handler.py` | 改收货地址→查单/弹窗 |
| 物流 | `Message/handlers/order_logistics_handler.py` | 物流意图→开放平台轨迹 |
| 关键词转人工 | `Message/handlers/keyword_handler.py` | DB 关键词命中→转接会话 |
| AI 回复 | `Message/handlers/ai_handler.py` | Bot 回复；尊重会话 `ai_mode` |
| 上下文类型 | `bridge/context.py` | `ContextType`、`ChannelType` |

人工协助弹窗：`core/human_assist_bus.py`（与 UI 联动）。

### 拼多多渠道

| 文件 | 说明 |
|------|------|
| `pdd_channel.py` | **推荐入口**：`PDDChannel`、连接状态 re-export |
| `ws_account.py` | 单账号启停、建连、上线、会话循环 |
| `ws_inbound_pipeline.py` | 入站预处理、路由、入队 |
| `ws_immediate_handlers.py` | AUTH / 转接 / 快捷退款卡等立即处理 |
| `ws_lifecycle.py` | 停止、资源与消费者清理 |
| `core/channel_facade.py` | UI 用连接状态 / 心跳查询门面 |
| `pdd_login.py` | Playwright 登录 / 刷新 Cookie |
| `pdd_message.py` | 下行消息解析为 `Context` |
| `utils/API/send_message.py` | `plateau/chat/send_message` 等 |

开放平台：`OpenPlatformAPI._call_open_platform()`，`client_id` / `client_secret` / `access_token` 来自 `config.get("pinduoduo_open")`。

### Agent 与知识库

- `Agent/CustomerAgent/agent.py`、`agent_knowledge.py`、`tools/`。

### UI（节选）

- `main_ui.py`：主导航与延迟加载子界面。
- `Knowledge_ui.py`、`keyword_ui.py`、`setting_ui.py`、`user_ui.py`、`auto_reply_ui.py`、`log_ui.py`。
- `ai_test_ui.py`：无账号调试对话。
- `chat_ui.py`、`conversation_hub.py`：实时会话相关。

### 核心服务

- `core/di_container.py`：DI（含 `ConnectionStatusManager`、`CustomerAgent` 等注册）。
- `database/db_manager.py`：账号、会话、关键词等 SQLite 持久化。
- `core/production_services.py`：健康检查、定时备份、生命周期清理（daemon 线程）。
- `core/health_server.py`：`/health`（存活）、`/ready`（WS+消费者就绪）、`/metrics`。
- `utils/audit_log.py`：安全审计 → `ops_security_audits`（含改址、Cookie 过期等）。

### 生产部署（本地无人值守）

详见 **`docs/生产部署说明.md`**。要点：

- 守护：PM2（`ecosystem.config.js`）/ Windows NSSM / Linux systemd（`scripts/customer-agent.service`）。
- 健康：`/health` 仅进程存活；`/ready` 503 表示 WS 未连或未消费。
- 日志：`logs/out.log`、`logs/error.log`、`logs/boot.log`（启动诊断与 faulthandler）。
- 环境变量：`LLM_API_KEY`、`AGENT_CREDENTIAL_KEY`；`STRICT_CONFIG=1` 硬失败。
- 冒烟：`uv run python scripts/smoke_test_all.py`（MMS 段需有效 Cookie）。

### 数据流（简化）

买家消息 → `PDDChannel` → 队列 → **处理器链**（物流/改单 → 关键词 → AI）→ `SendMessage.send_text` → 买家。

---

## 技术栈

PyQt6、Agno、SQLAlchemy、SQLite、LanceDB（按需）、websockets、requests、Playwright、Loguru、Pydantic、uv。

---

## 开发约定

- 命名：类 PascalCase，函数/变量 snake_case，常量 UPPER_CASE，文件 snake_case。
- 配置访问：`config.get("a.b.c")`，嵌套键；敏感信息勿入库。
- 阻塞 IO：在 async 路径用 `asyncio.to_thread`（参见 `ai_handler`、`order_logistics_handler`）。
- 新增拼多多 HTTP：优先继承 `BaseRequest`；开放平台 Router 继承 `OpenPlatformAPI`。

---

## 配置（config.json）

- `llm` / `embedder`：模型与密钥。
- `knowledge_base`：路径。
- `chat.manual_mode_send_notice`：人工模式是否发占位提示。
- `pinduoduo_open.enabled`：是否启用开放平台物流查询逻辑；`client_id`、`client_secret`、`access_token` 填开放平台应用与店铺授权。

`config.json` 通常在 `.gitignore` 中，勿提交。

---

## 注意事项

- Python **≥ 3.11**。
- 打包路径与日志目录在 frozen 模式下会落到用户可写目录（见 `config.Config._resolve_config_path`、`runtime_path`）。
- `Channel/pinduoduo/utils/API/get_messages.py` 多为占位，历史消息拉取需自行对接。

---

## 已知限制

| 领域 | 限制 |
|------|------|
| **渠道** | 生产路径以拼多多商家 WebSocket + MMS Cookie 为主；其它平台无一等公民支持。 |
| **登录** | Cookie 依赖 Playwright 登录，过期需人工或脚本刷新；无官方 OAuth 桌面流。 |
| **历史消息** | MMS 历史拉取接口未完整对接，重连后以 Hub/DB 已有记录为主，可能缺断线期间部分消息。 |
| **知识库** | 父子店铺 inherit_key 覆盖需父条显式 `allow_child_override`；向量维度和 embedder 配置不一致时需重建 LanceDB。 |
| **AI** | 回复质量受 LLM/提示词/知识库召回影响；无自动 A/B 与线上评测闭环。 |
| **测试** | UI（PyQt）仅冒烟覆盖；覆盖率门禁针对 `Message`/`core`/`database`/`utils` 核心包，不含 `ui`/`Channel`/`Agent` 全量。 |
| **部署** | 桌面单进程架构，水平扩展需自行拆分渠道与 Agent 服务。 |
| **许可** | 根目录 `LICENSE`（CC BY-NC 4.0）；沿用上游代码段须保留原作者许可与署名。 |

---

## 测试目录

- `test/test_ai_handler_async.py`
- `test/test_move_conversation.py`
- `test/test_handler_chain_integration.py` — 处理器链 mock 上下文集成
- `test/test_buyer_lock_registry.py` — 买家锁 LRU
- `test/test_health_server.py` — `/health` / `/ready`

修改处理器链或渠道协议后，建议跑 `pytest` 并做一次手动收发消息验证。
