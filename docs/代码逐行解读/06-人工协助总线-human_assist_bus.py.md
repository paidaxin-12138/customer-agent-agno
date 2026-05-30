# 逐行解读：`core/human_assist_bus.py`（人工协助总线）

源文件：[human_assist_bus.py](../../core/human_assist_bus.py)（共 215 行）

**功能**：在 **asyncio/WebSocket 线程** 中触发 **Qt 主线程** 弹窗；组装跳转实时聊天所需的 `payload`；持久化系统备注与运营统计。

---

## 模块头（第 1–25 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1–3 | docstring | 跨线程信号总线。 |
| 8 | `QObject, pyqtSignal` | Qt 信号机制基础。 |
| 12 | `_BUS: Optional[HumanAssistBus] = None` | 进程内单例。 |
| 13 | `_bus_log` | 本模块日志。 |
| 16–25 | `_BUYER_SESSION_END_MARKERS` | 系统消息文本命中则视为买家离开会话。 |

---

## `HumanAssistBus` 类（第 28–35 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 28–29 | 继承 `QObject` | 才能定义 `pyqtSignal`。 |
| 31 | `assist_requested = pyqtSignal(dict)` | 需转人工时携带 payload；槽在 `human_assist_ui` / `chat_ui` 连接。 |
| 32 | `buyer_conversation_ended = pyqtSignal(dict)` | 买家结束会话，UI 清理列表项。 |
| 34–35 | `__init__(parent=None)` | 可挂到 `MainWindow` 延长生命周期。 |

---

## `get_human_assist_bus`（第 38–53 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 39 | `global _BUS` | |
| 40–41 | 首次 `HumanAssistBus(parent)` | 创建单例。 |
| 42–50 | `moveToThread(app.thread())` | 若误在非 GUI 线程创建，挪回主线程，保证 `emit` 排队正确。 |
| 51–52 | `setParent(parent)` | 后续传入 MainWindow 时挂上父对象。 |
| 53 | `return _BUS` | |

---

## `text_suggests_buyer_left`（第 56–78 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 59–67 | 仅系统类 `ContextType` | 普通买家 TEXT 不算离开。 |
| 69–73 | content 转字符串 | dict 则 `str(raw)`。 |
| 74–75 | 小写后子串匹配 | 任一 marker 命中返回 True。 |
| 76–78 | 异常 | 返回 False。 |

---

## `build_escalation_payload`（第 81–130 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 88 | `from database.db_manager import db_manager` | 延迟 import。 |
| 91–95 | 从 context/metadata 取渠道、店铺、卖家、登录名 | |
| 96–98 | `get_account` | 无账号则 **return None**（不会弹窗）。 |
| 99–101 | `get_account_row_by_id` | 拿 shop_name 等展示字段。 |
| 102–110 | 解析 `buyer_uid` | kwargs → metadata → `parse_peer_from_context`。 |
| 111–114 | 截断 question 4000 字 | 弹窗展示用。 |
| 115–127 | 组装 dict | `reason`, `account_id`, `buyer_uid`, `buyer_nickname`, `question`… |
| 128–130 | except | debug 后 return None。 |

---

## `emit_human_assist`（第 133–185 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 139 | `build_escalation_payload` | 失败则 warning 并 return（**无弹窗**）。 |
| 146–153 | `labels` 映射 | reason → 中文说明，写入系统 note。 |
| 154 | `note = f"[系统] {labels...}"` | 聊天记录里的系统行。 |
| 155 | `meta_copy = dict(metadata)` | 给 ops 用，避免闭包改原 dict。 |
| 157–181 | `_emit_on_main` 闭包 | 在主线程：`assist_requested.emit` → `persist_escalation_system_note` → `record_human_transfer`。 |
| 183–185 | `run_on_main_thread(_emit_on_main)` | **禁止**在 WS 线程直接 emit 弹窗。 |

---

## `emit_buyer_conversation_ended`（第 188–214 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 197–199 | 查 account | 无则 return。 |
| 200–207 | `ended_payload` | account_id + buyer_uid 等。 |
| 209–210 | `_on_main` 里 emit `buyer_conversation_ended` | |
| 212–214 | `run_on_main_thread` | 同上，线程安全。 |

---

## 谁调用 `emit_human_assist`

| 调用方 | reason 示例 |
|--------|-------------|
| `ai_reply_watchdog.escalate_to_human` | `ai_timeout` |
| `ai_handler._escalate_immediate` | `ai_failed` |
| `keyword_handler` | `keyword_human` |
| `image_video_handler` | `media_human` |
| `order_logistics_handler` | `order_modify` |
| `ai_handler._handle_queue_degrade` | `queue_degrade` |

UI 连接见 [07-Qt主线程调度](./07-Qt主线程调度-qt_threading.py.md) 与 `core/human_assist_ui.py`。
