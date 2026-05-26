"""
拼多多 AI 客服助手 - 主界面
macOS 风格设计
"""

import sys
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget, QSplitter
from PyQt6.QtGui import QFont, QIcon
from qfluentwidgets import FluentWindow, NavigationItemPosition
from qfluentwidgets import FluentIcon as FIF
import time

from ui.dark_apple_style import apply_dark_apple_style
from ui.macos_design import MacOSFonts, MacOSSpacing
from utils.logger_loguru import get_logger
from utils.runtime_path import get_app_icon_path

logger = get_logger("MainWindow")


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
        _icon = get_app_icon_path()
        if _icon.exists():
            self.setWindowIcon(QIcon(str(_icon)))
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        logger.info(f"基础属性初始化：{time.perf_counter()-t:.2f}s")
        
        # 应用深色 Apple 风格设计系统
        apply_dark_apple_style(QApplication.instance())
        
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
        
        t = time.perf_counter()
        # 立即初始化导航和窗口
        self.initWindow()
        logger.info(f"initWindow: {time.perf_counter()-t:.2f}s")
        
        # 延迟加载各个视图，让窗口先显示
        QTimer.singleShot(200, self.lazy_load_views)
    
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
            self.ops_dashboard_view, FIF.PIE_SINGLE, '运营看板',
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
    
    def lazy_load_views(self):
        """延迟加载各个视图，提高启动速度"""
        t0 = time.perf_counter()
        try:
            self._lazy_load_views_impl()
        except Exception as e:
            logger.exception(f"延迟加载视图失败: {e}")
            if self.monitor_view is None:
                self.monitor_view = Widget("界面加载失败，请重启应用", self)
            if self.live_chat_view is None:
                self.live_chat_view = Widget("实时聊天加载失败", self)
            if self.ops_dashboard_view is None:
                self.ops_dashboard_view = Widget("运营看板加载失败", self)
            try:
                self.initNavigation()
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
            logger.error(f"运营看板加载失败（界面将继续）: {e}")
            self.ops_dashboard_view = Widget("运营看板暂不可用\n请重启应用或联系技术支持", self)

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
        
        # 连接页面切换信号，监控是否离开聊天窗口
        # 使用 stackedWidget 的 currentChanged 信号（兼容不同版本的 PyQt-Fluent-Widgets）
        try:
            if hasattr(self, 'stackedWidget') and self.stackedWidget:
                self.stackedWidget.currentChanged.connect(self._on_page_changed)
                logger.info("✅ 已连接 stackedWidget 页面切换监控")
            elif hasattr(self.navigationInterface, 'panelLayout'):
                self.navigationInterface.panelLayout.currentChanged.connect(self._on_page_changed)
                logger.info("✅ 已连接 panelLayout 页面切换监控")
            else:
                logger.warning("⚠️ 未找到可用的页面切换信号")
        except Exception as e:
            logger.error(f"❌ 连接页面切换信号失败：{e}")
        
        logger.info(f"延迟视图初始化耗时：{time.perf_counter() - t0:.2f}s")

    def _on_page_changed(self, index: int = None):
        """页面切换时的处理 - 离开聊天窗口时自动切回 AI 接待"""
        try:
            if not self.live_chat_view:
                return

            sw = getattr(self, "stackedWidget", None)
            if sw is None:
                return

            if index is None:
                index = sw.currentIndex()
            current_widget = sw.widget(index) if index >= 0 else sw.currentWidget()
            is_chat_page = current_widget is self.live_chat_view

            if not is_chat_page:
                logger.info("检测到离开实时聊天页面，自动切回 AI 接待")
                try:
                    self.live_chat_view._restore_ai_for_current_if_manual()
                    logger.info("已自动切回 AI 接待模式")
                except Exception as e:
                    logger.debug(f"切换 AI 模式失败：{e}")
            else:
                logger.debug("切换到实时聊天页面")
                try:
                    timer = getattr(self.live_chat_view, "_input_activity_timer", None)
                    if timer is not None:
                        if timer.isActive():
                            timer.stop()
                        timer.start(10000)
                except Exception as e:
                    logger.debug(f"重启输入框活动定时器失败：{e}")

        except Exception as e:
            logger.error(f"页面切换处理失败：{e}")
    
    def initWindow(self):
        """初始化窗口 - macOS 风格，强制深色标题栏"""
        # 设置窗口属性
        self.setWindowTitle('拼多多 AI 客服助手')
        self.setMinimumSize(1200, 800)
        self.resize(1400, 900)
        
        # macOS 强制深色标题栏（非 macOS 或 windowHandle 未就绪时会失败，可忽略）
        try:
            wh = self.windowHandle()
            if wh is not None:
                wh.setProperty("NSAppearanceName", "NSAppearanceNameDarkAqua")
        except Exception as e:
            logger.debug("设置 macOS 外观失败：{}", e)

        # 应用 macOS 设计 (已在 __init__ 中应用)
