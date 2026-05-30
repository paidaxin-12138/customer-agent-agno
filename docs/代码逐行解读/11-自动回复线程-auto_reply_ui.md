# 逐行解读：`ui/auto_reply_ui.py`（自动回复线程）

源文件：[auto_reply_ui.py](../../ui/auto_reply_ui.py)（节选 `AutoReplyManager` + `AutoReplyThread`）

**功能**：监控面板点「连接」后，为每个账号起一个 **QThread**，在线程内跑 **独立 asyncio 循环** 和 **PDDChannel**，与 Qt 主线程分离。

---

## `AutoReplyManager`（第 20–162 行，摘要）

| 行号 | 方法 | 含义 |
|------|------|------|
| 24 | `running_accounts: Dict[str, AutoReplyThread]` | key = `{channel}_{shop_id}_{username}`。 |
| 27–48 | `start_auto_reply(account_data)` | 若已在运行则 warning；`AutoReplyThread(account_data).start()`；连接信号。 |
| 42–44 | `connection_success/failed/finished` | 更新 UI 状态、清理 `running_accounts`。 |
| 146–158 | `stop_all` | 停所有线程，`wait(5000)`。 |

---

## `AutoReplyThread` 信号（第 168–169 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 168 | `connection_success = pyqtSignal()` | WS 连接成功 → 监控页绿灯。 |
| 169 | `connection_failed = pyqtSignal(str)` | 失败原因字符串 → 提示用户。 |

---

## `__init__`（第 171–175 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 171–172 | `super().__init__()` | QThread 基类。 |
| 173 | `self.account_data` | 含 `shop_id`, `user_id`, `channel_name`, `username` 等。 |
| 174 | `self.channel = None` | 在 `run()` 里赋值为 `PDDChannel()`。 |

---

## `run`（第 177–215 行）— 全文逐行

| 行号 | 代码 | 含义 |
|------|------|------|
| 177 | `def run(self):` | **在新 OS 线程**执行，不是主线程。 |
| 179 | `from ... PDDChannel` | 延迟 import，避免启动 UI 时拉 websockets。 |
| 183 | `self.loop = asyncio.new_event_loop()` | 本线程专属事件循环。 |
| 184 | `asyncio.set_event_loop(self.loop)` | 后续 `get_running_loop()` 都指此 loop。 |
| 187 | `self.channel = PDDChannel()` | 新渠道实例。 |
| 190–191 | `on_success` | 内层 `self.connection_success.emit()` → **跨线程**到 Qt 主线程槽。 |
| 193–194 | `on_failure` | `connection_failed.emit(error_msg)`。 |
| 197–204 | `create_task(channel.start_account(...))` | 异步连接；**注意**：task 创建后未 await，靠 `run_forever` 驱动。 |
| 199–201 | `shop_id/user_id` 来自 `account_data` | 与 DB 账号一致。 |
| 207 | `self.loop.run_forever()` | 阻塞本线程直到 `stop()` 调 `loop.stop()`。 |
| 209–211 | except | 启动异常 → `connection_failed`。 |
| 212–215 | finally | 停止并 `close()` 事件循环，释放资源。 |

---

## `stop`（第 217–232 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 220–221 | `channel.request_stop()` | 置所有 `_stop_events`，WS 循环退出。 |
| 224–229 | `call_soon_threadsafe(loop.stop)` | 从其他线程安全停止 `run_forever`。 |
| 226–228 | cancel `all_tasks` | 取消未完成的 asyncio 任务。 |

---

## `is_running`（第 234–237 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 237 | `return self.isRunning()` | QThread 是否存活；**不**等于 WS 一定已连接。 |

---

## 线程关系图

```text
[Qt 主线程]  MainWindow / AutoReplyManager.start_auto_reply()
       │
       ▼ start()
[AutoReplyThread]  asyncio loop + PDDChannel + MessageConsumer
       │ emit connection_success / assist_requested (经 run_on_main_thread)
       ▼
[Qt 主线程]  更新 UI、弹窗
```

**禁止**在 `AutoReplyThread` 里直接 `QWidget.show()`，见 [07-Qt主线程调度](./07-Qt主线程调度-qt_threading.py.md)。
