#自动回复界面

import asyncio
from PyQt6.QtCore import Qt, pyqtSignal, QThread, pyqtSignal as Signal, QTimer
from PyQt6.QtWidgets import (QFrame, QHBoxLayout, QVBoxLayout, QWidget, QSizePolicy, QLabel,
                            QInputDialog, QMessageBox, QComboBox, QDialog, QFormLayout)
from PyQt6.QtGui import QFont, QIcon, QPixmap
from qfluentwidgets import (
    CardWidget,
    SubtitleLabel,
    CaptionLabel,
    BodyLabel,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
    InfoBadge,
    ScrollArea,
    FluentIcon as FIF,
    InfoBar,
    InfoBarPosition,
)
from database.db_manager import db_manager
from utils.logger_loguru import get_logger
from utils.dialogs import confirm_action
from Channel.pinduoduo.utils.API.Set_up_online import AccountMonitor
from ui.logo_loader_thread import LogoLoaderThread
from typing import Dict, Optional
import requests


class AutoReplyManager:
    """自动回复管理器 - 管理所有账号的自动回复连接"""
    
    def __init__(self):
        self.running_accounts: Dict[str, 'AutoReplyThread'] = {}  # 正在运行的账号线程
        self.logger = get_logger()
    
    def start_auto_reply(self, account_data: dict) -> bool:
        """启动账号自动回复"""
        try:
            account_key = f"{account_data['channel_name']}_{account_data['shop_id']}_{account_data['username']}"
            
            # 检查是否已经在运行
            if account_key in self.running_accounts:
                self.logger.warning(f"账号 {account_data['username']} 自动回复已在运行")
                return False
            
            # 创建并启动自动回复线程
            thread = AutoReplyThread(account_data)
            self.running_accounts[account_key] = thread
            
            # 连接信号
            thread.connection_success.connect(lambda: self._on_connection_success(account_key))
            thread.connection_failed.connect(lambda error: self._on_connection_failed(account_key, error))
            thread.finished.connect(lambda: self._on_thread_finished(account_key))
            
            # 启动线程
            thread.start()
            return True
            
        except Exception as e:
            self.logger.error(f"启动自动回复失败: {str(e)}")
            return False
    
    def stop_auto_reply(self, account_data: dict) -> bool:
        """停止账号自动回复"""
        try:
            account_key = f"{account_data['channel_name']}_{account_data['shop_id']}_{account_data['username']}"
            
            if account_key not in self.running_accounts:
                self.logger.warning(f"账号 {account_data['username']} 自动回复未在运行")
                return False
            
            # 停止线程
            thread = self.running_accounts[account_key]
            thread.stop()
            
            # 等待线程结束后再从列表中移除
            if thread.isRunning():
                thread.wait(5000)  # 最多等待5秒
            
            # 从运行列表中移除
            if account_key in self.running_accounts:
                del self.running_accounts[account_key]
            return True
            
        except Exception as e:
            self.logger.error(f"停止自动回复失败: {str(e)}")
            return False
    
    def is_running(self, account_data: dict) -> bool:
        """检查账号是否正在自动回复（改进版本）"""
        try:
            account_key = f"{account_data['channel_name']}_{account_data['shop_id']}_{account_data['username']}"

            # 检查是否在运行列表中
            if account_key not in self.running_accounts:
                return False

            thread = self.running_accounts[account_key]

            # 检查线程是否存在且正在运行
            if not thread or not hasattr(thread, 'isRunning'):
                # 清理无效的线程引用，但不要过于频繁地清理
                self._cleanup_stale_thread(account_key)
                return False

            # 检查线程是否正在运行
            is_thread_running = thread.isRunning()

            # 如果线程已停止，清理引用
            if not is_thread_running:
                self._cleanup_stale_thread(account_key)
                return False

            # 线程正在运行，认为账号正在自动回复
            return True

        except Exception as e:
            self.logger.error(f"检查账号运行状态失败: {str(e)}")
            return False

    def _cleanup_stale_thread(self, account_key: str):
        """清理已停止的线程引用"""
        try:
            if account_key in self.running_accounts:
                thread = self.running_accounts[account_key]
                # 只有在线程确实停止后才清理
                if hasattr(thread, 'isRunning') and not thread.isRunning():
                    del self.running_accounts[account_key]
                    self.logger.debug(f"清理已停止的线程引用: {account_key}")
        except Exception as e:
            self.logger.error(f"清理线程引用失败: {account_key}, {e}")
    
    def _on_connection_success(self, account_key: str):
        """连接成功回调"""
        self.logger.debug(f"账号 {account_key} 自动回复连接成功")
    
    def _on_connection_failed(self, account_key: str, error: str):
        """连接失败回调"""
        self.logger.error(f"账号 {account_key} 自动回复连接失败: {error}")
        # 清理失败的线程
        if account_key in self.running_accounts:
            del self.running_accounts[account_key]
    
    def _on_thread_finished(self, account_key: str):
        """线程结束回调"""
        self.logger.debug(f"账号 {account_key} 自动回复线程已结束")
        # 清理线程引用
        if account_key in self.running_accounts:
            del self.running_accounts[account_key]
    
    def get_running_count(self) -> int:
        """获取正在运行的账号数量"""
        return len(self.running_accounts)
    
    def stop_all(self):
        """停止所有自动回复"""
        try:
            # 停止所有正在运行的线程
            for account_key, thread in self.running_accounts.items():
                if thread.is_running():
                    thread.stop()
            
            # 等待所有线程结束
            for thread in self.running_accounts.values():
                thread.wait(5000) # 等待5秒
            
            self.running_accounts.clear()
            self.logger.info("所有自动回复任务已停止")
            
        except Exception as e:
            self.logger.error(f"停止所有自动回复失败: {e}")


