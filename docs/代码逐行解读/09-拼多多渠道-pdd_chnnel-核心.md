# 逐行解读：`Channel/pinduoduo/pdd_chnnel.py`（核心路径）

源文件：[pdd_chnnel.py](../../Channel/pinduoduo/pdd_chnnel.py)（约 1214 行）

本文只拆解**自动回复主路径**；重连/心跳/清理等辅助方法见源文件内注释。

---

## 类与构造（第 46–88 行，摘要）

| 行号 | 含义 |
|------|------|
| 46–53 | `PDDChannel` **非单例**：每 `AutoReplyThread` 一个实例，独立 WS + asyncio 循环。 |
| 58–67 | 从 DI 取共享的 `ConnectionStatusManager`，多账号连接状态汇总到监控 UI。 |
| 70–74 | `base_url = wss://m-ws.pinduoduo.com/`。 |
| 72–73 | `_stop_events`：按 `shop_id_user_id` 停止单账号循环。 |
| 77–78 | `ReconnectConfig` / `HeartbeatConfig` 默认参数。 |

---

## `start_account`（第 112–149 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 120–125 | `db_manager.get_account` | 无账号记录则 `on_failure` 并 return。 |
| 127–128 | `username`、`connection_key` | 连接字典 key。 |
| 129 | `_stop_events[connection_key] = asyncio.Event()` | 供消息循环/心跳退出。 |
| 132 | `status_manager.update_status(..., CONNECTING)` | UI 显示连接中。 |
| 135–137 | 取消旧 `_reconnect_tasks` | 防止重复连接任务。 |
| 140–147 | `create_task(_connect_with_retry 或 _connect_single_attempt)` | 真正建 WS 在子协程里。 |
| 149 | 记入 `_reconnect_tasks` | `stop_account` 时可 cancel。 |

---

## `_message_loop`（第 630–655 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 635 | `async for message in websocket` | 阻塞等待下一条 WS 帧。 |
| 636–638 | `stop_event.is_set()` | 用户点「停止自动回复」时 break。 |
| 640–644 | `create_task(_process_websocket_message_concurrent)` | **不 await**，单条消息并发处理（受 semaphore 限制）。 |
| 647–648 | `processing_tasks` 跟踪 | 停止连接时 `cleanup_processing_tasks` 取消。 |
| 650–655 | `ConnectionClosed` 等 | 记录断线，外层重连逻辑接管。 |

---

## `_process_websocket_message_concurrent`（第 657–665 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 661 | `async with self.message_semaphore` | 限制同时解析/入队的 WS 条数（与 Consumer 的 28 是两层限流）。 |
| 663 | `await _process_websocket_message(...)` | 见下节。 |

---

## `_process_websocket_message`（第 796–877 行）— 最重要

| 行号 | 代码 | 含义 |
|------|------|------|
| 801 | `from Message import put_message` | 延迟 import 破循环依赖。 |
| 805–807 | 空消息 return | |
| 809 | `json.loads(message)` | WS 载荷为 JSON 字符串。 |
| 814 | `PDDChatMessage(message_data)` | 见 [15-pdd_message](./15-拼多多原始消息-pdd_message.py.md)。 |
| 821 | `_convert_to_context(...)` | 得到 `Context` 或 None。 |
| 837–846 | `text_suggests_buyer_left` | 系统文案命中 → `emit_buyer_conversation_ended` 清 UI 会话。 |
| 851–855 | `conversation_hub.record_from_context` | **主线程安全路径**内更新实时聊天会话列表（hub 内部再调度）。 |
| 860–862 | `_should_process_immediately` | 认证/撤回/系统消息等，不走 AI 队列。 |
| 864–867 | `_should_queue_message` → `put_message` | 进入 `MessageConsumer` → Handler 链。 |
| 868–870 | else | 忽略的类型，只打 debug。 |

---

## `_setup_message_consumer`（第 747–794 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 752–753 | 延迟 import | `message_consumer_manager`, `handler_chain`, `CustomerAgent`。 |
| 757–768 | 消费者已存在 | 先 `stop_consumer` + `recreate_queue`，避免**事件循环绑定到旧线程**。 |
| 773–777 | `max_concurrent` 从 config 读，限制 1–50 | 默认 28。 |
| 775–777 | `create_consumer(queue_name)` | 队列名如 `pdd_{shop_id}`，同店铺多账号可共享消费者（见停止逻辑）。 |
| 780–787 | DI 取 `CustomerAgent`，`handler_chain(..., bot=bot)`，`add_handler` | 组装 [03-处理器链](./03-处理器链-handler_chain_factory.py.md)。 |
| 789 | `start_consumer` | 启动 `_consume_loop`。 |

---

## 入队 vs 立即处理（第 879–926 行）

| 方法 | 行号 | 含义 |
|------|------|------|
| `_should_process_immediately` | 891–897 | `SYSTEM_STATUS`, `AUTH`, `WITHDRAW`, `SYSTEM_HINT`, `MALL_CS`, `TRANSFER`。 |
| `_should_queue_message` | 915–924 | `TEXT`, `IMAGE`, `VIDEO`, `EMOTION`, `GOODS_*`, `ORDER_INFO`。 |
| `_handle_immediate_message` | 928+ | 如撤回发 `[玫瑰]`、认证打日志，**不经过 AI**。 |

---

## `_convert_to_context`（第 1078–1133 行，摘要）

| 步骤 | 含义 |
|------|------|
| 读 `pdd_message.user_msg_type` | 作为 `Context.type`。 |
| content 转 str | dict 则 `json.dumps`。 |
| `Context.create_pinduoduo_context(...)` | 注入 shop_id、user_id、username、nickname、raw_data。 |

---

## 端到端（单账号）

```text
AutoReplyThread.run
  → PDDChannel.start_account
  → _connect_with_retry → _message_loop
  → _process_websocket_message → put_message
  → MessageConsumer (见 02)
```
