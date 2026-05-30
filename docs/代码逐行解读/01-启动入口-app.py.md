# 逐行解读：`app.py`（应用程序入口）

源文件：[app.py](../../app.py)（共 197 行）

---

## 文件头注释（第 1–20 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 1–20 | 多行 `"""..."""` | 文档字符串：说明**全局单例初始化顺序**（config → DI → db → 日志 → 队列/消费者 → 连接状态）及设计原则（延迟加载 UI、每账号线程独立 PDDChannel、共享 ConnectionStatusManager）。 |

---

## 标准库与 Qt 导入（第 21–29 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 21 | `import sys` | Python 解释器接口：`sys.argv`、`sys.exit`、`sys.platform`、`异常钩子等。 |
| 22 | `import os` | 操作系统接口：环境变量、`os.environ`。 |
| 23 | `import time` | 睡眠、计时（主函数里测 MainWindow 耗时）。 |
| 24 | `import traceback` | 把异常格式化成字符串写入 boot.log。 |
| 25 | `import logging` | 标准库 logging，专用于 **boot.log**（与业务 Loguru 分离）。 |
| 26 | `import faulthandler` | 捕获 **C 层崩溃**（segfault/abort）写入日志。 |
| 27 | `from pathlib import Path` | 跨平台路径对象。 |
| 28 | `from PyQt6.QtWidgets import QApplication` | Qt 应用程序对象，管理事件循环与 GUI。 |
| 29 | `from PyQt6.QtGui import QIcon` | 窗口/应用图标。 |

---

## 模块级预初始化（第 31–45 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 31–33 | 注释块 | 标明「import 时就会执行」，顺序不能乱。 |
| 35 | `from config import config as _app_config` | 加载 `config.py` 单例，读取/合并 `config.json`；**必须最先**，其他模块 `from config import config` 都依赖它。 |
| 38 | `from database import db_manager as _app_db_manager` | 触发数据库模块注册；实际连接多在首次使用时建立。 |
| 41 | `from utils.logger_loguru import get_logger as _get_logger` | Loguru 日志工厂（业务日志）。 |
| 44–45 | `configure_standard_services(_app_config)` | 向 `core.di_container` 注册 ConnectionStatusManager、DatabaseManager、CustomerAgent 工厂等。 |

---

## 其它模块级导入（第 47–50 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 49 | `from ui.refined_design import apply_refined_design` | 应用全局 QSS/样式。 |
| 50 | `from utils.runtime_path import get_app_icon_path` | 解析图标路径（开发目录 vs 打包目录）。 |

---

## `_setup_boot_log()`（第 53–77 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 53 | `def _setup_boot_log():` | 启动诊断日志，便于打包版闪退排查。 |
| 55 | `log_dir = Path.home() / "Library/Logs" / "AgentCustomer"` | macOS 用户日志目录。 |
| 56 | `log_dir.mkdir(parents=True, exist_ok=True)` | 不存在则创建。 |
| 57 | `log_path = log_dir / "boot.log"` | 启动日志文件路径。 |
| 59 | `logger = logging.getLogger("agent_boot")` | 命名 logger，避免与 root 冲突。 |
| 60 | `logger.setLevel(logging.INFO)` | 只记录 INFO 及以上。 |
| 61 | `logger.handlers.clear()` | 避免重复 handler。 |
| 63–65 | `FileHandler` + `Formatter` + `addHandler` | 写入 `boot.log`，带时间戳。 |
| 68 | `faulthandler.enable(..., all_threads=True)` | 原生崩溃栈写入同一文件。 |
| 70–73 | `_excepthook` | 未捕获 Python 异常也写入 boot.log，再交给默认 excepthook。 |
| 75 | `sys.excepthook = _excepthook` | 全局安装。 |
| 76–77 | `return logger, log_path` | 供 `main()` 打「main() entered」等。 |

---