class AutoReplyThread(QThread):
    """自动回复线程 - 每个账号独立的WebSocket连接线程"""
    
    connection_success = pyqtSignal()  # 连接成功信号
    connection_failed = pyqtSignal(str)  # 连接失败信号
    
    def __init__(self, account_data: dict):
        super().__init__()
        self.account_data = account_data
        self.channel = None
        self.logger = get_logger("AutoReplyThread")
        
    def run(self):
        """启动后端 PDDChannel 引擎"""
        from Channel.pinduoduo.pdd_chnnel import PDDChannel
        
        try:
            # 为当前线程创建并设置新的事件循环
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            
            # 创建 PDDChannel 实例
            self.channel = PDDChannel()
            
            # 定义成功和失败的回调函数
            def on_success():
                self.connection_success.emit()

            def on_failure(error_msg):
                self.connection_failed.emit(error_msg)

            # 启动引擎，并传递回调
            task = self.loop.create_task(
                self.channel.start_account(
                    shop_id=self.account_data['shop_id'],
                    user_id=self.account_data['user_id'],
                    on_success=on_success,
                    on_failure=on_failure
                )
            )
            
            # 保持事件循环运行，直到显式停止
            self.loop.run_forever()

        except Exception as e:
            self.logger.error(f"自动回复线程启动失败: {e}")
            self.connection_failed.emit(str(e))
        finally:
            if self.loop.is_running():
                self.loop.stop()
            self.loop.close()

    def stop(self):
        """停止后端引擎"""
        try:
            if self.channel:
                self.channel.request_stop()

            # 停止事件循环（如果存在）
            if hasattr(self, 'loop') and self.loop:
                if self.loop.is_running():
                    for task in asyncio.all_tasks(self.loop):
                        if not task.done():
                            task.cancel()
                    self.loop.call_soon_threadsafe(self.loop.stop)

        except Exception as e:
            self.logger.error(f"停止自动回复线程失败: {e}")
        
    def is_running(self) -> bool:
        """检查线程是否在运行"""
        # 实际的运行状态由 PDDChannel 内部管理，这里仅表示线程是否已启动
        return self.isRunning()


# 全局自动回复管理器实例
auto_reply_manager = AutoReplyManager()


class SetStatusThread(QThread):
    """设置账号状态的线程"""
    
    status_set_success = pyqtSignal(dict, int)  # 设置成功信号
    status_set_failed = pyqtSignal(dict, str)   # 设置失败信号
    
    def __init__(self, account_data: dict, target_status: int):
        super().__init__()
        self.account_data = account_data
        self.target_status = target_status
        self.logger = get_logger()
    def run(self):
        """在后台线程中执行状态更新"""
        try:
            # 1. 调用API设置平台状态
            cookies = self.account_data.get("cookies")
            if not cookies:
                raise ValueError("账号缺少cookies，无法设置状态")

            account_monitor = AccountMonitor(cookies)
            
            api_success = account_monitor.set_csstatus(self.target_status)

            if not api_success:
                # API调用失败
                self.status_set_failed.emit(self.account_data, "平台状态设置失败")
                return

            # 2. 更新数据库状态
            db_success = db_manager.update_account_status(
                channel_name=self.account_data["channel_name"],
                shop_id=self.account_data["shop_id"],
                user_id=self.account_data["user_id"],
                status=self.target_status
            )
            
            if db_success:
                # 发射成功信号
                self.status_set_success.emit(self.account_data, self.target_status)
            else:
                # 发射失败信号
                self.status_set_failed.emit(self.account_data, "数据库状态更新失败")
                
        except KeyError:
            # 如果缺少 'user_id' 等关键信息
            self.status_set_failed.emit(self.account_data, "账号数据不完整，无法设置状态")
        except Exception as e:
            # 其他异常
            self.status_set_failed.emit(self.account_data, str(e))


