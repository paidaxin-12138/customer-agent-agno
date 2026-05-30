# 逐行解读：`AIReplyHandler.handle` 与发送（节选）

源文件：[ai_handler.py](../../Message/handlers/ai_handler.py)  
本节：**`handle`（约 226–335 行）** + **`_send_reply`（约 413–456 行）**

---

## `handle` 入口与人工模式（第 226–235 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 226 | `async def handle(self, context, metadata)` | 实现 `MessageHandler` 接口。 |
| 227–230 | `t0`, `session_key`, `epoch` 初始化 | 计时；session_key 稍后赋值；epoch 来自 consumer 的 watchdog。 |
| 232–235 | `_is_ai_mode_enabled` 为 False | 查 DB `ChatSession.ai_mode`；人工模式：**不发 AI**，`return True`（表示「已处理」以免 CatchAll 再搞，但**不会**自动帮卖家回复）。 |
| 233 | `_maybe_send_manual_mode_notice` | 仅当 `chat.manual_mode_send_notice=true` 才可能发占位话术。 |
| 234–235 | `log_message` + `return True` | 记「AI跳过」日志。 |

---

## 预处理与连发合并（第 237–253 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 237 | `preprocessor.process(content, type)` | 清洗文本、去噪（见 `preprocessor.py`）。 |
| 239–251 | `build_merged_buyer_query_for_ai` | 45 秒内多条买家消息合并成一句再送 LLM，防「只回最后一个字」。 |
| 252–253 | except | 合并失败则用原文。 |

---

## 运营遥测（第 255–276 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 255 | `session_key = self._get_session_key(...)` | 即 `resolve_session_key`。 |
| 258–274 | `start_turn` / `set_rewrite` / `set_intent` | 后台看板统计用；失败只 debug。 |
| 274 | `_pending_intent` | 供后续 `finish_turn` 写意图标签。 |

---

## 排队降级（第 278–280 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 278 | `get_ai_queue_tracker()` | 全局单例，统计 LLM 耗时。 |
| 279–280 | `should_queue_degrade()` | 队列过忙时**不调 LLM**，走 `_handle_queue_degrade`（发固定话术 + 可选转人工弹窗）。 |

---

## 调用 LLM（第 282–291 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 282–283 | `watchdog_epoch = metadata["_watchdog_epoch"]` | 与 consumer 启动的 watchdog 同一 epoch。 |
| 286 | `async with tracker.ai_inflight()` | 进入 inflight 计数，供降级判断。 |
| 287 | `_get_ai_reply_with_sync_retry` | `asyncio.to_thread` 或 `async_reply` 调 `CustomerAgent`；网络错误可重试 1 次。 |
| 289–291 | `is_escalated` | 若等待期间 watchdog 已转人工，**丢弃 AI 正文**不发送。 |

---

## 校验回复并发送（第 293–328 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 293–296 | `_is_invalid_ai_content` | 空或含「AI客服初始化失败」等占位 → `_escalate_immediate(ai_failed)`。 |
| 298 | `_send_reply` | HTTP 发拼多多；成功内部 `notify_outbound_reply`。 |
| 299–318 | 成功分支 | 记耗时、`finish_turn`、`persist_turn_memory`、统计 `ai_ok`、日志。 |
| 319–323 | 发送失败 | `_escalate_immediate(ai_failed)`。 |
| 328 | `return True` | 本条消息处理结束。 |

---

## 异常（第 330–335 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 330–335 | `except Exception` | 任意未捕获错误 → 转人工 `ai_failed`。 |

---

## `_escalate_immediate`（第 337–357 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 346 | `_stats["ai_fallback"] += 1` | 统计。 |
| 347–355 | `await escalate_to_human(self, ...)` | 弹窗 + 发默认安抚话术；`self` 作为 handler 用于 `_send_reply`。 |
| 357 | `return True` | 短路 consumer 链。 |

---

## `_get_ai_reply_with_sync_retry` / `_call_bot_once`（第 359–411 行，摘要）

| 行号 | 含义 |
|------|------|
| 360–362 | 无 bot 返回 None。 |
| 364–371 | 读重试开关与 delay。 |
| 374–393 | 最多 2 次；瞬时网络错误 sleep 后重试。 |
| 400–404 | 优先 `async_reply`。 |
| 405–409 | 否则 `asyncio.to_thread(bot.reply)`。 |
| 410–411 | 无 reply 方法则 warning。 |

---

## `_send_reply`（第 413–456 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 415–418 | 从 metadata 取 shop_id, user_id, from_uid | 缺一则 `return False`。 |
| 431–434 | `SendMessage` + `asyncio.to_thread(send_text)` | 同步 HTTP 放到线程池，不阻塞事件循环。 |
| 435 | `result.get("success")` | 拼多多 MMS 返回结构。 |
| 437–447 | `persist_ai_message` | 写入 SQLite，供实时聊天 UI 显示。 |
| 450–451 | `notify_outbound_reply` | **取消 150s watchdog**。 |
| 454–456 | 异常 | 记 error，返回 False。 |

---

## 与 Watchdog、Bus 的关系

```text
consumer.start_inbound_watchdog
  → AIReplyHandler.handle
       → _send_reply 成功 → notify_outbound_reply
       → 失败/无效 → escalate_to_human → emit_human_assist
```

更多方法（`_is_ai_mode_enabled`、`_handle_queue_degrade`）在同文件前半部分，可按行号继续对照源文件阅读。
