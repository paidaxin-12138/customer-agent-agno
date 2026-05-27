"""
应用程序入口点

全局单例初始化顺序（重要）：
1. config           → 必须在最前面，其他模块都依赖配置
2. DI 容器           → 通过 configure_standard_services() 统一注册所有服务
3. db_manager       → 通过 DI 容器获取
4. logger           → 日志系统，依赖 config
5. queue_manager    → 通过 DI 容器获取
6. message_consumer_manager → 通过 DI 容器获取
7. status_manager   → 通过 DI 容器获取（ConnectionStatusManager 单例）
8. cache_manager    → 通过 DI 容器获取

关键原则：
- config 必须最先初始化
- DI 容器通过 configure_standard_services() 统一管理所有服务的生命周期
- UI 模块在 main() 中通过延迟加载初始化
- 业务模块间通过延迟导入（lazy import）避免循环依赖
- PDDChannel 每个 AutoReplyThread 独立实例，共享 ConnectionStatusManager
"""
import sys
import os
import time
import traceback
import logging
import faulthandler
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon

# ============================================================================
# 全局单例预初始化（确保正确的初始化顺序）
# ============================================================================
# 1. 配置必须最先加载
from config import config as _app_config

# 2. 数据库管理器（通过 DI 代理，懒加载）
from database import db_manager as _app_db_manager

# 3. 日志系统（依赖配置）
from utils.logger_loguru import get_logger as _get_logger

# 4. 配置标准服务到 DI 容器（必须在其他业务模块导入前执行）
from core.di_container import configure_standard_services
configure_standard_services(_app_config)

# ============================================================================

from ui.refined_design import apply_refined_design
from utils.runtime_path import get_app_icon_path


def _setup_boot_log():
    """Write startup diagnostics for packaged app crash investigation."""
    log_dir = Path.home() / "Library" / "Logs" / "AgentCustomer"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "boot.log"

    logger = logging.getLogger("agent_boot")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(file_handler)

    # Capture native crashes (segfault/abort) into the same log file.
    faulthandler.enable(file_handler.stream, all_threads=True)

    def _excepthook(exc_type, exc_value, exc_tb):
        logger.error("Unhandled exception during startup/runtime:")
        logger.error("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook
    logger.info("Boot log initialized.")
    return logger, log_path


def _preload_numpy_safely_on_macos() -> None:
    """Preload NumPy on macOS with sanity-check guard to avoid startup segfault."""
    if sys.platform != "darwin":
        return

    if "numpy" in sys.modules:
        return

    original_platform = sys.platform
    try:
        sys.platform = "linux"
        __import__("numpy")
    finally:
        sys.platform = original_platform

# 设置 Playwright 浏览器路径（支持打包后的 exe）
def get_project_root():
    """获取项目根目录（支持 PyInstaller 打包后的 exe）"""
    import sys
    if getattr(sys, 'frozen', False):
        # PyInstaller 打包后的 exe
        return Path(sys._MEIPASS).parent
    return Path(__file__).resolve().parent

def setup_playwright_browsers_path():
    """设置 Playwright 浏览器安装路径"""
    project_root = get_project_root()
    browsers_path = project_root / ".browsers"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
    return browsers_path

def main():
    """应用程序主函数（同步；Qt 与 asyncio.run 混用易引发事件循环问题）。"""
    boot_logger, boot_log_path = _setup_boot_log()
    boot_logger.info("main() entered.")

    # 设置 Playwright 浏览器路径
    setup_playwright_browsers_path()
    boot_logger.info("Playwright path set.")
    _preload_numpy_safely_on_macos()
    boot_logger.info("NumPy macOS preload completed.")

    from qfluentwidgets import Theme, setTheme
    from ui.main_ui import MainWindow

    # 创建应用
    app = QApplication(sys.argv)
    from utils.qt_threading import init_main_thread_bridge

    init_main_thread_bridge()
    from core.human_assist_bus import get_human_assist_bus

    get_human_assist_bus()  # 确保总线对象驻留 GUI 主线程
    app.setApplicationName("Agent-Customer")
    _icon_path = get_app_icon_path()
    if _icon_path.exists():
        app.setWindowIcon(QIcon(str(_icon_path)))
    boot_logger.info("QApplication initialized.")
    
    # 加载安全配置
    try:
        from utils.secure_config import get_config
        config = get_config()
        boot_logger.info("安全配置加载完成")
    except Exception as e:
        boot_logger.warning(f"安全配置加载失败：{e}")
    
    # macOS 强制深色模式（防止标题栏变白）
    try:
        from PyQt6.QtGui import QPalette, QColor
        palette = app.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#1C1C1E"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Base, QColor("#1C1C1E"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#FFFFFF"))
        app.setPalette(palette)
        boot_logger.info("macOS dark palette applied.")
    except Exception as e:
        boot_logger.warning(f"Failed to apply dark palette: {e}")
    
    # 全局深色主题，与「实时聊天」等自定义深色面板一致
    setTheme(Theme.DARK, save=False, lazy=False)
    apply_refined_design(app)
    boot_logger.info("Theme and global style applied.")

    # 创建主窗口
    logger = _get_logger("App")
    logger.info("应用程序启动...")
    boot_logger.info(f"App logger initialized. boot_log={boot_log_path}")
    # 默认不强制拦截，避免在部分桌面会话中误判导致“闪退”。
    # 如需在无头环境提前退出，可设置: REQUIRE_DISPLAY_CHECK=1
    if os.getenv("REQUIRE_DISPLAY_CHECK", "0") == "1":
        retries = int(os.getenv("HEADLESS_DISPLAY_CHECK_RETRIES", "20"))
        for _ in range(max(1, retries)):
            if app.screens():
                break
            app.processEvents()
            time.sleep(0.1)
        else:
            logger.error("未检测到可用显示设备，无法创建窗口。请在本机桌面会话中启动应用。")
            return

    t0 = time.perf_counter()
    window = MainWindow()
    window.show()
    boot_logger.info("MainWindow shown.")
    logger.info(f"  MainWindow 创建与显示耗时: {time.perf_counter() - t0:.2f}s")

    # 将窗口设为应用级别的变量，防止被垃圾回收
    app.main_window = window


    # 运行事件循环
    sys.exit(app.exec())

if __name__ == '__main__':
    main()
