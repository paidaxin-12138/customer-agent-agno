# 逐行解读：`utils/qt_threading.py`（Qt 主线程调度）

源文件：[qt_threading.py](../../utils/qt_threading.py)（共 69 行）

**功能**：把任意线程里的 Python 回调 `fn()` 投递到 **Qt GUI 主线程** 执行，避免 macOS 上 WebSocket 线程直接操作 UI 导致崩溃。

---

## 逐行表

| 行号 | 代码 | 含义 |
|------|------|------|
| 1–3 | docstring | 说明用途。 |
| 4 | `from __future__ import annotations` | |
| 6 | `Callable, Optional` | 类型。 |
| 8–9 | `QObject, Qt, QThread, pyqtSignal, pyqtSlot` | Qt 核心。 |
| 9 | `QApplication` | 判断当前是否主线程。 |
| 13 | `_log` | |
| 15 | `_bridge: Optional[_MainThreadBridge] = None` | 全局桥，单例。 |
| 18–19 | `class _MainThreadBridge(QObject)` | 必须 QObject 才能有信号。 |
| 19 | `call = pyqtSignal(object)` | 载荷是一个 **可调用对象** `fn`（无参）。 |
| 21–22 | `__init__` + `connect(..., QueuedConnection)` | 槽 `_dispatch` 始终在 **bridge 所在线程**（主线程）执行。 |
| 25–26 | `@pyqtSlot(object)` | 显式槽，跨线程 invoke 更可靠。 |
| 26 | `def _dispatch(self, fn)` | |
| 27–28 | `if not callable(fn): return` | 防止误 emit 非函数。 |
| 29–32 | `try: fn()` | 执行 UI 逻辑；异常记 error + traceback。 |
| 35–47 | `init_main_thread_bridge` | |
| 37 | `global _bridge` | |
| 38–40 | 无 `QApplication` 则 return | `app.py` 里应先 `QApplication` 再 init。 |
| 41–42 | 已存在则 return | 只初始化一次。 |
| 43 | `_bridge = _MainThreadBridge(parent or app)` | parent 通常是 `QApplication`。 |
| 44–46 | `moveToThread(app.thread())` | 确保 bridge 驻留 GUI 线程。 |
| 47 | debug 日志 | |
| 50–68 | `run_on_main_thread(fn)` | |
| 52–58 | 无 app 时直接 `fn()` | 单元测试或无 GUI 场景；可能不安全。 |
| 60–62 | 当前已是主线程 | **同步**执行 `fn()`，无队列延迟。 |
| 64–66 | `_bridge is None` | warning 并 **跳过**（不静默执行 fn，避免崩溃）。 |
| 68 | `_bridge.call.emit(fn)` | 非主线程：Qt 将 `_dispatch` 排到主线程事件循环。 |

---

## 调用时序

```text
AutoReplyThread (asyncio)
  → emit_human_assist
       → run_on_main_thread(_emit_on_main)
            → _bridge.call.emit(_emit_on_main)   # 跨线程
                 → [Qt 事件队列]
                      → _dispatch(_emit_on_main)  # 主线程
                           → assist_requested.emit(payload)
                                → ChatLiveWidget._on_human_assist_requested
```

---

## 注意

- 必须在 `app.py` 的 `QApplication` 之后调用 `init_main_thread_bridge()`。  
- `fn` 不要捕获过大对象或已销毁的 QWidget 引用。  
- 主线程 `run_on_main_thread` 会同步执行，注意重入（弹窗里再调 bus 等）。