class AutoReplyCard(CardWidget):
    """自动回复卡片组件"""
    
    # 定义信号
    online_clicked = pyqtSignal(dict)  # 上线按钮点击信号
    offline_clicked = pyqtSignal(dict)  # 离线按钮点击信号
    auto_reply_clicked = pyqtSignal(dict)  # 开始自动回复按钮点击信号
    
    def __init__(self, account_data: dict, parent=None):
        super().__init__(parent)
        self.account_data = account_data
        self.shop_id = account_data.get("shop_id", "")
        self.shop_name = account_data.get("shop_name", "")
        self.shop_logo = account_data.get("shop_logo")
        self.account_name = account_data.get("username", "")
        self.platform = account_data.get("channel_name", "")
        self.status = self.getStatusText(account_data.get("status", 0))
        self.auto_reply_status = False  # 自动回复状态
        self.setupUI()
        self.connectSignals()
        self.loadLogo()
        
    def getStatusText(self, status_code: int) -> str:
        """将状态码转换为文本"""
        status_map = {
            0: "休息",
            1: "在线", 
            3: "离线",
            None: "未验证"
        }
        return status_map.get(status_code, "未知")
        
    def setupUI(self):
        """设置卡片UI"""
        # 设置卡片样式
        self.setFixedHeight(120)
        # 主布局
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 15, 20, 15)
        layout.setSpacing(20)
        
        # Logo
        logo_widget = self.createLogoWidget()
        
        # 左侧信息区域
        info_widget = self.createInfoWidget()
        
        # 右侧操作区域
        self.action_widget = self.createActionWidget()
        
        # 添加到主布局
        layout.addWidget(logo_widget)
        layout.addWidget(info_widget, 1)
        layout.addWidget(self.action_widget, 0)
    
    def createLogoWidget(self):
        """创建Logo显示区域"""
        self.logo_label = QLabel()
        self.logo_label.setFixedSize(65, 65)
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo_label.setStyleSheet("border-radius: 30px; border: 1px solid #2A3140; background-color: #1B1F2A;")
        self.logo_label.setText("加载中...")
        return self.logo_label
        
    def createInfoWidget(self):
        """创建信息显示区域"""
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setSpacing(8)
        info_layout.setContentsMargins(0, 0, 0, 0)

        # 第一行：店铺名称 + 平台标签
        first_row = QWidget()
        first_row_layout = QHBoxLayout(first_row)
        first_row_layout.setContentsMargins(0, 0, 0, 0)
        first_row_layout.setSpacing(10)
        
        # 店铺名称
        shop_name_label = StrongBodyLabel(self.shop_name)
        shop_name_label.setFont(QFont("Microsoft YaHei", 14, QFont.Weight.Bold))
        shop_name_label.setStyleSheet("color: #F2F2F7;")
        
        # 平台标签
        platform_badge = InfoBadge.info(self.platform, self)
        platform_badge.setFont(QFont("Microsoft YaHei", 9))

        first_row_layout.addWidget(shop_name_label)
        first_row_layout.addWidget(platform_badge)
        first_row_layout.addStretch()
        
        # 第二行：店铺ID
        second_row = self.createInfoRow("店铺ID:", self.shop_id)
        
        # 第三行：账号名称
        third_row = self.createInfoRow("账号:", self.account_name)
        
        # 添加到布局
        info_layout.addWidget(first_row)
        info_layout.addWidget(second_row)
        info_layout.addWidget(third_row)
        info_layout.addStretch()
        
        return info_widget
    
    def createInfoRow(self, label_text: str, value_text: str):
        """创建信息行"""
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)
        
        # 标签
        label = CaptionLabel(label_text)
        label.setStyleSheet("color: #9EA6B8; font-weight: 500;")
        label.setFixedWidth(60)
        
        # 值
        value = BodyLabel(value_text)
        value.setStyleSheet("color: #F2F2F7;")
        
        row_layout.addWidget(label)
        row_layout.addWidget(value)
        row_layout.addStretch()
        
        return row_widget
    
    def createActionWidget(self):
        """创建操作区域"""
        action_widget = QWidget()
        action_layout = QVBoxLayout(action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(10)
        action_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # 状态标签
        status_badge = self.createStatusBadge()
        
        # 操作按钮容器
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(8)
        
        # 上线按钮
        self.online_btn = PushButton("上线")
        self.online_btn.setIcon(FIF.PLAY)
        self.online_btn.setFixedSize(100, 32)
        
        # 离线按钮
        self.offline_btn = PushButton("离线")
        self.offline_btn.setIcon(FIF.PAUSE)
        self.offline_btn.setFixedSize(100, 32)
       
        # 自动回复按钮
        self.auto_reply_btn = PrimaryPushButton("开始回复")
        self.auto_reply_btn.setIcon(FIF.ROBOT)
        self.auto_reply_btn.setFixedSize(110, 32)

        buttons_layout.addWidget(self.online_btn)
        buttons_layout.addWidget(self.offline_btn)
        buttons_layout.addWidget(self.auto_reply_btn)
        
        # 添加到操作布局
        action_layout.addWidget(status_badge, 0, Qt.AlignmentFlag.AlignRight)
        action_layout.addWidget(buttons_widget)
        action_layout.addStretch()
        
        return action_widget
    
    def createStatusBadge(self):
        """创建状态标签"""
        if self.status == "在线":
            status_badge = InfoBadge.success("● 在线", self)
        elif self.status == "离线":
            status_badge = InfoBadge.error("● 离线", self)
        elif self.status == "未验证":
            status_badge = InfoBadge.warning("● 未验证", self)
        elif self.status == "休息":
            status_badge = InfoBadge.info("● 休息", self)
        else:
            status_badge = InfoBadge.info(f"● {self.status}", self)
        
        status_badge.setFont(QFont("Microsoft YaHei", 9, QFont.Weight.Bold))
        return status_badge
    
    def connectSignals(self):
        """连接信号"""
        self.online_btn.clicked.connect(lambda: self.online_clicked.emit(self.account_data))
        self.offline_btn.clicked.connect(lambda: self.offline_clicked.emit(self.account_data))
        self.auto_reply_btn.clicked.connect(lambda: self.auto_reply_clicked.emit(self.account_data))
    
    def setButtonsEnabled(self, enabled: bool):
        """设置按钮是否可用"""
        self.online_btn.setEnabled(enabled)
        self.offline_btn.setEnabled(enabled)
        
    def setButtonLoading(self, button_type: str, loading: bool):
        """设置按钮加载状态"""
        if button_type == "online":
            if loading:
                self.online_btn.setText("设置中...")
                self.online_btn.setEnabled(False)
            else:
                self.online_btn.setText("上线")
                self.online_btn.setEnabled(True)
        elif button_type == "offline":
            if loading:
                self.offline_btn.setText("设置中...")
                self.offline_btn.setEnabled(False)
            else:
                self.offline_btn.setText("离线")
                self.offline_btn.setEnabled(True)
    
    def setAutoReplyStatus(self, is_running: bool):
        """设置自动回复状态"""
        self.auto_reply_status = is_running
        if is_running:
            self.auto_reply_btn.setText("停止回复")
            self.auto_reply_btn.setIcon(FIF.CANCEL)
        else:
            self.auto_reply_btn.setText("开始回复")
            self.auto_reply_btn.setIcon(FIF.ROBOT)
    
    def updateStatus(self, new_status: int):
        """更新账号状态"""
        self.account_data["status"] = new_status
        self.status = self.getStatusText(new_status)
        
        # 重新创建状态标签
        old_badge = self.action_widget.layout().itemAt(0).widget()
        if old_badge:
            old_badge.deleteLater()
            
        new_badge = self.createStatusBadge()
        self.action_widget.layout().insertWidget(0, new_badge, 0, Qt.AlignmentFlag.AlignRight)

    def loadLogo(self):
        """异步加载Logo"""
        if self.shop_logo:
            def _start():
                self.logo_loader_thread = LogoLoaderThread(self.shop_logo)
                self.logo_loader_thread.logo_loaded.connect(self.setLogo)
                self.logo_loader_thread.start()
            QTimer.singleShot(200, _start)
        else:
            self.logo_label.setText("无Logo")

    def setLogo(self, pixmap: QPixmap):
        """设置Logo"""
        if not pixmap.isNull():
            self.logo_label.setPixmap(pixmap)
        else:
            self.logo_label.setText("加载失败")


class AutoReplyUI(QFrame):
    """自动回复主界面"""
    
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self.logger = get_logger()  # 初始化logger（必须在其他操作之前）
        self.accounts_data = []  # 存储账号数据
        self._loaded_once = False
        self.setupUI()
        QTimer.singleShot(300, self._maybeLoadOnShow)

        # 设置定时器定期更新统计信息
        self.stats_timer = QTimer()
        self.stats_timer.timeout.connect(self.updateStats)
        self.stats_timer.start(5000)  # 每5秒更新一次

        # 设置定时器定期同步自动回复状态（减少检查频率，避免过度同步）
        self.sync_timer = QTimer()
        self.sync_timer.timeout.connect(self._sync_auto_reply_status)
        self.sync_timer.start(10000)  # 每10秒同步一次状态（减少频率）

    @staticmethod
    def _account_match_key(account_data: dict) -> tuple:
        return (
            str(account_data.get("channel_name") or ""),
            str(account_data.get("shop_id") or ""),
            str(account_data.get("user_id") or ""),
        )

    def _toast(
        self,
        title: str,
        content: str = "",
        *,
        level: str = "success",
        duration: int = 2800,
    ) -> None:
        """顶部轻提示（上线/离线/自动回复操作反馈）。"""
        show = getattr(InfoBar, level, InfoBar.info)
        try:
            show(
                title=title,
                content=content,
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=duration,
                parent=self.window() or self,
            )
        except Exception as e:
            self.logger.debug(f"InfoBar 显示失败: {e}")

    def closeEvent(self, event):
        """窗口关闭时清理定时器"""
        try:
            if hasattr(self, 'stats_timer'):
                self.stats_timer.stop()
            if hasattr(self, 'sync_timer'):
                self.sync_timer.stop()
            event.accept()
        except Exception as e:
            self.logger.error(f"清理定时器失败: {e}")
            event.accept()
    
    def showEvent(self, event):
        super().showEvent(event)
        self._maybeLoadOnShow()
    
    def _maybeLoadOnShow(self):
        if not self._loaded_once and self.isVisible():
            self._loaded_once = True
            self.loadAccountsFromDB()

    def setupUI(self):
        """设置主界面UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(25)
        
        # 创建头部区域
        header_widget = self.createHeaderWidget()
        
        # 创建内容区域
        content_widget = self.createContentWidget()
        
        # 连接按钮信号
        self.refresh_btn.clicked.connect(self.reloadAccounts)
        self.start_all_btn.clicked.connect(self.onStartAllAutoReply)
        self.stop_all_btn.clicked.connect(self.stopAllAutoReply)
        
        # 添加到主布局
        main_layout.addWidget(header_widget)
        main_layout.addWidget(content_widget, 1)
        
        # 设置对象名
        self.setObjectName("自动回复")
    
    def createHeaderWidget(self):
        """创建头部区域"""
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)
        
        # 标题
        title_label = SubtitleLabel("自动回复管理")
        # 统计信息
        self.stats_label = CaptionLabel("共 0 个账号")
        # 运行状态统计
        self.running_stats_label = CaptionLabel("运行中: 0 个")
        self.running_stats_label.setStyleSheet("color: #32D74B; font-weight: bold;")
        
        # 左侧标题区域
        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_layout.addWidget(title_label)
        title_layout.addWidget(self.stats_label)
        title_layout.addWidget(self.running_stats_label)
        
        # 刷新按钮
        self.refresh_btn = PushButton("刷新")
        self.refresh_btn.setIcon(FIF.UPDATE)
        self.refresh_btn.setFixedSize(120, 40)

        # 开始所有按钮
        self.start_all_btn = PrimaryPushButton("开始所有")
        self.start_all_btn.setIcon(FIF.PLAY_SOLID)
        self.start_all_btn.setFixedSize(120, 40)
        
        # 停止所有按钮
        self.stop_all_btn = PushButton("停止所有")
        self.stop_all_btn.setIcon(FIF.CANCEL)
        self.stop_all_btn.setFixedSize(120, 40)
        
        # 按钮容器
        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)
        buttons_layout.addWidget(self.refresh_btn)
        buttons_layout.addWidget(self.start_all_btn)
        buttons_layout.addWidget(self.stop_all_btn)
        
        # 添加到头部布局
        header_layout.addWidget(title_area)
        header_layout.addStretch()
        header_layout.addWidget(buttons_widget)
        
        return header_widget
    
    def createContentWidget(self):
        """创建内容区域"""
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # 滚动区域
        self.scroll_area = ScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # 去除边框
        self.scroll_area.setStyleSheet("""
            ScrollArea {
                border: none;
                background-color: transparent;
            }
        """)
        
        # 账号列表容器
        self.accounts_container = QWidget()
        self.accounts_layout = QVBoxLayout(self.accounts_container)
        self.accounts_layout.setSpacing(15)  # 设置账号卡片之间的间距
        self.accounts_layout.setContentsMargins(20, 20, 20, 20)  # 设置容器内边距
        self.accounts_layout.setAlignment(Qt.AlignmentFlag.AlignTop)  # 顶部对齐
        
        # 设置容器样式，去除边框
        self.accounts_container.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border: none;
            }
        """)
        
        # 设置滚动区域内容
        self.scroll_area.setWidget(self.accounts_container)
        
        # 添加到内容布局
        content_layout.addWidget(self.scroll_area)
        
        return content_widget
    
    def loadAccountsFromDB(self):
        """从数据库加载账号数据"""
        try:
            self.accounts_data.clear()  # 使用 clear() 替代重新赋值
            
            channels = db_manager.get_all_channels()
            
            for channel in channels:
                channel_name = channel["channel_name"]
                
                # 获取该渠道下的所有店铺
                shops = db_manager.get_shops_by_channel(channel_name)
                
                for shop in shops:
                    shop_id = shop["shop_id"]
                    
                    # 获取该店铺下的所有账号
                    accounts = db_manager.get_accounts_by_shop(channel_name, shop_id)
                    
                    for account in accounts:
                        account_data = {
                            "channel_name": channel_name,
                            "shop_id": shop_id,
                            "shop_name": shop["shop_name"],
                            "shop_logo": shop.get("shop_logo"),
                            "username": account["username"],
                            "password": account["password"],
                            "status": account["status"],
                            "user_id": account["user_id"],
                            "cookies": account["cookies"]
                        }
                        self.accounts_data.append(account_data)
                        
            self.refreshAccountList()
            
        except Exception as e:
            self.logger.error(f"加载账号数据失败: {e}")
    
    def refreshAccountList(self):
        """刷新账号列表"""
        # 清空现有卡片
        self.clearAccountList()

        # 添加账号卡片
        for account_data in self.accounts_data:
            account_card = AutoReplyCard(account_data)

            # 连接卡片信号
            account_card.online_clicked.connect(self.onAccountOnline)
            account_card.offline_clicked.connect(self.onAccountOffline)
            account_card.auto_reply_clicked.connect(self.onAutoReplyToggle)

            # 检查并设置自动回复状态（改进的状态检查）
            account_key = f"{account_data['channel_name']}_{account_data['shop_id']}_{account_data['username']}"
            is_running = auto_reply_manager.is_running(account_data)

            # 记录状态检查的调试信息
            self.logger.debug(f"账号 {account_data['username']} 状态检查: key={account_key}, running={is_running}")

            # 设置自动回复状态
            account_card.setAutoReplyStatus(is_running)

            self.accounts_layout.addWidget(account_card)

        # 添加弹性空间
        self.accounts_layout.addStretch()

        # 更新统计信息
        self.updateStats()

        # 额外的状态同步：延迟一点时间再次检查并更新
        QTimer.singleShot(2000, self._sync_auto_reply_status)  # 增加延迟时间，让初始化更稳定
    
    def clearAccountList(self):
        """清空账号列表"""
        while self.accounts_layout.count():
            child = self.accounts_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
    
    def updateStats(self):
        """更新统计信息"""
        count = len(self.accounts_data)
        running_count = auto_reply_manager.get_running_count()
        self.stats_label.setText(f"共 {count} 个账号")
        self.running_stats_label.setText(f"运行中: {running_count} 个")

    def _sync_auto_reply_status(self):
        """同步自动回复状态（优化版本，减少误判）"""
        try:
            updated_count = 0

            for i in range(self.accounts_layout.count() - 1):  # -1 因为最后一个是stretch
                widget = self.accounts_layout.itemAt(i).widget()
                if isinstance(widget, AutoReplyCard):
                    # 重新检查实际的运行状态
                    is_running = auto_reply_manager.is_running(widget.account_data)
                    current_status = widget.auto_reply_status

                    # 只有在状态真正不一致时才更新UI
                    if is_running != current_status:
                        # 额外检查：如果是运行中变为停止，需要确认线程真的停止了
                        if current_status and not is_running:
                            # 再次检查，确保不是误判
                            account_key = f"{widget.account_data['channel_name']}_{widget.account_data['shop_id']}_{widget.account_data['username']}"
                            if account_key in auto_reply_manager.running_accounts:
                                thread = auto_reply_manager.running_accounts[account_key]
                                if hasattr(thread, 'isRunning') and thread.isRunning():
                                    # 线程还在运行，不更新状态
                                    continue

                        self.logger.info(f"同步状态: {widget.account_data['username']} 从 {current_status} 更新为 {is_running}")
                        widget.setAutoReplyStatus(is_running)
                        updated_count += 1

            if updated_count > 0:
                self.logger.info(f"状态同步完成，更新了 {updated_count} 个账号的状态")
                # 再次更新统计信息
                self.updateStats()

        except Exception as e:
            self.logger.error(f"同步自动回复状态失败: {str(e)}")
    
    def reloadAccounts(self):
        """重新加载账号"""
        self.loadAccountsFromDB()
    
    def onStartAllAutoReply(self):
        """开始所有符合条件的账号的自动回复"""
        try:
            # 1. 筛选出可以启动的账号
            eligible_accounts = [
                acc_data for acc_data in self.accounts_data
                if acc_data.get("status") == 1 and not auto_reply_manager.is_running(acc_data)
            ]

            # 2. 如果没有可启动的账号，提示用户
            if not eligible_accounts:
                QMessageBox.information(self, "提示", "没有符合条件的账号可以启动自动回复。\n\n(需要账号状态为'在线'且当前未在回复中)")
                return

            # 3. 确认对话框
            if not confirm_action(
                self,
                "确认开始",
                f"找到 {len(eligible_accounts)} 个可启动的账号。确定要全部开始自动回复吗？",
                confirm_text="开始全部",
                cancel_text="取消",
            ):
                return

            # 4. 循环启动
            started_count = 0
            for account_data in eligible_accounts:
                success = auto_reply_manager.start_auto_reply(account_data)
                if success:
                    started_count += 1
                    # 连接信号以处理连接成功/失败的回调
                    self._connect_auto_reply_signals(account_data)

            # 5. 更新UI并显示结果
            self._update_all_cards_auto_reply_status()
            self.updateStats()

            QMessageBox.information(self, "操作完成", f"已成功为 {started_count} / {len(eligible_accounts)} 个账号启动自动回复。")

        except Exception as e:
            self.logger.error(f"开始所有自动回复失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"开始所有自动回复失败：{str(e)}")

    def stopAllAutoReply(self):
        """停止所有自动回复"""
        try:
            running_count = auto_reply_manager.get_running_count()
            
            if running_count == 0:
                QMessageBox.information(self, "提示", "当前没有正在运行的自动回复")
                return
            
            # 确认对话框
            if confirm_action(
                self,
                "确认停止",
                f"确定要停止所有 {running_count} 个正在运行的自动回复吗？",
                confirm_text="停止全部",
                cancel_text="取消",
                destructive=True,
            ):
                # 停止所有自动回复
                auto_reply_manager.stop_all()
                
                # 更新所有卡片状态
                self._update_all_cards_auto_reply_status()
                
                # 更新统计信息
                self.updateStats()
                
                QMessageBox.information(self, "成功", "已停止所有自动回复")
                
        except Exception as e:
            self.logger.error(f"停止所有自动回复失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"停止所有自动回复失败：{str(e)}")
    
    def _update_all_cards_auto_reply_status(self):
        """更新所有卡片的自动回复状态"""
        try:
            for i in range(self.accounts_layout.count() - 1):  # -1 因为最后一个是stretch
                widget = self.accounts_layout.itemAt(i).widget()
                if isinstance(widget, AutoReplyCard):
                    # 检查实际运行状态
                    is_running = auto_reply_manager.is_running(widget.account_data)
                    widget.setAutoReplyStatus(is_running)
                    
        except Exception as e:
            self.logger.error(f"更新卡片状态失败: {str(e)}")
    
    def onAccountOnline(self, account_data: dict):
        """账号上线回调"""
        try:
            name = account_data.get("username") or account_data.get("user_id") or "账号"
            self._toast("正在上线", f"{name}：正在请求拼多多客服上线…", level="info", duration=2000)

            # 找到对应的卡片
            account_card = self.findAccountCard(account_data)
            if account_card:
                account_card.setButtonLoading("online", True)
            else:
                self.logger.warning(f"未找到账号卡片: {account_data}")

            # 创建设置状态线程
            self.status_thread = SetStatusThread(account_data, 1)  # 1表示在线
            
            # 连接信号
            self.status_thread.status_set_success.connect(self.onStatusSetSuccess)
            self.status_thread.status_set_failed.connect(self.onStatusSetFailed)
            
            # 启动线程
            self.status_thread.start()
            
        except Exception as e:
            self.logger.error(f"启动上线操作失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"启动上线操作失败：{str(e)}")
    
    def onAccountOffline(self, account_data: dict):
        """账号离线回调"""
        try:
            name = account_data.get("username") or account_data.get("user_id") or "账号"
            self._toast("正在离线", f"{name}：正在请求拼多多客服离线…", level="info", duration=2000)

            # 找到对应的卡片
            account_card = self.findAccountCard(account_data)
            if account_card:
                account_card.setButtonLoading("offline", True)
            else:
                self.logger.warning(f"未找到账号卡片: {account_data}")

            # 创建设置状态线程
            self.status_thread = SetStatusThread(account_data, 3)  # 3表示离线
            
            # 连接信号
            self.status_thread.status_set_success.connect(self.onStatusSetSuccess)
            self.status_thread.status_set_failed.connect(self.onStatusSetFailed)
            
            # 启动线程
            self.status_thread.start()
            
        except Exception as e:
            self.logger.error(f"启动离线操作失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"启动离线操作失败：{str(e)}")
    
    def findAccountCard(self, account_data: dict):
        """查找对应的账号卡片（按渠道+店铺+用户 ID 匹配，避免 dict 引用不一致）。"""
        key = self._account_match_key(account_data)
        for i in range(self.accounts_layout.count() - 1):  # -1 因为最后一个是stretch
            widget = self.accounts_layout.itemAt(i).widget()
            if isinstance(widget, AutoReplyCard) and self._account_match_key(
                widget.account_data
            ) == key:
                return widget
        return None
    
    def onStatusSetSuccess(self, account_data: dict, new_status: int):
        """状态设置成功回调"""
        try:
            # 找到对应的卡片
            account_card = self.findAccountCard(account_data)
            if account_card:
                # 恢复按钮状态
                account_card.setButtonLoading("online", False)
                account_card.setButtonLoading("offline", False)
            
            # 更新卡片状态
            self.updateCardStatus(account_data, new_status)
            
            status_text = "在线" if new_status == 1 else "离线"
            name = account_data.get("username") or account_data.get("user_id") or "账号"
            self.logger.info(f"账号 '{name}' 已成功设置为{status_text}状态")
            self._toast(
                f"已{status_text}",
                f"账号「{name}」拼多多客服状态已设为{status_text}。",
                level="success",
            )

        except Exception as e:
            self.logger.error(f"处理状态设置成功回调失败: {str(e)}")
    
    def onStatusSetFailed(self, account_data: dict, error_message: str):
        """状态设置失败回调"""
        try:
            # 找到对应的卡片
            account_card = self.findAccountCard(account_data)
            if account_card:
                # 恢复按钮状态
                account_card.setButtonLoading("online", False)
                account_card.setButtonLoading("offline", False)
            
            name = account_data.get("username") or account_data.get("user_id") or "账号"
            self.logger.error(f"设置账号 '{name}' 状态失败：{error_message}")
            self._toast("状态设置失败", f"{name}：{error_message}", level="error", duration=4000)
            QMessageBox.warning(self, "失败", f"设置账号「{name}」状态失败：\n{error_message}")
            
        except Exception as e:
            self.logger.error(f"处理状态设置失败回调失败: {str(e)}")
    
    def onAutoReplyToggle(self, account_data: dict):
        """自动回复开关回调"""
        try:
            # 找到对应的卡片
            account_card = self.findAccountCard(account_data)
            if not account_card:
                self.logger.error("找不到对应的账号卡片")
                self._toast("操作失败", "未找到对应账号卡片，请点「刷新」后重试。", level="warning")
                return

            # 检查当前自动回复状态
            current_status = auto_reply_manager.is_running(account_data)
            
            if current_status:
                # 当前正在运行，需要停止
                self._stop_auto_reply(account_data, account_card)
            else:
                # 当前未运行，需要启动
                self._start_auto_reply(account_data, account_card)
                
        except Exception as e:
            self.logger.error(f"自动回复开关操作失败: {str(e)}")
            QMessageBox.critical(self, "错误", f"自动回复操作失败：{str(e)}")
    
    def _start_auto_reply(self, account_data: dict, account_card):
        """启动自动回复"""
        try:
            # 检查账号状态，只有在线状态才能启动自动回复
            if account_data.get("status") != 1:
                QMessageBox.warning(self, "提示", "账号必须先上线才能开始自动回复！")
                return
            
            # 设置按钮为加载状态
            account_card.auto_reply_btn.setText("启动中...")
            account_card.auto_reply_btn.setEnabled(False)
            
            # 启动自动回复
            success = auto_reply_manager.start_auto_reply(account_data)
            
            if success:
                account_card.setAutoReplyStatus(True)
                name = account_data.get("username") or account_data.get("user_id") or "账号"
                self.logger.info(f"账号 '{name}' 自动回复启动成功")
                self._toast(
                    "正在连接",
                    f"账号「{name}」自动回复已启动，连接成功后按钮会变为「停止回复」。",
                    level="info",
                    duration=3500,
                )
                self._connect_auto_reply_signals(account_data)

            else:
                # 启动失败，恢复按钮状态
                account_card.auto_reply_btn.setText("开始回复")
                account_card.auto_reply_btn.setEnabled(True)
                QMessageBox.warning(self, "失败", f"启动账号 '{account_data['username']}' 自动回复失败！")
                
        except Exception as e:
            self.logger.error(f"启动自动回复失败: {str(e)}")
            account_card.auto_reply_btn.setText("开始回复")
            account_card.auto_reply_btn.setEnabled(True)
            QMessageBox.critical(self, "错误", f"启动自动回复失败：{str(e)}")
    
    def _stop_auto_reply(self, account_data: dict, account_card):
        """停止自动回复"""
        try:
            # 设置按钮为加载状态
            account_card.auto_reply_btn.setText("停止中...")
            account_card.auto_reply_btn.setEnabled(False)
            
            # 停止自动回复
            success = auto_reply_manager.stop_auto_reply(account_data)
            
            # 无论成功与否，都更新UI状态（因为已经从管理器中移除）
            account_card.setAutoReplyStatus(False)
            account_card.auto_reply_btn.setEnabled(True)

            name = account_data.get("username") or account_data.get("user_id") or "账号"
            if success:
                self.logger.info(f"账号 '{name}' 自动回复停止成功")
                self._toast("已停止回复", f"账号「{name}」自动回复已停止。", level="success")
            else:
                self.logger.warning(f"账号 '{name}' 自动回复停止可能未完全成功")
                self._toast(
                    "已停止回复",
                    f"账号「{name}」已断开自动回复（如有异常请查看日志）。",
                    level="warning",
                )

            self.updateStats()
                
        except Exception as e:
            self.logger.error(f"停止自动回复失败: {str(e)}")
            # 即使出错也要恢复按钮状态
            account_card.setAutoReplyStatus(False)
            QMessageBox.critical(self, "错误", f"停止自动回复失败：{str(e)}")
            # 更新统计信息
            self.updateStats()
    
    def _connect_auto_reply_signals(self, account_data: dict):
        """连接自动回复相关信号"""
        try:
            account_key = f"{account_data['channel_name']}_{account_data['shop_id']}_{account_data['username']}"
            
            if account_key in auto_reply_manager.running_accounts:
                thread = auto_reply_manager.running_accounts[account_key]
                
                # 连接成功和失败信号
                thread.connection_success.connect(
                    lambda: self._on_auto_reply_success(account_data)
                )
                thread.connection_failed.connect(
                    lambda error: self._on_auto_reply_failed(account_data, error)
                )
                
        except Exception as e:
            self.logger.error(f"连接自动回复信号失败: {str(e)}")
    
    def _on_auto_reply_success(self, account_data: dict):
        """自动回复连接成功回调"""
        try:
            account_card = self.findAccountCard(account_data)
            if account_card:
                account_card.auto_reply_btn.setText("停止回复")
                account_card.auto_reply_btn.setEnabled(True)
                account_card.updateStatus(1)

            # 聊天已连通：标记账号在线，便于与「用户管理」状态一致
            db_manager.update_account_status(
                account_data["channel_name"],
                account_data["shop_id"],
                account_data["user_id"],
                1,
            )
            account_data["status"] = 1

            name = account_data.get("username") or account_data.get("user_id") or "账号"
            self.logger.info(f"账号 '{name}' 自动回复连接成功")
            self._toast(
                "连接成功",
                f"账号「{name}」已连接，可自动接待买家消息。",
                level="success",
            )

            self.updateStats()

        except Exception as e:
            self.logger.error(f"处理自动回复成功回调失败: {str(e)}")
    
    def _on_auto_reply_failed(self, account_data: dict, error: str):
        """自动回复连接失败回调"""
        try:
            account_card = self.findAccountCard(account_data)
            if account_card:
                account_card.setAutoReplyStatus(False)
                account_card.auto_reply_btn.setText("开始回复")
                account_card.auto_reply_btn.setEnabled(True)
            
            self.logger.error(f"账号 '{account_data['username']}' 自动回复连接失败: {error}")
            QMessageBox.warning(self, "连接失败", f"账号 '{account_data['username']}' 自动回复连接失败：{error}")
            
            # 更新统计信息
            self.updateStats()
            
        except Exception as e:
            self.logger.error(f"处理自动回复失败回调失败: {str(e)}")
    
    def updateCardStatus(self, account_data: dict, new_status: int):
        """更新卡片状态"""
        for i in range(self.accounts_layout.count() - 1):  # -1 因为最后一个是stretch
            widget = self.accounts_layout.itemAt(i).widget()
            if isinstance(widget, AutoReplyCard) and widget.account_data == account_data:
                widget.updateStatus(new_status)
                break 
