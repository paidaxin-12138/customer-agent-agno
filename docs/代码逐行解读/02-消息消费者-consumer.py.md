# 逐行解读：`Message/core/consumer.py`（消息消费者）

源文件：[consumer.py](../../Message/core/consumer.py)（共 220 行）

**功能**：从 `SimpleMessageQueue` 取 `MessageWrapper`，补充 metadata，启动 **150s Watchdog**，按顺序调用 **Handler 链**，首个返回 `True` 的 Handler 终止后续处理。

---

## 模块说明与导入（第 1–16 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1–4 | 模块 docstring | 说明这是简化版消费者。 |
| 6 | `import asyncio` | 异步队列、Task、Lock、Semaphore。 |
| 7 | `from typing import Any, Dict, List` | 类型注解。 |
| 9 | `get_logger` | Loguru。 |
| 10 | `Context` | 统一消息结构。 |
| 11 | `queue_manager` | 全局队列管理器，按 `queue_name` 取队列。 |
| 12 | `MessageHandler` | 处理器抽象基类。 |
| 13 | `MessageWrapper` | 队列元素：message_id、context、timestamp。 |
| 16 | `logger = get_logger(__name__)` | 本模块 logger。 |

---

## `MessageConsumer.__init__`（第 19–31 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 19–20 | `class MessageConsumer` | 每个店铺队列通常对应一个 Consumer（如 `pdd_{shop_id}`）。 |
| 22–24 | `queue_name`, `max_concurrent` | 队列名；最大并行处理消息数（默认 28）。 |
| 25 | `self.handlers: List[MessageHandler] = []` | 由 `PDDChannel._setup_message_consumer` 里 `add_handler` 填充。 |
| 26 | `self.semaphore = asyncio.Semaphore(max_concurrent)` | 限制同时 `_process_message` 的个数。 |
| 27–28 | `running`, `consumer_task` | 消费循环是否在跑；`_consume_loop` 的 Task。 |
| 29 | `self.logger = get_logger(f"Consumer.{queue_name}")` | 按队列区分日志。 |
| 30–31 | `_buyer_seq_locks` | **同一买家**消息串行：key 为 `user_key`（见 `_extract_user_id`）。 |

---

## `add_handler` / `is_running`（第 33–40 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 33–36 | `add_handler` | 追加处理器；**顺序即优先级**（先注册先尝试）。 |
| 38–40 | `is_running` | 返回 `self.running`。 |

---

## `start` / `_consume_loop`（第 42–67 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 42–50 | `async def start` | 若已 running 则 warning；否则 `create_task(_consume_loop)`。 |
| 52–54 | `_consume_loop` 取队列 | `queue_manager.get_or_create_queue(self.queue_name)`。 |
| 57 | `while self.running` | 直到 `stop()` 置 `running=False`。 |
| 59 | `wrapper = await queue.get(timeout=1.0)` | 最多等 1 秒；无消息返回 None，循环继续（便于检查 `running`）。 |
| 60–62 | `if wrapper: create_task(_process_message)` | **每条消息独立 Task**；内部还有 semaphore + 买家锁。 |
| 63–65 | `except` + `sleep(0.1)` | 避免死循环打满 CPU。 |
| 66–67 | `finally` 打 stopped 日志 | 循环退出时记录。 |

---

## `stop`（第 69–85 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 71 | `self.running = False` | 消费循环将退出。 |
| 74–81 | 取消 `consumer_task` | 并 await，吞掉 `CancelledError`。 |
| 84–85 | `semaphore.acquire()` 再 `release()` | 等待已拿到信号量的处理完成（粗粒度排空）。 |

---

## `_process_message`（第 87–143 行）— 核心

| 行号 | 代码 | 含义 |
|------|------|------|
| 89 | `user_key = self._extract_user_id(...)` | 形如 `pinduoduo_{from_uid}`，用于买家级锁。 |
| 90 | `lock = self._buyer_seq_locks.setdefault(...)` | 每个买家一个 `asyncio.Lock`。 |
| 91 | `async with self.semaphore` | 全局限流。 |
| 92 | `async with lock` | 同买家消息**排队**处理。 |
| 94 | `processed = False` | 是否有 Handler 成功处理。 |
| 95 | `metadata = wrapper.to_metadata()` | 从 wrapper 复制基础元数据。 |
| 97–109 | 从 `context.kwargs`  enrich | 写入 `shop_id`、`user_id`、`from_uid`、`username`、`channel_name`；供发消息、查 DB、Watchdog 用。 |
| 110 | `metadata["user_key"] = user_key` | 运营统计、转人工 payload 备用。 |
| 112–123 | `start_inbound_watchdog` | **买家消息一进处理就计时**；epoch 写入 `metadata["_watchdog_epoch"]`。 |
| 125–137 | `for handler in self.handlers` | 遍历链。 |
| 127 | `if handler.can_handle(context)` | 类型/内容是否由该 Handler 处理。 |
| 128 | `success = await handler.handle(...)` | 异步处理。 |
| 129–134 | `if success: processed=True; break` | **短路**：后续 Handler 不再执行。 |
| 135–137 | Handler 异常 | 记 error，**continue** 尝试下一个（不是 break）。 |
| 139–140 | 无人处理 | warning。 |
| 142–143 | 外层异常 | 整条消息失败日志。 |

---

## `_extract_user_id`（第 145–166 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 148 | `from_uid = context.kwargs.from_uid` | 拼多多买家 UID。 |
| 149 | `channel = context.channel_type` | 渠道枚举或 None。 |
| 152–155 | None 兜底为 `"unknown"` | 避免 key 拼接失败。 |
| 158–161 | `channel.value` 或 `str(channel)` | 兼容枚举与字符串。 |
| 163 | `return f"{channel_str}_{from_uid}"` | 消费者内部锁的 key（**不是** session_key）。 |
| 164–166 | 异常 | 返回 `unknown_unknown`。 |

---

## `MessageConsumerManager`（第 169–219 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 169–174 | 类定义 | 管理多个 `queue_name → MessageConsumer`。 |
| 176–185 | `create_consumer` | 已存在则 warning 并返回旧实例。 |
| 187–189 | `get_consumer` | 可能返回 None。 |
| 191–197 | `start_consumer` | 对已有 consumer 调 `start()`。 |
| 199–205 | `stop_consumer` | 调 `stop()`。 |
| 211–215 | `stop_all` | 停所有消费者。 |
| 219 | `message_consumer_manager = ...` | **全局单例**，`Message/__init__.py` 导出。 |

---

## 数据流小结

```text
put_message → SimpleMessageQueue
  → _consume_loop.get()
  → _process_message
       → start_inbound_watchdog   # 150s
       → OrderLogistics → ImageVideo → AfterSales → Keyword → AI → CatchAll
       → (某处) notify_outbound_reply  # 取消 watchdog
```
