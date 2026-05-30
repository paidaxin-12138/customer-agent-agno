# 逐行解读：`Message/handlers/ai_reply_watchdog.py`（150 秒未回复兜底）

源文件：[ai_reply_watchdog.py](../../Message/handlers/ai_reply_watchdog.py)（共 319 行）

---

## 模块头与全局状态（第 1–28 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1–4 | docstring | 超时转人工 + 在 **Consumer 入口** 启动。 |
| 5 | `from __future__ import annotations` | 类型前向引用。 |
| 7–8 | `asyncio`, `time` | 异步等待与单调时钟。 |
| 11–13 | `Context`, `config`, `get_logger` | 消息模型、配置、日志。 |
| 15–16 | `TYPE_CHECKING` 下 import `AIReplyHandler` | 仅类型检查用，避免运行时循环 import。 |
| 18 | `logger = get_logger("AIReplyWatchdog")` | |
| 20 | `_tasks` | `session_key → asyncio.Task`，当前 watchdog 协程。 |
| 21 | `_epoch` | `session_key → int`，每轮买家消息递增，用于区分「第几轮」等待。 |
| 22 | `_replied_epoch` | 已成功回复的 epoch 上限。 |
| 23 | `_escalated_epoch` | 已转人工的 epoch 上限。 |
| 24 | `_turn_store` | 超时触发时用的 context/metadata/question 快照。 |
| 25 | `_lock` | `begin_watchdog_turn` 里改 epoch/task 时互斥。 |
| 27–28 | 默认安抚话术常量 | `ai_timeout` 用「不好意思亲亲…」；其它 reason 用「稍等下…」。 |

---

## 配置与 session_key（第 31–83 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 31–40 | `_buyer_notice_for_escalation` | 优先级：参数 > `config chat.ai_watchdog_escalate_notice` > reason 默认。 |
| 43–44 | `_watchdog_enabled` | 读 `chat.ai_watchdog_enabled`，默认 True。 |
| 47–52 | `_escalate_after_sec` | 读秒数，限制在 [30, 3600]。 |
| 55–83 | `resolve_session_key` | 拼 `channel:shop:user:buyer`；缺 `from_uid` 时从 kwargs 或 `parse_peer_from_context` 补。 |

---

## 等待与 epoch 管理（第 86–141 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 86–98 | `_sleep_until_delivered` | 每秒醒一次；若已回复、或 epoch 被新消息顶掉 → 返回 False（不转人工）；超时且仍未回复 → True。 |
| 101–110 | `begin_watchdog_turn` | epoch+1；取消旧 Task；返回新 epoch。 |
| 113–115 | `register_task` | 记录当前 Task 引用。 |
| 117–121 | `is_escalated` | AI 发送前检查：若已超时转人工，则不再发 AI 正文。 |
| 124–129 | `mark_delivered` | 出站成功 → 记入 `_replied_epoch`。 |
| 132–133 | `_is_delivered` | 比较 `replied_epoch >= epoch`。 |
| 136–141 | `mark_escalated` | 转人工后标记，避免重复弹窗逻辑混乱。 |

---

## `notify_outbound_reply` / `start_inbound_watchdog`（第 144–189 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 144–155 | `notify_outbound_reply` | AI/关键词/手动发消息成功后调用 → `mark_delivered`。 |
| 158–189 | `start_inbound_watchdog` | Consumer 调用；无 session_key 则 warning 返回 0；否则 `begin_watchdog_turn` + 存 `_turn_store` + `schedule_inbound_watchdog`。 |

---

## 发送与转人工（第 192–248 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 192–216 | `_send_buyer_text` | Watchdog 超时且没有 AIReplyHandler 时，直接用 `SendMessage` 发安抚话术。 |
| 219–248 | `escalate_to_human` | `mark_escalated` → `emit_human_assist` → 发 notice → 成功则 `mark_delivered`。 |
| 242–245 | `handler is not None` | 有 AI Handler 用其 `_send_reply`（含 persist）；否则 `_send_buyer_text`。 |

---

## 后台协程与调度（第 251–318 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 251–283 | `_run_inbound_watchdog` | 等到 deadline；若需转人工则从 `_turn_store` 取 context 调 `escalate_to_human(..., reason="ai_timeout")`。 |
| 282–283 | `raise CancelledError` | 新消息 `begin_watchdog_turn` 取消旧 Task 时正常传播。 |
| 286–298 | `schedule_inbound_watchdog` | `get_running_loop()` + `create_task(_go)`。 |
| 302–318 | `schedule_watchdog` | 兼容旧 API：补全 `_turn_store` 后调 `schedule_inbound_watchdog`。 |

---

## 时序（单轮买家消息）

```text
T0  start_inbound_watchdog → epoch=1, Task 开始 sleep
T?  notify_outbound_reply   → mark_delivered → Task 醒来返回，不转人工
或
T0+150s  Task 超时 → emit_human_assist + 发「不好意思亲亲…」
```
