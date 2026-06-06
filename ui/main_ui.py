"""
拼多多 AI 客服助手 - 主界面
macOS 风格设计
"""

import os
import sys
import threading
import time
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QSplitter,
)
from PyQt6.QtGui import QCloseEvent, QFont, QIcon
from qfluentwidgets import FluentWindow, NavigationItemPosition
from qfluentwidgets import FluentIcon as FIF
import time

from ui.macos_fonts import MacOSFonts, MacOSSpacing
from ui.macos_window_chrome import apply_dark_titlebar_chrome, use_unified_dark_titlebar
from utils.dialogs import confirm_action
from utils.logger_loguru import get_logger
from utils.runtime_path import get_app_icon_path, keep_macos_bundle_dock_icon

logger = get_logger("MainWindow")

SHUTDOWN_TIMEOUT_SEC = 5.0


async def stop_all_services() -> None:
    """异步停止 WebSocket、消息消费者、Watchdog 等后台服务（委托 core.app_shutdown）。"""
    from core.app_shutdown import stop_all_services as _stop

    await _stop()


def run_stop_all_services_sync(timeout: float = SHUTDOWN_TIMEOUT_SEC) -> None:
    """同步执行服务清理，最多等待 timeout 秒。"""
    from core.app_shutdown import run_stop_all_services_sync as _run

    _run(timeout)


