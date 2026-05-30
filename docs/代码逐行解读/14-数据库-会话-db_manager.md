# 逐行解读：`database/db_manager.py`（聊天会话相关）

源文件：[db_manager.py](../../database/db_manager.py)（全文件 1600+ 行；本文只拆 **ChatSession / ChatMessage** 相关）

ORM 定义见 [models.py](../../database/models.py) 中 `ChatSession`、`ChatMessage`。

---

## 单例（第 16–23 行，摘要）

| 含义 |
|------|
| `DatabaseManager` 使用 `__new__` 单例；`db_manager` 全局导入。 |
| 默认库路径 `./temp/customer.db`（可被 config 覆盖）。 |

---

## `get_chat_session_by_buyer`（第 1077–1083 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1078 | `status: str = "active"` | 默认只查未结案会话。 |
| 1080–1082 | 遍历 `get_chat_sessions` 匹配 `buyer_uid` | O(n)；n 为单账号会话数。 |

**调用**：`AIReplyHandler._is_ai_mode_enabled` 判断该买家是否 AI 接待。

---

## `get_chat_session_by_id`（第 1085–1111 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1086 | docstring | 避免 UI 树节点缓存的 `ai_mode` 过期。 |
| 1089–1106 | SQLAlchemy 查 `ChatSession` → dict | 含 `ai_mode`, `status`, `unread_count` 等。 |
| 1107–1110 | 异常返回 None | |

**调用**：`chat_ui` 点击会话时 `fresh = get_chat_session_by_id`。

---

## `get_or_create_chat_session`（第 1113–1164 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1124–1130 | 按 `account_id + buyer_uid` 查 | 唯一约束 `uq_chat_session_account_buyer`。 |
| 1133–1141 | 已存在 | 更新昵称/头像；若 `status==closed` **改回 active**（买家再来）。 |
| 1142–1158 | 新建 | 默认 `ai_mode=True`，`status=active`。 |
| 1155–1157 | `commit` + `refresh` | 返回新 `session_id`。 |

**调用**：`chat_persist` 收到消息时确保有会话行。

---

## `update_session_last_message`（第 1166–1184 行）

| 行号 | 含义 |
|------|------|
| 1174–1176 | 写 `last_message`, `last_message_time`, `updated_at` | 会话列表排序用。 |

---

## `close_chat_session`（第 1186–1201 行）

| 行号 | 含义 |
|------|------|
| 1192 | `status = "closed"` | 后台看板「已解决」据此判断。 |

---

## `close_idle_chat_sessions`（第 1203–1266 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1205–1207 | docstring | 买家最后一条消息超过 `idle_seconds` 则结案。 |
| 1214 | `is_active_chat` | **跳过**当前正在实时聊天窗口打开的会话。 |
| 1230–1236 | `max(sent_at) where sender_type=customer` | 无买家消息的不关。 |
| 1240–1241 | `last_customer > cutoff` 则 skip | 仍活跃。 |
| 1242–1257 | 否则 `status=closed`，收集 account_key | 供 ops 同步。 |

**调用**：`core/session_idle_closer.py` 定时任务。

---

## `set_session_ai_mode`（第 1268–1283 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1274 | `s.ai_mode = ai_mode` | bool 列。 |
| 1275 | `updated_at = now_for_db()` | 上海时区语义，见 `utils/chat_time.py`。 |
| 1276 | `commit` | |

**调用**：`chat_ui._set_ai_mode`、自动切回 AI 的几处逻辑。

---

## `get_session_memory`（第 1285 行起，摘要）

| 字段 | 含义 |
|------|------|
| `task_state_json` | 任务状态机 JSON |
| `long_term_summary` | 长期摘要 |
| `memory_summary_through_id` | 摘要已覆盖到的消息 id |

供 `conversation_memory.build_layered_prompt` 读取。

---

## 表关系（复习）

```text
Account (卖家登录账号)
  └── ChatSession (买家 UID 维度, ai_mode, status)
        └── ChatMessage (sender_type: customer/seller/system, content, ...)
```

---

## 与代码其它部分的衔接

| 场景 | DB API |
|------|--------|
| AI 是否回复 | `get_chat_session_by_buyer` → `ai_mode` |
| 转人工弹窗 | `get_account` + `get_account_row_by_id` |
| 会话列表 | `get_chat_sessions` |
| 5 分钟无买家消息结案 | `close_idle_chat_sessions` |
