# CLAUDE.md

面向 Claude Code（claude.ai/code）及在本仓库内协作的助手：**Python 电商 AI 客服桌面应用**（PyQt6），当前主力渠道为**拼多多** seller WebSocket + 商家后台 HTTP Cookie；可选接入**拼多多开放平台**（`gw-api.pinduoduo.com/api/router`，签名调用）。

---

## 项目概述

- **桌面 UI**：PyQt6 + PyQt-Fluent-Widgets，入口 `app.py` → `ui/main_ui.py`。
- **AI**：Agno + OpenAI 兼容 LLM；知识库可用 LanceDB / SQLite（具体实现见 `Agent/CustomerAgent/agent_knowledge.py`）。
- **拼多多**：`Channel/pinduoduo/pdd_chnnel.py`（注意文件名拼写）维护 WebSocket；`utils/API/send_message.py` 等走 `mms.pinduoduo.com`；开放平台封装见 `utils/API/open_platform_client.py`，物流见 `utils/API/logistics.py`，售后示例见 `utils/API/after_sales.py`。
- **消息链**：`handler_chain()` 顺序为：**AddressChangeHandler** → **OrderLogisticsHandler** → **ImageVideoHumanHandler** → **AfterSalesApplyHandler** → **KeywordDetectionHandler** → **AIReplyHandler** → **CatchAllHandler**（未回复由 Consumer + `fallback_reply` 安抚）。出站文本统一 `Message/handlers/channel_send.py`。
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
uv sync --group dev    # pytest 等
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
| `pdd_chnnel.py` | WebSocket 连接、重连、消息派发 |
| `pdd_login.py` | Playwright 登录 / 刷新 Cookie |
| `pdd_message.py` | 下行消息解析为 `Context`（含订单卡片等） |
| `utils/base_request.py` | Cookie + 重试 + 会话过期再登录 |
| `utils/API/send_message.py` | `plateau/chat/send_message` 等 |

开放平台：`OpenPlatformAPI._call_open_platform()`，`client_id` / `client_secret` / `access_token` 来自 `config.get("pinduoduo_open")`。

### Agent 与知识库

- `Agent/CustomerAgent/agent.py`、`agent_knowledge.py`、`tools/`、`readers/`。
- 另有扩展模块 `knowledge_enhanced.py`（进度等），是否与主路径挂载以实际 import 为准。

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

## 测试目录

- `test/test_ai_handler_async.py`
- `test/test_move_conversation.py`
- `test/test_handler_chain_integration.py` — 处理器链 mock 上下文集成
- `test/test_buyer_lock_registry.py` — 买家锁 LRU
- `test/test_health_server.py` — `/health` / `/ready`

修改处理器链或渠道协议后，建议跑 `pytest` 并做一次手动收发消息验证。