class Widget(QFrame):
    """内容容器"""
    
    def __init__(self, text: str, parent=None):
        super().__init__(parent=parent)
        self.setObjectName("cardFrame")
        
        # 创建垂直布局
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setSpacing(MacOSSpacing.SPACING_M)
        self.vBoxLayout.setContentsMargins(
            MacOSSpacing.MARGIN_CARD,
            MacOSSpacing.MARGIN_CARD,
            MacOSSpacing.MARGIN_CARD,
            MacOSSpacing.MARGIN_CARD
        )
        
        # 创建标题标签
        self.label = QLabel(text, self)
        self.label.setFont(MacOSFonts.get_font(MacOSFonts.FONT_TITLE3, "semibold"))
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        self.vBoxLayout.addWidget(self.label, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.setObjectName(text.replace(' ', '-'))


class MainWindow(FluentWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        t = time.perf_counter()
        
        # 窗口基本设置
        self.setWindowTitle('拼多多 AI 客服助手')
        if not keep_macos_bundle_dock_icon():
            _icon = get_app_icon_path()
            if _icon.exists():
                self.setWindowIcon(QIcon(str(_icon)))
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        if sys.platform == "darwin":
            use_unified_dark_titlebar(self)

        logger.info(f"基础属性初始化：{time.perf_counter()-t:.2f}s")

        # 延迟加载的视图
        self.monitor_view = None
        self.ops_dashboard_view = None
        self.live_chat_view = None
        self.keyword_manager_view = None
        self.user_manager_view = None
        self.log_view = None
        self.knowledge_view = None
        self.settingInterface = None
        self.ai_test_view = None
        self._navigation_ready = False
        self._was_on_chat_page = False
        self._chat_page_index = -1
        self._page_change_timer = QTimer(self)
        self._page_change_timer.setSingleShot(True)
        self._page_change_timer.timeout.connect(self._apply_page_changed)
        
        t = time.perf_counter()
        # 立即初始化导航和窗口
        self.initWindow()
        logger.info(f"initWindow: {time.perf_counter()-t:.2f}s")
        
        # 延迟加载各个视图，让窗口先显示
        QTimer.singleShot(200, self.lazy_load_views)

        from core.human_assist_ui import setup_human_assist_popup

        setup_human_assist_popup(self)

        from core.session_idle_closer import SessionIdleCloserService
        from config import config as _cfg

        _interval_ms = int(
            _cfg.get("chat.session_idle_resolve_check_interval_sec", 60) or 60
        ) * 1000
        self._session_idle_closer = SessionIdleCloserService(
            self, interval_ms=max(30_000, _interval_ms)
        )
        self._session_idle_closer.start()
        QTimer.singleShot(800, self._show_startup_config_hints)
        QTimer.singleShot(1200, self._warm_knowledge_index)
        self._init_system_tray()
        self._force_quit = False
        self._closing = False

    def _init_system_tray(self) -> None:
        """系统托盘：关闭窗口时最小化到托盘。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("系统托盘不可用，跳过托盘初始化")
            return
        app = QApplication.instance()
        if app is not None:
            try:
                from config import get_config

                minimize = bool(get_config("ui.minimize_to_tray_on_close", False))
            except Exception:
                minimize = False
            app.setQuitOnLastWindowClosed(not minimize)

        self._tray_icon = QSystemTrayIcon(self)
        _icon = get_app_icon_path()
        if _icon.exists():
            self._tray_icon.setIcon(QIcon(str(_icon)))
        else:
            self._tray_icon.setIcon(self.windowIcon())
        self._tray_icon.setToolTip("拼多多 AI 客服助手")

        menu = QMenu()
        show_action = menu.addAction("显示主窗口")
        show_action.triggered.connect(self._show_from_tray)
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(self._quit_from_tray)
        self._tray_icon.setContextMenu(menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()
        self._tray_enabled = True

    def _show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        """托盘退出：走主窗口 close()，确保先完成资源清理。"""
        self._force_quit = True
        if getattr(self, "_tray_icon", None):
            self._tray_icon.hide()
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(True)
        self.close()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def notify_user(
        self,
        title: str,
        message: str,
        *,
        tray_only: bool = False,
    ) -> None:
        """不可恢复错误或关键运维事件：托盘气泡 + 可选系统通知。"""
        if getattr(self, "_tray_icon", None) and self._tray_icon.isVisible():
            self._tray_icon.showMessage(
                title,
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                8000,
            )
        if not tray_only:
            try:
                from utils.notify import send_desktop_notification

                send_desktop_notification(title, message)
            except Exception as e:
                logger.debug(f"系统通知跳过: {e}")

    def _show_startup_config_hints(self) -> None:
        """启动后提示关键配置缺失（不阻断已打开的窗口）。"""
        try:
            from utils.config_startup import validate_startup_config

            errors, warnings = validate_startup_config()
            issues = errors + warnings
            if not issues:
                return
            from qfluentwidgets import InfoBar, InfoBarPosition

            InfoBar.warning(
                title="配置提示",
                content=issues[0],
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=8000,
                parent=self,
            )
            for msg in issues[1:3]:
                logger.warning(f"启动配置: {msg}")
            if len(issues) >= 2:
                self.notify_user("配置提示", issues[0], tray_only=True)
        except Exception as e:
            logger.debug(f"启动配置提示跳过: {e}")

    def _warm_knowledge_index(self) -> None:
        """窗口显示后在后台预热知识库索引，不阻塞 UI。"""
        try:
            from Agent.CustomerAgent.agent_knowledge import get_knowledge_manager

            get_knowledge_manager()
        except Exception as e:
            logger.debug("知识库预热跳过: {}", e)

    def initNavigation(self):
        """初始化导航栏 - macOS 风格"""
        # 添加导航项
        self.addSubInterface(
            self.monitor_view, FIF.HOME, '监控面板',
            position=NavigationItemPosition.SCROLL
        )
        
        self.addSubInterface(
            self.live_chat_view, FIF.CHAT, '实时聊天',
            position=NavigationItemPosition.SCROLL
        )

        self.addSubInterface(
            self.ops_dashboard_view, FIF.PIE_SINGLE, '后台看板',
            position=NavigationItemPosition.SCROLL
        )
        
        # 分隔线
        self.navigationInterface.addSeparator()
        
        self.addSubInterface(
            self.knowledge_view, FIF.LIBRARY, '知识库',
            position=NavigationItemPosition.SCROLL
        )
        
        self.addSubInterface(
            self.keyword_manager_view, FIF.TAG, '关键词',
            position=NavigationItemPosition.SCROLL
        )
        
        # 分隔线
        self.navigationInterface.addSeparator()
        
        self.addSubInterface(
            self.user_manager_view, FIF.PEOPLE, '账号管理',
            position=NavigationItemPosition.SCROLL
        )
        
        self.addSubInterface(
            self.log_view, FIF.DOCUMENT, '日志',
            position=NavigationItemPosition.SCROLL
        )
        
        # 底部设置
        self.addSubInterface(
            self.settingInterface, FIF.SETTING, '设置',
            position=NavigationItemPosition.BOTTOM
        )
        
        self.addSubInterface(
            self.ai_test_view, FIF.ROBOT, 'AI 测试',
            position=NavigationItemPosition.BOTTOM
        )
    
    def _ensure_nav_fallback_views(self, message: str = "界面加载失败，请重启应用") -> None:
        """视图加载失败时为所有导航项提供占位页，避免 initNavigation 收到 None。"""
        fallbacks = (
            ("monitor_view", message),
            ("live_chat_view", "实时聊天加载失败"),
            ("ops_dashboard_view", "后台看板加载失败"),
            ("knowledge_view", "知识库加载失败"),
            ("keyword_manager_view", "关键词管理加载失败"),
            ("user_manager_view", "账号管理加载失败"),
            ("log_view", "日志界面加载失败"),
            ("settingInterface", "设置界面加载失败"),
            ("ai_test_view", "AI 测试加载失败"),
        )
        for attr, text in fallbacks:
            if getattr(self, attr, None) is None:
                setattr(self, attr, Widget(text, self))

    def lazy_load_views(self):
        """延迟加载各个视图，提高启动速度"""
        t0 = time.perf_counter()
        try:
            self._lazy_load_views_impl()
        except Exception as e:
            logger.exception(f"延迟加载视图失败: {e}")
            self.notify_user("界面加载失败", "部分功能不可用，请查看日志或重启应用。")
            self._ensure_nav_fallback_views()
            try:
                self.initNavigation()
                self._configure_navigation()
            except Exception as e2:
                logger.error(f"导航初始化失败: {e2}")
        logger.info(f"延迟视图初始化耗时：{time.perf_counter() - t0:.2f}s")

    def _lazy_load_views_impl(self):
        """延迟加载实现（供 lazy_load_views 捕获异常）。"""
        t0 = time.perf_counter()
        
        # 局部按需导入
        t = time.perf_counter()
        from ui.auto_reply_ui import AutoReplyUI
        logger.info(f"import AutoReplyUI: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        from ui.keyword_ui import KeywordManagerWidget
        logger.info(f"import KeywordManagerWidget: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        from ui.user_ui import UserManagerWidget
        logger.info(f"import UserManagerWidget: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        from ui.log_ui import LogUI
        logger.info(f"import LogUI: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        from ui.setting_ui import SettingUI
        logger.info(f"import SettingUI: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        from ui.Knowledge_ui import KnowledgeUI
        logger.info(f"import KnowledgeUI: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        from ui.ai_test_ui import AITestWidget
        logger.info(f"import AITestWidget: {time.perf_counter()-t:.2f}s")
        
        # 创建实例
        t = time.perf_counter()
        self.monitor_view = AutoReplyUI(self)
        logger.info(f"AutoReplyUI: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        from ui.chat_ui import ChatLiveWidget
        self.live_chat_view = ChatLiveWidget(self)
        logger.info(f"ChatLiveWidget: {time.perf_counter()-t:.2f}s")

        t = time.perf_counter()
        try:
            from ui.ops_dashboard import OpsDashboardUI

            self.ops_dashboard_view = OpsDashboardUI(self)
            logger.info(f"OpsDashboardUI: {time.perf_counter()-t:.2f}s")
        except Exception as e:
            logger.error(f"后台看板加载失败（界面将继续）: {e}")
            self.ops_dashboard_view = Widget("后台看板暂不可用\n请重启应用或联系技术支持", self)

        t = time.perf_counter()
        self.keyword_manager_view = KeywordManagerWidget(self)
        logger.info(f"KeywordManagerWidget: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        self.user_manager_view = UserManagerWidget(self)
        logger.info(f"UserManagerWidget: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        self.log_view = LogUI(self)
        logger.info(f"LogUI: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        self.settingInterface = SettingUI(self)
        logger.info(f"SettingUI: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        self.knowledge_view = KnowledgeUI(self)
        logger.info(f"KnowledgeUI: {time.perf_counter()-t:.2f}s")
        
        t = time.perf_counter()
        self.ai_test_view = AITestWidget(self)
        logger.info(f"AITestWidget: {time.perf_counter()-t:.2f}s")
        
        # 初始化导航
        self.initNavigation()
        self._configure_navigation()

        # 连接页面切换信号：仅在导航就绪后、且确认离开聊天页时切回 AI
        try:
            sw = getattr(self, "stackedWidget", None)
            if sw is not None:
                self._chat_page_index = self._index_of_stacked_widget(self.live_chat_view)
                sw.currentChanged.connect(self._on_page_changed)
                logger.info(
                    "✅ 已连接 stackedWidget 页面切换监控 chat_index={}",
                    self._chat_page_index,
                )
            else:
                logger.warning("⚠️ 未找到 stackedWidget，跳过页面切换监控")
        except Exception as e:
            logger.error(f"❌ 连接页面切换信号失败：{e}")
        self._navigation_ready = True
        
        logger.info(f"延迟视图初始化耗时：{time.perf_counter() - t0:.2f}s")

    def _configure_navigation(self) -> None:
        """侧栏 280px、默认展开，符合 SaaS 看板布局。"""
        nav = getattr(self, "navigationInterface", None)
        if nav is None:
            return
        try:
            if hasattr(nav, "setExpandWidth"):
                nav.setExpandWidth(280)
            if hasattr(nav, "setCollapsible"):
                nav.setCollapsible(False)
            if hasattr(nav, "expand"):
                nav.expand(useAni=False)
        except Exception as e:
            logger.debug("导航栏配置跳过: {}", e)

    def _index_of_stacked_widget(self, widget) -> int:
        sw = getattr(self, "stackedWidget", None)
        if sw is None or widget is None:
            return -1
        for i in range(sw.count()):
            if sw.widget(i) is widget:
                return i
        return -1

    def _is_chat_page_active(self) -> bool:
        """当前 stacked 页是否为实时聊天（索引 + widget 双重判断，避免初始化误触发）。"""
        if not getattr(self, "live_chat_view", None):
            return False
        sw = getattr(self, "stackedWidget", None)
        if sw is None:
            return False
        current = sw.currentWidget()
        if current is self.live_chat_view:
            return True
        chat_idx = int(getattr(self, "_chat_page_index", -1))
        return chat_idx >= 0 and sw.currentIndex() == chat_idx

    def _on_page_changed(self, index: int = None) -> None:
        """页面切换去抖：stackedWidget 在 addSubInterface 时会连续触发 currentChanged。"""
        if not getattr(self, "_navigation_ready", False):
            return
        self._pending_page_index = index
        self._page_change_timer.start(80)

    def _apply_page_changed(self) -> None:
        """仅在「从聊天页切到其他页」时恢复 AI 接待，避免同页或初始化误触发。"""
        try:
            if not getattr(self, "live_chat_view", None):
                return
            is_chat = self._is_chat_page_active()
            was_chat = bool(getattr(self, "_was_on_chat_page", False))

            if is_chat:
                self._was_on_chat_page = True
                logger.debug("当前位于实时聊天页面")
                try:
                    timer = getattr(self.live_chat_view, "_input_activity_timer", None)
                    if timer is not None:
                        if timer.isActive():
                            timer.stop()
                        timer.start(10000)
                except Exception as e:
                    logger.debug(f"重启输入框活动定时器失败：{e}")
                return

            if was_chat:
                self._was_on_chat_page = False
                logger.info("离开实时聊天页面，自动切回 AI 接待")
                try:
                    self.live_chat_view._restore_ai_for_current_if_manual()
                except Exception as e:
                    logger.debug(f"切换 AI 模式失败：{e}")
            else:
                self._was_on_chat_page = False

        except Exception as e:
            logger.error(f"页面切换处理失败：{e}")
    
    def initWindow(self):
        """初始化窗口 - macOS 风格，强制深色标题栏"""
        self.setWindowTitle('拼多多 AI 客服助手')
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if sys.platform == "darwin":
            apply_dark_titlebar_chrome(self)
            QTimer.singleShot(50, lambda: apply_dark_titlebar_chrome(self))

    def _stop_ui_timers(self) -> None:
        closer = getattr(self, "_session_idle_closer", None)
        if closer is not None:
            try:
                closer.stop()
            except Exception as e:
                logger.debug("停止会话空闲检测: {}", e)

    def _release_tray(self) -> None:
        """退出前移除托盘图标；否则 Qt 会认为应用仍在运行。"""
        icon = getattr(self, "_tray_icon", None)
        if icon is None:
            return
        try:
            icon.hide()
            icon.setVisible(False)
            icon.deleteLater()
        except Exception as e:
            logger.debug("移除托盘图标: {}", e)
        self._tray_icon = None
        self._tray_enabled = False

    def _quit_application(self) -> None:
        """显式结束 Qt 事件循环（托盘存在时关窗不会自动 quit）。"""
        self._release_tray()
        app = QApplication.instance()
        if app is None:
            return
        app.setQuitOnLastWindowClosed(True)
        app.quit()

        def _force_exit_if_stuck() -> None:
            time.sleep(2.0)
            os._exit(0)

        threading.Thread(
            target=_force_exit_if_stuck, daemon=True, name="QuitWatchdog"
        ).start()

    def closeEvent(self, event: QCloseEvent) -> None:
        minimize = False
        try:
            from config import get_config

            minimize = bool(get_config("ui.minimize_to_tray_on_close", False))
        except Exception:
            minimize = False

        if (
            not getattr(self, "_force_quit", False)
            and minimize
            and getattr(self, "_tray_enabled", False)
            and getattr(self, "_tray_icon", None)
            and self._tray_icon.isVisible()
        ):
            event.ignore()
            self.hide()
            self._tray_icon.showMessage(
                "客服助手仍在运行",
                "程序已最小化到托盘，右键图标可退出。",
                QSystemTrayIcon.MessageIcon.Information,
                4000,
            )
            return

        if not getattr(self, "_force_quit", False):
            if not confirm_action(
                self,
                "确认退出",
                "确定要退出客服助手吗？\n正在运行的账号连接与自动回复将停止。",
                confirm_text="退出",
                cancel_text="取消",
                destructive=True,
            ):
                event.ignore()
                return

        if getattr(self, "_closing", False):
            event.accept()
            super().closeEvent(event)
            return

        self._closing = True
        event.accept()
        self._stop_ui_timers()
        self._release_tray()
        app = QApplication.instance()
        if app is not None:
            app.setQuitOnLastWindowClosed(True)

        try:
            from core.app_shutdown import shutdown_application

            shutdown_application()
        except Exception as e:
            logger.warning("退出清理失败，继续关闭窗口: {}", e)
            run_stop_all_services_sync(SHUTDOWN_TIMEOUT_SEC)

        super().closeEvent(event)
        self._quit_application()