## `_preload_numpy_safely_on_macos()`（第 80–93 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 80 | `def _preload_numpy_safely_on_macos()` | 仅在 macOS 预加载 NumPy，降低 LanceDB/向量库首次 import 崩溃概率。 |
| 82–83 | `if sys.platform != "darwin": return` | 非 Mac 直接返回。 |
| 85–86 | `if "numpy" in sys.modules: return` | 已加载则跳过。 |
| 88–93 | 临时 `sys.platform = "linux"` 再 `__import__("numpy")` | 规避部分 Mac 上 NumPy 与 BLAS 的已知问题（hack）。 |

---

## `get_project_root()` / `setup_playwright_browsers_path()`（第 96–109 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 96–102 | `get_project_root()` | 开发：`app.py` 所在目录；PyInstaller：`sys._MEIPASS` 父目录。 |
| 104–109 | `setup_playwright_browsers_path()` | 设置 `PLAYWRIGHT_BROWSERS_PATH` 为项目下 `.browsers`，打包后浏览器放此处。 |

---

## `main()`（第 111–193 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 111 | `def main():` | 同步入口；**不在此** `asyncio.run()`，asyncio 在 AutoReplyThread 里。 |
| 113–114 | `_setup_boot_log()` + `boot_logger.info("main() entered.")` | 最早的可追踪日志点。 |
| 117–118 | `setup_playwright_browsers_path()` | 拼多多登录用 Playwright 前必须设路径。 |
| 119–120 | `_preload_numpy_safely_on_macos()` | Mac 预加载 NumPy。 |
| 122–123 | `from ... MainWindow` | **延迟 import**，避免 import `ui` 时拉起整个界面树。 |
| 126 | `app = QApplication(sys.argv)` | 创建 Qt 应用；`sys.argv` 支持命令行参数。 |
| 127–129 | `init_main_thread_bridge()` | 创建 `_MainThreadBridge`，供 WS 线程回调 UI。 |
| 130–132 | `get_human_assist_bus()` | 在主线程创建 `HumanAssistBus` QObject。 |
| 133 | `app.setApplicationName("Agent-Customer")` | 应用显示名。 |
| 134–136 | `setWindowIcon` | 若图标文件存在则设置。 |
| 137 | `boot_logger.info("QApplication initialized.")` | 启动里程碑。 |
| 140–145 | `secure_config.get_config()` | 可选 `.env` 覆盖；失败只 warning，不退出。 |
| 148–158 | `QPalette` 深色 | macOS 标题栏/窗口底色与深色 UI 一致。 |
| 161–163 | `setTheme(DARK)` + `apply_refined_design(app)` | Fluent 深色主题 + 项目样式。 |
| 166–168 | `_get_logger("App")` + 启动日志 | 业务 Loguru 记录「应用程序启动」。 |
| 171–180 | `REQUIRE_DISPLAY_CHECK` | 默认关闭；设为 `1` 时无屏幕则退出（无头服务器场景）。 |
| 182–186 | `MainWindow()` + `show()` + 耗时日志 | 主窗口；内部 200ms 后 lazy_load 子页。 |
| 189 | `app.main_window = window` | 挂到 app 上防止被 GC 回收。 |
| 193 | `sys.exit(app.exec())` | 进入 Qt 事件循环；退出码传给 shell。 |

---

## 脚本入口（第 195–196 行）

| 行号 | 代码 | 含义 |
|------|------|------|
| 195 | `if __name__ == '__main__':` | 仅直接 `python app.py` 时执行。 |
| 196 | `main()` | 调用主函数。 |

---

## 与本文件相关的调用链

```text
python app.py
  → main()
  → MainWindow (ui/main_ui.py)
       → setup_human_assist_popup
       → lazy_load_views → AutoReplyUI / ChatLiveWidget / ...
```

自动回复 **不会** 在 `app.py` 里启动，需在「监控面板」点连接后由 `AutoReplyThread` 启动 `PDDChannel`。
