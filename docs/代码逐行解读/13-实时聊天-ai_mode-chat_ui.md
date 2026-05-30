# 逐行解读：`ui/chat_ui.py`（接待模式与发送）

源文件：[chat_ui.py](../../ui/chat_ui.py)（全文件 1800+ 行；本文只拆 **AI/人工模式、10 秒定时器、手动发送**）

**功能**：实时聊天 UI；`ChatSession.ai_mode` 与界面双向同步；人工模式下 10 秒无输入回 AI；卖家发消息取消 Watchdog。

---

## 状态字段 `_current`（选用会话时）

选中会话后 `_current` 大致包含：

```python
{
  "session_id": int,
  "buyer_uid": str,
  "buyer_nickname": str,
  "account": dict,      # 含 platform_shop_id, seller_user_id, channel_name
  "ai_mode": bool,      # 与 DB ChatSession.ai_mode 一致
}
```

`AIReplyHandler._is_ai_mode_enabled` 读的是 **DB**，因此 UI 改模式必须调 `db_manager.set_session_ai_mode`。

---

## `_set_ai_mode`（第 1735–1757 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1736–1737 | 无 `_current` return | 未选会话。 |
| 1738–1739 | `set_session_ai_mode(sid, ai)` | **持久化**到 SQLite。 |
| 1740 | `self._current["ai_mode"] = ai` | 内存与 UI 按钮状态一致。 |
| 1741 | `_update_header_visuals()` | 刷新「AI 自动接待 / 人工接待中」样式。 |
| 1742–1744 | `ai=True` 时停掉 `_input_activity_timer` | AI 模式不需要 10 秒人工倒计时。 |
| 1745–1747 | `ai=False` 时 `_reset_input_activity_timer()` | 切人工即开始 10 秒倒计时。 |
| 1749–1757 | `InfoBar.success` 提示用户 | |

按钮绑定：`_on_toggle_ai_true` → `_set_ai_mode(True)`；`_on_toggle_ai_false` → `_set_ai_mode(False)`。

---

## `_reset_input_activity_timer`（第 1502–1509 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1504–1505 | 非人工或无人 return | AI 模式不启定时器。 |
| 1506–1507 | 若在跑则 stop | |
| 1508 | `start(10000)` | 10 秒单次触发 `_on_input_activity_timeout`。 |

在 `eventFilter` 里，输入框 KeyPress/FocusIn/MousePress 等会调用此方法**重置**倒计时。

---

## `_on_input_activity_timeout`（第 1511–1522 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1513–1514 | 无 `_current` return | |
| 1515–1516 | 已是 AI 模式 return | |
| 1517–1519 | `set_session_ai_mode(sid, True)` + 更新 `_current` | **自动切回 AI**。 |
| 1520–1522 | 日志 + `_show_ai_mode_notice` | 顶部 InfoBar 提示卖家。 |

---

## `_restore_ai_for_current_if_manual`（约 1488–1500 行）

| 含义 |
|------|
| 切换会话或离开聊天页时，若当前是人工模式，自动改回 AI，避免后台一直不自动回复。 |

---

## `_on_session_clicked`（节选）

| 行为 | 含义 |
|------|------|
| 切换买家前 `_restore_ai_for_current_if_manual` | 上一会话若人工则先回 AI。 |
| 加载 `fresh = get_chat_session_by_id` | 避免树节点上 ai_mode 过期。 |
| `if not ai_mode: _reset_input_activity_timer()` | 打开人工会话即开始 10 秒计时。 |

---

## 手动发送 `_on_send` / `_on_send_done`（第 1772–1823 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1775–1777 | 取文本、非空 | |
| 1778–1779 | 防重入 `_send_thread.isRunning()` | |
| 1783–1790 | `SendHumanMessageThread` + `start()` | **子线程**调 `SendMessage.send_text`，不卡 UI。 |
| 1792–1797 | 失败恢复输入框 + QMessageBox | |
| 1801–1808 | `conversation_hub.record_manual_sent` | 写 DB + 刷新气泡。 |
| 1809–1821 | `notify_outbound_reply(metadata=...)` | **取消 150s Watchdog**（卖家已回复）。 |
| 1822–1823 | 清空输入、重绘消息列表 | |

---

## `_on_human_assist_requested`（第 1329 行起，摘要）

| 步骤 | 含义 |
|------|------|
| 解析 payload | account_id, buyer_uid, question, reason |
| 关闭旧 `HumanAssistDialog` | |
| 新建弹窗 `show()` | |
| `InfoBar.warning` 额外提醒 | |
| `go_to_chat_requested` → 切主窗口到实时聊天并选中会话 | |

弹窗信号由 `core/human_assist_ui.setup_human_assist_popup` 在主窗口启动时挂接。

---

## 三条规则对照表

| 规则 | 代码位置 | 影响 |
|------|----------|------|
| 人工 → 10s 无输入 → AI | `_on_input_activity_timeout` | 仅 UI+DB，下条买家消息走 AI |
| 离开会话/页面 → AI | `_restore_ai_for_current_if_manual` | |
| DB `ai_mode=False` | `AIReplyHandler` 跳过 LLM | Watchdog 仍在 Consumer 启动 |
