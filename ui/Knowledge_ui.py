"""
知识库管理UI模块

提供知识库数据展示、添加、导入和删除功能。
"""

from __future__ import annotations
import asyncio
import os
import sys
from typing import TYPE_CHECKING, Optional, List
from PyQt6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QFrame,
    QGridLayout,
    QFileDialog,
    QMessageBox,
    QDialog,
    QInputDialog,
    QSizePolicy,
    QProgressBar,
)
from PyQt6.QtCore import Qt, QTimer, QThread, pyqtSignal, QProcess
from qfluentwidgets import (
    FluentIcon as FIF,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    CaptionLabel,
    InfoBar,
    InfoBarPosition,
)

if TYPE_CHECKING:
    from Agent.CustomerAgent.agent_knowledge import KnowledgeManager
from utils.logger_loguru import get_logger
from utils.file_validator import FileValidator, ExcelValidator
from utils.dialogs import confirm_action

from .knowledge.models import SimpleDocument, ImportError as KnowledgeImportError
from .knowledge.widgets import KnowledgeCard, AddKnowledgeDialog
from .goods_sync_subprocess import GoodsSyncSubprocessRunner

logger = get_logger(__name__)


class GoodsSyncCookiePreflightWorker(QThread):
    """同步前检测商品接口登录态，必要时刷新 Cookie 写入数据库。"""

    finished_ok = pyqtSignal()
    finished_fail = pyqtSignal(str)

    def __init__(self, shop_id: str, user_id: str, parent=None):
        super().__init__(parent)
        self.shop_id = shop_id
        self.user_id = user_id

    def run(self) -> None:
        try:
            from Channel.pinduoduo.utils.API.product_manager import ProductManager
            from scripts.sync_goods_to_kb import _normalize_sync_error_message

            pm = ProductManager(shop_id=self.shop_id, user_id=self.user_id)
            result = pm.get_product_list(page=1, size=1)
            if result and result.get("success"):
                self.finished_ok.emit()
                return

            err = str((result or {}).get("error_msg") or (result or {}).get("errorMsg") or "")
            expired = "会话已过期" in err or (result or {}).get("error_code") == 43001
            if expired:
                logger.info("商品接口会话过期，尝试刷新 Cookie…")
                refreshed = pm.force_refresh_cookies() or pm.force_relogin()
                if refreshed:
                    result2 = pm.get_product_list(page=1, size=1)
                    if result2 and result2.get("success"):
                        self.finished_ok.emit()
                        return
                self.finished_fail.emit(_normalize_sync_error_message(err))
                return

            self.finished_fail.emit(_normalize_sync_error_message(err or "商品接口不可用"))
        except Exception as e:
            logger.error(f"同步前检查登录态失败: {e}")
            self.finished_fail.emit(str(e))


class ImportWorker(QThread):
    """导入工作线程，在后台执行异步导入操作"""

    success = pyqtSignal(int)
    failed = pyqtSignal(str)

    def __init__(
        self,
        knowledge_manager: KnowledgeManager,
        file_path: str,
        platform_shop_id: Optional[str] = None,
        inherit_key: Optional[str] = None,
        allow_child_override: bool = False,
    ):
        super().__init__()
        self.knowledge_manager = knowledge_manager
        self.file_path = file_path
        self.platform_shop_id = (platform_shop_id or "").strip() or None
        self.inherit_key = (inherit_key or "").strip() or None
        self.allow_child_override = bool(allow_child_override)

    def run(self):
        """在子线程中运行异步导入"""
        try:
            # 在子线程中创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 运行异步导入
            count = loop.run_until_complete(self._import_async())
            self.success.emit(count)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            # 清理事件循环
            try:
                loop.close()
            except Exception as e:
                logger.warning(f"关闭事件循环异常：{e}")

    async def _import_async(self) -> int:
        """异步导入知识库文件"""
        # 导入前文件预检查
        logger.info("正在进行文件预检查...")
        from utils.file_validator import FileValidator, ExcelValidator

        file_ext = os.path.splitext(self.file_path)[1].lower()

        # PDF 依赖前置校验：给出可执行的安装指引，避免进入底层后报错不明确
        if file_ext == ".pdf":
            capabilities = {}
            if hasattr(self.knowledge_manager, "get_reader_capabilities"):
                capabilities = self.knowledge_manager.get_reader_capabilities() or {}
            pdf_cap = capabilities.get("pdf", {})
            if not pdf_cap.get("enabled", False):
                raise KnowledgeImportError(
                    "当前环境未启用 PDF 解析能力。",
                    [
                        pdf_cap.get("missing_hint")
                        or "请安装 pypdf 后重启应用再导入 PDF。",
                    ],
                )
            self._validate_pdf_extractable(self.file_path)

        # 根据文件类型验证
        if file_ext in ['.xlsx', '.xls']:
            validator = ExcelValidator()
            result = validator.validate_readable(self.file_path)
            if not result.is_valid and result.error_type == "MISSING_DEPENDENCY":
                result = validator.validate_basic(self.file_path)
            if not result.is_valid:
                raise KnowledgeImportError(result.error_message, result.suggestions)
        else:
            validator = FileValidator()
            result = validator.validate_basic(self.file_path)
            if not result.is_valid:
                raise KnowledgeImportError(result.error_message, result.suggestions)

        logger.info("文件预检查通过")

        # 对于文本类文件（CSV、TXT、MD等），可能需要编码转换
        actual_file_path = self.file_path
        if file_ext in ['.csv', '.txt', '.text', '.md', '.markdown']:
            actual_file_path = self._ensure_utf8_encoding(self.file_path)

        # 获取导入前的文档数量
        count_before = self.knowledge_manager.get_content_count()

        # 使用标准导入方法
        imported_count = await self.knowledge_manager.add_content_from_file(
            actual_file_path,
            platform_shop_id=self.platform_shop_id,
            inherit_key=self.inherit_key,
            allow_child_override=self.allow_child_override,
        )

        # 获取导入后的文档数量
        count_after = self.knowledge_manager.get_content_count()
        actual_imported = count_after - count_before

        logger.info(f"导入成功,实际新增文档数量: {actual_imported}")

        # 清理临时文件
        if actual_file_path != self.file_path and os.path.exists(actual_file_path):
            try:
                os.remove(actual_file_path)
            except Exception as e:
                logger.warning(f"删除临时文件失败：{e}")

        if actual_imported == 0 and imported_count == 0:
            raise KnowledgeImportError.from_empty_file()

        return max(actual_imported, imported_count)

    def _validate_pdf_extractable(self, file_path: str) -> None:
        """校验 PDF 是否包含可提取文本，避免扫描件直接导入失败。"""
        try:
            from pypdf import PdfReader
        except Exception as err:
            raise KnowledgeImportError(
                "PDF 解析依赖不可用。",
                [f"请安装 pypdf 后重试。详细错误：{err}"]
            )

        try:
            reader = PdfReader(file_path)
            text_len = 0
            checked_pages = 0

            for page in reader.pages[:8]:
                checked_pages += 1
                text_len += len((page.extract_text() or "").strip())

            if text_len == 0:
                raise KnowledgeImportError(
                    "该 PDF 未检测到可提取文本（通常是扫描件图片）。",
                    [
                        "请先将 PDF 做 OCR 文字识别后再导入。",
                        "或将内容复制为 TXT/Markdown 文件导入。",
                    ],
                )

            logger.info(f"PDF 预检查通过: pages={checked_pages}, chars={text_len}")
        except KnowledgeImportError:
            raise
        except Exception as err:
            raise KnowledgeImportError(
                "PDF 文件读取失败，可能文件损坏或受保护。",
                [
                    "请确认 PDF 可正常打开且未加密。",
                    f"详细错误：{err}",
                ],
            )

    def _ensure_utf8_encoding(self, file_path: str) -> str:
        """
        确保文件使用UTF-8编码，如果不是则转换

        Args:
            file_path: 原始文件路径

        Returns:
            UTF-8编码的文件路径（可能是原文件或临时文件）
        """
        from utils.encoding_helper import EncodingConverter

        temp_path, encoding = EncodingConverter.ensure_utf8(file_path)
        logger.info(f"检测到文件编码: {encoding}")

        return temp_path


class AddKnowledgeWorker(QThread):
    """添加知识工作线程，在后台执行异步添加操作"""

    success = pyqtSignal(str)  # 传递标题
    failed = pyqtSignal(str, str)  # 传递标题和错误信息

    def __init__(
        self,
        knowledge_manager: KnowledgeManager,
        title: str,
        content: str,
        platform_shop_id: Optional[str] = None,
        inherit_key: Optional[str] = None,
        allow_child_override: bool = False,
    ):
        super().__init__()
        self.knowledge_manager = knowledge_manager
        self.title = title
        self.content = content
        self.platform_shop_id = (platform_shop_id or "").strip() or None
        self.inherit_key = (inherit_key or "").strip() or None
        self.allow_child_override = bool(allow_child_override)

    def run(self):
        """在子线程中运行异步添加"""
        try:
            # 在子线程中创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 运行异步添加
            loop.run_until_complete(self._add_async())
            self.success.emit(self.title)
        except Exception as e:
            self.failed.emit(self.title, str(e))
        finally:
            # 清理事件循环
            try:
                loop.close()
            except Exception as e:
                logger.warning(f"关闭事件循环异常：{e}")

    async def _add_async(self) -> None:
        """异步添加知识内容"""
        formatted_content = f"标题: {self.title}\n\n内容:\n{self.content}"
        ok = await self.knowledge_manager.add_text_content(
            self.title,
            formatted_content,
            platform_shop_id=self.platform_shop_id,
            inherit_key=self.inherit_key,
            allow_child_override=self.allow_child_override,
        )
        if not ok:
            raise RuntimeError("写入知识库失败")
        logger.info(f"成功添加文本内容: {self.title}")


class DeleteWorker(QThread):
    """删除文档工作线程，在后台执行删除操作"""

    success = pyqtSignal(str, str)  # 传递 (doc_id, doc_title)
    failed = pyqtSignal(str, str, str)  # 传递 (doc_id, doc_title, error_message)

    def __init__(self, knowledge_manager: KnowledgeManager, doc_id: str, doc_title: str):
        super().__init__()
        self.knowledge_manager = knowledge_manager
        self.doc_id = doc_id
        self.doc_title = doc_title

    def run(self):
        """在子线程中运行删除操作"""
        try:
            # 执行删除（同步操作，已经在子线程中）
            success = self.knowledge_manager.delete_document(self.doc_id)

            if success:
                self.success.emit(self.doc_id, self.doc_title)
            else:
                self.failed.emit(self.doc_id, self.doc_title, "删除操作失败")

        except Exception as e:
            self.failed.emit(self.doc_id, self.doc_title, str(e))


class LoadDataWorker(QThread):
    """数据加载工作线程，在后台执行异步加载操作"""

    finished = pyqtSignal(list)  # 传递加载的文档列表
    failed = pyqtSignal(str)     # 错误消息

    def __init__(self, knowledge_manager: KnowledgeManager):
        super().__init__()
        self.knowledge_manager = knowledge_manager

    def run(self):
        """在子线程中运行异步加载"""
        try:
            # 在子线程中创建新的事件循环
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            # 运行异步加载
            docs = loop.run_until_complete(self._load_async())
            self.finished.emit(docs)
        except Exception as e:
            self.failed.emit(str(e))
        finally:
            # 清理事件循环
            try:
                loop.close()
            except Exception as e:
                logger.warning(f"关闭事件循环异常：{e}")

    async def _load_async(self) -> list:
        """异步加载文档数据"""
        from ui.knowledge.data_loader import KnowledgeDataLoader
        from config import get_config

        try:
            loader = KnowledgeDataLoader(self.knowledge_manager)
            shop_id = (get_config("pinduoduo.shop_id", "") or "").strip() or None
            docs = loader.load_documents(platform_shop_id=shop_id)

            logger.info(f"成功加载 {len(docs)} 个文档")
            return docs

        except Exception as e:
            logger.error(f"加载文档失败: {str(e)}")
            raise


class KnowledgeUI(QFrame):
    """
    知识库管理界面

    提供知识库的可视化管理功能，包括：
    - 知识文档卡片展示
    - 添加/删除知识
    - 导入文件到知识库
    - 刷新数据
    """

    # 类常量
    INITIAL_LOAD_DELAY = 500  # 初始加载延迟（ms）
    RESIZE_DEBOUNCE_DELAY = 150  # 调整大小防抖延迟（ms）
    DEFAULT_COLUMNS = 2  # 默认列数
    CARD_SPACING = 16  # 卡片间距

    BUTTON_WIDTH = 120
    BUTTON_HEIGHT = 40

    def __init__(self, parent: Optional[QWidget] = None):
        """
        初始化知识库UI

        Args:
            parent: 父组件
        """
        super().__init__(parent)
        self.setWindowTitle('知识库数据展示')
        self.setObjectName("知识库管理")
        self.resize(900, 700)

        # 成员变量
        self.knowledge_manager: Optional[KnowledgeManager] = None
        self.docs: List[SimpleDocument] = []
        self._layout_initialized = False

        # 数据缓存
        self._cached_docs: List[SimpleDocument] = []
        self._cache_valid = False

        # 分页相关
        self._current_page = 1  # 当前页码（从1开始）
        self._page_size = 12  # 每页显示数量
        self._total_pages = 1  # 总页数

        # 设置大小策略
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding
        )

        # 防抖定时器
        self._resize_timer = QTimer()
        self._resize_timer.setSingleShot(True)
        self._resize_timer.timeout.connect(self._handle_resize_timeout)

        # 初始化UI
        self._init_ui()

        # 延迟加载数据
        QTimer.singleShot(self.INITIAL_LOAD_DELAY, self.populate_cards)

    def _init_ui(self) -> None:
        """初始化UI组件（页边距与头部布局与关键词管理一致）"""
        self.mainLayout = QVBoxLayout(self)
        self.setLayout(self.mainLayout)
        self.mainLayout.setContentsMargins(30, 30, 30, 30)
        self.mainLayout.setSpacing(25)

        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(20)

        title_area = QWidget()
        title_layout = QVBoxLayout(title_area)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(5)
        title_layout.addWidget(SubtitleLabel("知识库管理"))
        self.status_label = CaptionLabel(f"共 {len(self.docs)} 条记录")
        title_layout.addWidget(self.status_label)

        buttons_widget = QWidget()
        buttons_layout = QHBoxLayout(buttons_widget)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        buttons_layout.setSpacing(10)

        import_btn = PushButton("导入知识库")
        import_btn.clicked.connect(self.import_knowledge)
        import_btn.setFixedSize(self.BUTTON_WIDTH, self.BUTTON_HEIGHT)
        import_btn.setIcon(FIF.FOLDER_ADD)
        buttons_layout.addWidget(import_btn)

        # 新增：同步商品到知识库按钮
        sync_btn = PushButton("同步商品")
        sync_btn.clicked.connect(self.sync_goods_to_knowledge)
        sync_btn.setFixedSize(self.BUTTON_WIDTH, self.BUTTON_HEIGHT)
        sync_btn.setIcon(FIF.SHOPPING_CART)
        sync_btn.setToolTip("同步在售商品；默认 OCR 详情主图并整理参数写入知识库")
        buttons_layout.addWidget(sync_btn)

        restart_btn = PushButton("重启应用")
        restart_btn.clicked.connect(self.restart_application)
        restart_btn.setFixedSize(self.BUTTON_WIDTH, self.BUTTON_HEIGHT)
        restart_btn.setIcon(FIF.SYNC)
        buttons_layout.addWidget(restart_btn)

        refresh_btn = PushButton("刷新")
        refresh_btn.clicked.connect(self.refresh_data)
        refresh_btn.setFixedSize(self.BUTTON_WIDTH, self.BUTTON_HEIGHT)
        refresh_btn.setIcon(FIF.SYNC)
        buttons_layout.addWidget(refresh_btn)

        add_btn = PrimaryPushButton("添加知识")
        add_btn.clicked.connect(self.add_knowledge)
        add_btn.setFixedSize(self.BUTTON_WIDTH, self.BUTTON_HEIGHT)
        add_btn.setIcon(FIF.ADD)
        buttons_layout.addWidget(add_btn)

        header_layout.addWidget(title_area)
        header_layout.addStretch()
        header_layout.addWidget(buttons_widget)
        self.mainLayout.addWidget(header_widget)

        # 添加加载指示器容器（初始隐藏）
        from PyQt6.QtCore import QTimer
        self.loading_container = QWidget()
        self.loading_container.setFixedHeight(40)
        self.loading_container.setVisible(False)

        loading_layout = QVBoxLayout(self.loading_container)
        loading_layout.setContentsMargins(16, 8, 16, 8)
        loading_layout.setSpacing(8)

        # 加载文字提示容器（文字 + 图标）
        loading_text_widget = QWidget()
        loading_text_layout = QHBoxLayout(loading_text_widget)
        loading_text_layout.setContentsMargins(0, 0, 0, 0)
        loading_text_layout.setSpacing(12)

        # 旋转图标（使用圆形点阵）
        self.loading_icon = QLabel("⠋")
        self.loading_icon.setStyleSheet("""
            QLabel {
                color: #0A84FF;
                font-size: 24px;
                font-weight: normal;
            }
        """)
        loading_text_layout.addWidget(self.loading_icon, alignment=Qt.AlignmentFlag.AlignCenter)

        # 加载文字
        self.loading_text = QLabel("正在导入")
        self.loading_text.setStyleSheet("""
            QLabel {
                color: #0A84FF;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        loading_text_layout.addWidget(self.loading_text, alignment=Qt.AlignmentFlag.AlignCenter)

        # 动态省略号
        self.loading_dots = QLabel("...")
        self.loading_dots.setStyleSheet("""
            QLabel {
                color: #0A84FF;
                font-size: 14px;
                font-weight: bold;
            }
        """)
        loading_text_layout.addWidget(self.loading_dots, alignment=Qt.AlignmentFlag.AlignCenter)

        loading_text_layout.addStretch(1)
        loading_layout.addWidget(loading_text_widget)

        self.mainLayout.addWidget(self.loading_container)

        # 动画定时器（用于省略号和图标动画）
        self._loading_animation_timer = QTimer()
        self._loading_animation_timer.timeout.connect(self._update_loading_animation)
        self._loading_dots_state = 0
        self._loading_icon_state = 0

        # 提示语
        tip_label = QLabel("💡 提示：导入或添加知识后需重启应用才可生效哦")
        tip_label.setStyleSheet("""
            QLabel {
                background-color: #1B1F2A;
                border: 1px solid #2A3140;
                border-radius: 12px;
                padding: 8px 12px;
                color: #9EA6B8;
                font-size: 13px;
            }
        """)
        tip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mainLayout.addWidget(tip_label)

        # 主内容滚动区域
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)

        # 内容容器和网格布局
        self.contentWidget = QWidget()
        self.gridLayout = QGridLayout(self.contentWidget)
        self.gridLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.gridLayout.setContentsMargins(0, 0, 0, 0)
        self.gridLayout.setSpacing(self.CARD_SPACING)

        self.scroll.setWidget(self.contentWidget)
        self.mainLayout.addWidget(self.scroll)

        # 分页控件
        self._init_pagination_ui()

    def _init_pagination_ui(self) -> None:
        """初始化分页控件"""
        from qfluentwidgets import ComboBox, PushButton

        # 分页容器
        pagination_container = QWidget()
        pagination_layout = QHBoxLayout(pagination_container)
        pagination_layout.setContentsMargins(0, 8, 0, 0)
        pagination_layout.setSpacing(12)

        # 上一页按钮
        self.prev_page_btn = PushButton("上一页")
        self.prev_page_btn.setFixedSize(120, 40)
        self.prev_page_btn.setEnabled(False)
        self.prev_page_btn.clicked.connect(self._go_to_previous_page)
        pagination_layout.addWidget(self.prev_page_btn)

        # 页码显示
        self.page_label = CaptionLabel("第 1 / 1 页")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pagination_layout.addWidget(self.page_label)

        # 下一页按钮
        self.next_page_btn = PushButton("下一页")
        self.next_page_btn.setFixedSize(120, 40)
        self.next_page_btn.setEnabled(False)
        self.next_page_btn.clicked.connect(self._go_to_next_page)
        pagination_layout.addWidget(self.next_page_btn)

        # 每页数量选择
        page_size_label = CaptionLabel("每页:")
        pagination_layout.addWidget(page_size_label)

        self.page_size_combo = ComboBox()
        self.page_size_combo.addItems(["12", "24", "48", "96"])
        self.page_size_combo.setCurrentIndex(0)
        self.page_size_combo.setFixedSize(88, 40)
        self.page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        pagination_layout.addWidget(self.page_size_combo)

        # 显示总记录数
        pagination_layout.addStretch(1)
        total_label = CaptionLabel(f"共 {len(self.docs)} 条记录")
        pagination_layout.addWidget(total_label)

        self.mainLayout.addWidget(pagination_container)

        # 保存引用
        self.pagination_container = pagination_container
        self.total_label = total_label

    def _ensure_knowledge_manager(self) -> None:
        """按需创建知识库管理器"""
        if self.knowledge_manager is None:
            try:
                # 延迟导入，避免启动时加载 Agno/LanceDB/CulturalManager 等重型模块
                from Agent.CustomerAgent.agent_knowledge import KnowledgeManager
                self.knowledge_manager = KnowledgeManager()
                logger.info("✅ 知识库管理器初始化成功")
            except Exception as e:
                logger.error(f"❌ 知识库管理器初始化失败: {e}")
                self.knowledge_manager = None

    def showEvent(self, event) -> None:
        """窗口显示事件，确保布局正确"""
        super().showEvent(event)
        if event.spontaneous() or not self.isVisible():
            QTimer.singleShot(150, self.populate_cards)

    def _handle_resize_timeout(self) -> None:
        """处理resize防抖超时，重新布局卡片"""
        if self.isVisible() and self._layout_initialized:
            self.populate_cards()

    def resizeEvent(self, event) -> None:
        """窗口大小变化时重新计算布局 - 使用防抖机制"""
        super().resizeEvent(event)

        if self.isVisible() and self._layout_initialized:
            new_size = event.size()
            old_size = event.oldSize()

            if (not old_size.isValid() or
                abs(new_size.width() - old_size.width()) > 30):
                self._resize_timer.stop()
                self._resize_timer.start(self.RESIZE_DEBOUNCE_DELAY)

    def clear_grid_layout(self) -> None:
        """清空网格布局中的所有控件"""
        while self.gridLayout.count():
            item = self.gridLayout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def populate_cards(self) -> None:
        """
        填充知识库卡片到网格布局

        根据窗口大小自适应调整列数。
        使用后台线程加载，避免阻塞UI。
        """
        # 如果窗口还没有正确显示，延迟处理
        if not self.isVisible() or self.width() <= 0:
            if not self._layout_initialized:
                QTimer.singleShot(100, self.populate_cards)
            return

        # 清空现有卡片
        self.clear_grid_layout()

        # 获取知识库数据
        try:
            self._ensure_knowledge_manager()
            if self.knowledge_manager is None:
                no_data_label = QLabel("知识库未初始化，打开该页时将自动加载")
                no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                no_data_label.setStyleSheet("color: #9EA6B8; font-size: 14px; padding: 40px;")
                self.gridLayout.addWidget(no_data_label, 0, 0)
                self._layout_initialized = True
                return

            # 显示加载指示器
            self._show_loading_indicator()

            # 启动后台加载
            self._load_worker = LoadDataWorker(self.knowledge_manager)
            self._load_worker.finished.connect(self._on_data_loaded)
            self._load_worker.failed.connect(self._on_load_failed)
            self._load_worker.start()

        except Exception as e:
            logger.error(f"❌ 启动数据加载失败: {e}")
            self._hide_loading_indicator()
            return

    def _on_data_loaded(self, docs: list) -> None:
        """数据加载完成回调"""
        try:
            self.docs = docs
            self._hide_loading_indicator()

            # 更新缓存
            self._cached_docs = docs
            self._cache_valid = True

            # 重置到第一页
            self._current_page = 1

            # 渲染第一页
            self._populate_current_page()

            logger.info(f"✅ 成功加载 {len(self.docs)} 条知识库记录")

        except Exception as e:
            logger.error(f"❌ 渲染数据失败: {e}")
            self._hide_loading_indicator()

    def _on_load_failed(self, error: str) -> None:
        """数据加载失败回调"""
        logger.error(f"❌ 数据加载失败: {error}")
        self._hide_loading_indicator()

        no_data_label = QLabel(f"加载失败: {error}\n请刷新页面重试")
        no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        no_data_label.setStyleSheet("color: #FF453A; font-size: 14px; padding: 40px;")
        self.gridLayout.addWidget(no_data_label, 0, 0)
        self._layout_initialized = True

    def _load_knowledge_data(self) -> None:
        """
        加载知识库数据

        从LanceDB或Agno API获取文档数据并转换为SimpleDocument列表。
        """
        if self.knowledge_manager is None:
            return

        try:
            self.docs = []

            # 尝试直接从LanceDB获取数据
            try:
                import lancedb
                db_path = self.knowledge_manager.knowledge.vector_db.uri
                db = lancedb.connect(db_path)
                table = db.open_table("customer_knowledge")

                # 获取所有数据
                df = table.to_pandas()

                # 转换为SimpleDocument列表
                for idx, row in df.iterrows():
                    doc = SimpleDocument.from_lancedb_row(row.to_dict(), idx)
                    self.docs.append(doc)

            except Exception as lancedb_err:
                logger.warning(f"从LanceDB直接获取数据失败: {lancedb_err}")

                # 回退到使用Agno的API
                try:
                    results = self.knowledge_manager.search_knowledge(
                        "", limit=1000, ignore_shop_filter=True
                    )
                    self.docs = [SimpleDocument.from_agno_doc(doc) for doc in results]
                    logger.info(f"通过搜索API获取到 {len(self.docs)} 条记录")
                except Exception as search_err:
                    logger.error(f"搜索API也失败: {search_err}")
                    self.docs = []

            logger.info(f"✅ 成功加载 {len(self.docs)} 条知识库记录")

        except Exception as e:
            logger.error(f"❌ 获取知识库内容失败: {e}")
            import traceback
            traceback.print_exc()
            self.docs = []

    def add_knowledge(self) -> None:
        """添加知识内容"""
        self._ensure_knowledge_manager()
        if self.knowledge_manager is None:
            self._show_message('error', "错误", "知识库管理器未初始化")
            return

        # 创建并显示添加知识对话框
        dialog = AddKnowledgeDialog(self)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            title, content, shop_id, inherit_key, allow_child_override = dialog.get_data()

            try:
                # 确认对话框
                shop_note = f"\n店铺 ID：{shop_id}（仅本店）" if shop_id else "\n范围：全店通用"
                ik_note = f"\n继承/覆盖键：{inherit_key}" if inherit_key else ""
                ac_note = (
                    "\n父条允许被子店同键覆盖：是"
                    if (allow_child_override and not shop_id and inherit_key)
                    else ""
                )
                confirm_box = QMessageBox(
                    QMessageBox.Icon.Question,
                    "确认添加",
                    f"确定要添加知识「{title}」吗？\n\n内容长度：{len(content)} 字符{shop_note}{ik_note}{ac_note}",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    self
                )
                confirm_box.button(QMessageBox.StandardButton.Yes).setText("添加")
                confirm_box.button(QMessageBox.StandardButton.No).setText("取消")

                if confirm_box.exec() == QMessageBox.StandardButton.Yes:
                    # 使用工作线程执行添加
                    self._add_worker = AddKnowledgeWorker(
                        self.knowledge_manager,
                        title,
                        content,
                        platform_shop_id=shop_id,
                        inherit_key=inherit_key or None,
                        allow_child_override=allow_child_override,
                    )
                    self._add_worker.success.connect(self._on_add_success)
                    self._add_worker.failed.connect(self._on_add_failed)
                    self._add_worker.start()

            except Exception as e:
                logger.error(f"添加知识失败: {e}")
                self._show_message('error', "添加失败", f"添加知识时出错: {str(e)}")

    def _on_add_success(self, title: str) -> None:
        """添加成功回调"""
        self._show_message('success', "添加成功", f"知识「{title}」已成功添加")
        # 强制刷新缓存
        self.refresh_data(force_reload=True)

    def _on_add_failed(self, title: str, error: str) -> None:
        """添加失败回调"""
        self._show_message('error', "添加失败", f"添加知识「{title}」失败: {error}")

    def _show_loading_indicator(self, message: str = "正在加载"):
        """
        显示加载指示器（带动画）

        Args:
            message: 加载提示文字（不包含省略号）
        """
        self.loading_container.setVisible(True)

        # 提取文字部分（去除可能的省略号）
        base_message = message.replace("...", "").strip()
        self.loading_text.setText(base_message)
        self.status_label.setText(base_message + "...")

        # 启动动画定时器（每200ms更新一次，动画更流畅）
        self._loading_dots_state = 0
        self._update_loading_animation()  # 立即显示初始状态
        self._loading_animation_timer.start(200)

    def _hide_loading_indicator(self):
        """隐藏加载指示器"""
        self.loading_container.setVisible(False)
        # 停止动画定时器
        self._loading_animation_timer.stop()

    def _update_loading_animation(self):
        """更新加载动画（省略号 + 图标动画）"""
        # 更新省略号动画
        dots_states = ["", ".", "..", "..."]
        self._loading_dots_state = (self._loading_dots_state + 1) % len(dots_states)
        self.loading_dots.setText(dots_states[self._loading_dots_state])

        # 更新图标动画（使用圆形点阵，更流畅的加载效果）
        icon_states = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠇", "⠏"]
        current_icon = self.loading_icon.text()
        try:
            current_index = icon_states.index(current_icon)
            next_index = (current_index + 1) % len(icon_states)
            self.loading_icon.setText(icon_states[next_index])
        except ValueError:
            self.loading_icon.setText("⠋")

    def import_knowledge(self) -> None:
        """导入知识库文件"""
        self._ensure_knowledge_manager()
        if self.knowledge_manager is None:
            QMessageBox.critical(self, "错误", "知识库管理器未初始化，无法导入。")
            return

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择知识库文件",
            "",
            "支持的知识库文件 (*.pdf *.csv *.txt *.text *.md *.markdown *.json *.xlsx *.xls *.doc *.docx);;PDF 文件 (*.pdf);;CSV文件 (*.csv);;文本文件 (*.txt *.text *.md *.markdown);;JSON 文件 (*.json);;Excel 文件 (*.xlsx *.xls);;Word 文件 (*.doc *.docx);;所有文件 (*.*)"
        )

        if file_path:
            shop_id, ok = QInputDialog.getText(
                self,
                "绑定拼多多店铺（可选）",
                "仅本店宣发使用的知识，请填该店「店铺 ID」；留空表示全店通用：",
            )
            if not ok:
                return
            shop_id = (shop_id or "").strip() or None

            ik_raw, ok_ik = QInputDialog.getText(
                self,
                "继承/覆盖键（可选）",
                "与「父知识库」中某条共用同一键时，本店导入将覆盖父库检索结果。\n"
                "例如填 SKU 或统一编号；仅本店重写时与父文档填相同键。留空表示独立条目。\n"
                "点「取消」跳过本项（等同留空）。",
            )
            inherit_key = ((ik_raw or "").strip() or None) if ok_ik else None

            allow_child_override = False
            if not shop_id and inherit_key:
                allow_child_override = (
                    QMessageBox.question(
                        self,
                        "父库条目：子店覆盖",
                        "本条为全店通用且已填写「继承/覆盖键」。\n"
                        "是否允许子店铺使用相同键时，在检索中隐藏本条、改用子店文案？\n\n"
                        "选「否」则子店同键仅并列检索，不会替换本条。",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No,
                    )
                    == QMessageBox.StandardButton.Yes
                )

            # 显示加载指示器（带动画）
            self._show_loading_indicator("正在导入知识库")

            # 使用工作线程执行导入
            self._import_worker = ImportWorker(
                self.knowledge_manager,
                file_path,
                platform_shop_id=shop_id,
                inherit_key=inherit_key,
                allow_child_override=allow_child_override,
            )

            # 连接信号
            self._import_worker.success.connect(self._on_import_success)
            self._import_worker.failed.connect(self._on_import_failed)

            # 启动导入
            self._import_worker.start()

    def sync_goods_to_knowledge(self) -> None:
        """同步商品到知识库（独立子进程，避免 OCR 拖死主界面）。"""
        preflight = getattr(self, "_sync_preflight_worker", None)
        if preflight is not None and preflight.isRunning():
            QMessageBox.warning(self, "请稍候", "正在检查拼多多登录态，请稍后再试。")
            return

        runner = getattr(self, "_sync_runner", None)
        if runner is not None and runner.is_running():
            QMessageBox.warning(
                self,
                "同步进行中",
                "商品正在独立进程中同步，请等待完成或点击取消后再试。",
            )
            return

        from scripts.sync_goods_to_kb import (
            validate_pinduoduo_account,
            resolve_sync_shop_credentials,
        )

        shop_id, user_id = resolve_sync_shop_credentials()
        if not shop_id or not user_id:
            QMessageBox.warning(
                self,
                "配置不完整",
                "未找到可用的拼多多账号。\n请先在「用户管理」添加并验证账号，"
                "或在 config.json 中设置 pinduoduo.shop_id / pinduoduo.user_id。",
            )
            return

        login_err = validate_pinduoduo_account(shop_id, user_id)
        if login_err:
            QMessageBox.warning(self, "无法同步", login_err)
            return

        if not confirm_action(
            self,
            "同步商品",
            "将在独立进程中同步商品（含 OCR 时较慢，但主界面可继续操作）。\n"
            "可在 config.json 的 knowledge_base.goods_sync_ocr_enabled 关闭 OCR。\n\n"
            "是否现在开始同步？",
            confirm_text="开始同步",
            cancel_text="取消",
        ):
            return

        self._sync_shop_id = shop_id
        self._sync_user_id = user_id
        from config import get_config

        self._sync_use_ocr = bool(get_config("knowledge_base.goods_sync_ocr_enabled", True))

        # 创建并显示进度对话框
        self._sync_dialog = QDialog(self)
        self._sync_dialog.setWindowTitle("同步商品")
        self._sync_dialog.setFixedSize(400, 200)
        
        layout = QVBoxLayout(self._sync_dialog)
        layout.setContentsMargins(30, 30, 30, 30)
        layout.setSpacing(15)
        
        # 进度标签
        self._sync_label = QLabel("正在获取商品列表...")
        self._sync_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sync_label)
        
        # 进度条
        self._sync_progress = QProgressBar()
        self._sync_progress.setRange(0, 0)  # 不确定进度
        layout.addWidget(self._sync_progress)
        
        # 取消按钮
        cancel_btn = PushButton("取消")
        cancel_btn.setFixedWidth(100)
        layout.addWidget(cancel_btn, 0, Qt.AlignmentFlag.AlignCenter)

        self._sync_dialog.show()

        cancel_btn.clicked.connect(self._cancel_goods_sync)
        self._sync_cancel_btn = cancel_btn

        self._sync_preflight_worker = GoodsSyncCookiePreflightWorker(
            self._sync_shop_id, self._sync_user_id, self
        )
        self._sync_preflight_worker.finished_ok.connect(self._on_sync_preflight_ok)
        self._sync_preflight_worker.finished_fail.connect(self._on_sync_preflight_fail)
        self._sync_preflight_worker.finished.connect(self._on_sync_preflight_finished)
        self._sync_label.setText("正在检查商品接口登录态…")
        self._sync_preflight_worker.start()

    def _on_sync_preflight_finished(self) -> None:
        self._sync_preflight_worker = None

    def _on_sync_preflight_ok(self) -> None:
        if hasattr(self, "_sync_label"):
            self._sync_label.setText("登录态正常，正在启动同步…")
        self._sync_runner = GoodsSyncSubprocessRunner(self)
        self._sync_runner.progress.connect(self._on_sync_progress)
        self._sync_runner.success.connect(self._on_sync_success)
        self._sync_runner.failed.connect(self._on_sync_failed)
        self._sync_runner.finished.connect(self._on_sync_runner_finished)
        self._sync_runner.start(
            self._sync_shop_id,
            self._sync_user_id,
            use_ocr=self._sync_use_ocr,
        )

    def _on_sync_preflight_fail(self, error: str) -> None:
        if hasattr(self, "_sync_dialog"):
            self._sync_dialog.reject()
        extra = ""
        if "会话已过期" in error or "验证" in error:
            extra = (
                "\n\n说明：自动回复走聊天长连接，商品同步走商家后台商品接口，"
                "登录态可能不一致，验证成功后再同步。"
            )
        QMessageBox.warning(self, "无法同步商品", f"{error}{extra}")

    def _cancel_goods_sync(self) -> None:
        preflight = getattr(self, "_sync_preflight_worker", None)
        if preflight is not None and preflight.isRunning():
            preflight.requestInterruption()
            preflight.quit()
            preflight.wait(2000)
        runner = getattr(self, "_sync_runner", None)
        if runner is not None and runner.is_running():
            runner.cancel()
            if hasattr(self, "_sync_label"):
                self._sync_label.setText("正在终止同步进程…")
        if hasattr(self, "_sync_dialog"):
            self._sync_dialog.reject()

    def _on_sync_runner_finished(self) -> None:
        self._sync_runner = None
    
    def _on_sync_progress(self, message: str, current: int, total: int) -> None:
        """同步进度更新"""
        if hasattr(self, '_sync_label'):
            self._sync_label.setText(message)
        if hasattr(self, '_sync_progress'):
            if total > 0:
                self._sync_progress.setRange(0, total)
                self._sync_progress.setValue(min(current, total))
            else:
                self._sync_progress.setRange(0, 0)
    
    def _on_sync_success(self, count: int) -> None:
        """同步成功回调"""
        if hasattr(self, '_sync_dialog'):
            self._sync_dialog.accept()
        
        QMessageBox.information(
            self,
            "同步完成",
            f"成功同步 {count} 个商品到知识库！\n\nAI 现在可以查询和推荐这些商品了。",
        )

        # 子进程已写入磁盘，主进程需重新加载知识库实例
        self.knowledge_manager = None
        QTimer.singleShot(300, self.populate_cards)
    
    def _on_sync_failed(self, error: str) -> None:
        """同步失败回调"""
        if hasattr(self, '_sync_dialog'):
            self._sync_dialog.reject()
        
        QMessageBox.critical(
            self,
            "同步失败",
            f"商品同步失败：\n{error}",
        )

    def restart_application(self) -> None:
        """重启应用：用于知识库导入后快速生效。"""
        if not confirm_action(
            self,
            "重启应用",
            "重启后将重新加载知识库内容。\n是否现在重启？",
            confirm_text="立即重启",
            cancel_text="稍后再说",
        ):
            return

        app = QApplication.instance()
        if app is None:
            QMessageBox.critical(self, "错误", "未检测到应用实例，无法重启。")
            return

        executable = sys.executable
        args = sys.argv[1:]

        # 开发模式（python app.py）需要显式携带脚本路径；打包后直接重启可执行文件。
        if not getattr(sys, "frozen", False):
            script_path = os.path.abspath(sys.argv[0]) if sys.argv else ""
            if script_path:
                args = [script_path] + args

        started = QProcess.startDetached(executable, args)
        if not started:
            QMessageBox.critical(
                self,
                "错误",
                "无法拉起新的应用进程，请手动重启应用。",
            )
            return

        app.quit()

    def _on_import_success(self, count: int) -> None:
        """
        导入成功回调

        Args:
            count: 导入的文档数量
        """
        self._hide_loading_indicator()
        try:
            # 强制刷新缓存
            self.refresh_data(force_reload=True)
        finally:
            QMessageBox.information(self, "成功", f"知识库导入完成！\n成功导入 {count} 条记录")

    def _on_import_failed(self, msg: str) -> None:
        """
        导入失败回调

        Args:
            msg: 错误消息
        """
        self._hide_loading_indicator()
        QMessageBox.critical(self, "错误", f"导入失败：{msg}")

    def refresh_data(self, force_reload: bool = False) -> None:
        """
        刷新数据，确保布局一致性

        Args:
            force_reload: 是否强制重新加载（忽略缓存）
        """
        try:
            # 如果有有效缓存且不是强制刷新，先显示缓存数据
            if self._cached_docs and self._cache_valid and not force_reload:
                self.docs = self._cached_docs
                # 不等待，直接显示缓存
                QTimer.singleShot(0, self._populate_from_cache)
            else:
                # 没有缓存或强制刷新，清空当前显示
                self.clear_grid_layout()

            # 重置布局初始化标志，强制重新计算布局
            self._layout_initialized = False

            # 后台更新数据
            QTimer.singleShot(50, lambda: self._background_refresh(force_reload))

        except Exception as e:
            error_msg = str(e)
            if "Cannot delete" in error_msg or "Access is denied" in error_msg:
                QMessageBox.warning(
                    self, "文件锁定",
                    "知识库文件被其他程序占用，请尝试以下方法：\n\n"
                    "1. 关闭其他可能使用知识库的程序\n"
                    "2. 重启本应用程序\n"
                    "3. 检查是否有杀毒软件在扫描该文件\n\n"
                    "如果问题持续存在，请联系技术支持。"
                )
            else:
                QMessageBox.critical(self, "错误", f"刷新失败：{error_msg}")

    def _populate_from_cache(self) -> None:
        """从缓存数据快速渲染"""
        try:
            if not self.docs:
                return

            # 渲染当前页（使用分页）
            self._populate_current_page()

            # 更新状态标签
            self.status_label.setText(f"共 {len(self.docs)} 条记录（正在更新...）")

        except Exception as e:
            logger.error(f"❌ 渲染缓存数据失败: {e}")

    def _background_refresh(self, force_reload: bool = False) -> None:
        """后台刷新数据"""
        try:
            self._ensure_knowledge_manager()
            if self.knowledge_manager is None:
                return

            # 显示加载指示器（仅在状态栏显示小图标，不显示进度条）
            if not (self._cached_docs and self._cache_valid and not force_reload):
                self._show_loading_indicator()

            # 启动后台加载
            self._load_worker = LoadDataWorker(self.knowledge_manager)
            self._load_worker.finished.connect(self._on_refresh_completed)
            self._load_worker.failed.connect(self._on_refresh_failed)
            self._load_worker.start()

        except Exception as e:
            logger.error(f"❌ 启动后台刷新失败: {e}")
            self._hide_loading_indicator()

    def _on_refresh_completed(self, docs: list) -> None:
        """后台刷新完成回调"""
        try:
            # 更新缓存
            self._cached_docs = docs
            self._cache_valid = True
            self.docs = docs

            # 隐藏加载指示器
            self._hide_loading_indicator()

            # 保持当前页码（如果超出范围则重置）
            if self._current_page > self._total_pages:
                self._current_page = 1

            # 重新渲染当前页
            self._populate_current_page()

            logger.info(f"✅ 后台刷新完成，共 {len(docs)} 条记录")

        except Exception as e:
            logger.error(f"❌ 后台刷新处理失败: {e}")
            self._hide_loading_indicator()

    def _on_refresh_failed(self, error: str) -> None:
        """后台刷新失败回调"""
        logger.error(f"❌ 后台刷新失败: {error}")
        self._hide_loading_indicator()

        # 如果有缓存，保留缓存显示
        if self._cached_docs:
            self._show_message('warning', "更新失败", f"后台更新失败，显示缓存数据\n{error}")
        else:
            # 无缓存，显示错误
            self.clear_grid_layout()
            no_data_label = QLabel(f"刷新失败: {error}\n请重试")
            no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_data_label.setStyleSheet("color: #FF453A; font-size: 14px; padding: 40px;")
            self.gridLayout.addWidget(no_data_label, 0, 0)

    def _show_message(
        self,
        level: str,
        title: str,
        content: str,
        duration: int = 3000
    ) -> None:
        """
        统一的消息显示方法

        Args:
            level: 消息级别 ('success', 'error', 'warning', 'info')
            title: 标题
            content: 内容
            duration: 显示时长（毫秒）
        """
        # 使用 getattr 获取 InfoBar 的方法
        info_method = getattr(InfoBar, level)
        info_method(
            title=title,
            content=content,
            orient=InfoBarPosition.TOP,
            duration=duration,
            parent=self
        )

    # ========== 分页功能方法 ==========

    def _update_pagination(self) -> None:
        """更新分页控件状态"""
        # 计算总页数
        total_docs = len(self.docs)
        if total_docs == 0:
            self._total_pages = 1
        else:
            self._total_pages = (total_docs + self._page_size - 1) // self._page_size

        # 确保当前页码有效
        if self._current_page > self._total_pages:
            self._current_page = self._total_pages
        if self._current_page < 1:
            self._current_page = 1

        # 更新页码显示
        self.page_label.setText(f"第 {self._current_page} / {self._total_pages} 页")

        # 更新按钮状态
        self.prev_page_btn.setEnabled(self._current_page > 1)
        self.next_page_btn.setEnabled(self._current_page < self._total_pages)

        # 更新总记录数
        self.total_label.setText(f"共 {total_docs} 条记录")
        self.status_label.setText(f"共 {total_docs} 条记录")

    def _go_to_previous_page(self) -> None:
        """跳转到上一页"""
        if self._current_page > 1:
            self._current_page -= 1
            self._populate_current_page()

    def _go_to_next_page(self) -> None:
        """跳转到下一页"""
        if self._current_page < self._total_pages:
            self._current_page += 1
            self._populate_current_page()

    def _on_page_size_changed(self, index: int) -> None:
        """
        每页数量改变回调

        Args:
            index: 下拉框索引
        """
        page_sizes = [12, 24, 48, 96]
        new_page_size = page_sizes[index]

        if new_page_size != self._page_size:
            self._page_size = new_page_size
            # 重新计算当前页（保持在相同的数据范围内）
            self._current_page = 1
            self._populate_current_page()

    def _get_current_page_docs(self) -> List[SimpleDocument]:
        """
        获取当前页的文档列表

        Returns:
            当前页的文档列表
        """
        start_idx = (self._current_page - 1) * self._page_size
        end_idx = min(start_idx + self._page_size, len(self.docs))

        if start_idx >= len(self.docs):
            return []

        return self.docs[start_idx:end_idx]

    def _populate_current_page(self) -> None:
        """渲染当前页的卡片"""
        try:
            # 清空现有卡片
            self.clear_grid_layout()

            # 更新分页状态
            self._update_pagination()

            # 获取当前页的文档
            current_docs = self._get_current_page_docs()

            # 检查是否有数据
            if not current_docs:
                if len(self.docs) == 0:
                    # 完全没有数据
                    no_data_label = QLabel("暂无知识库数据\n请点击\"导入知识库\"按钮添加数据")
                else:
                    # 当前页没有数据（异常情况）
                    no_data_label = QLabel("当前页没有数据")
                no_data_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                no_data_label.setStyleSheet("color: #9EA6B8; font-size: 14px; padding: 40px;")
                self.gridLayout.addWidget(no_data_label, 0, 0)
                self._layout_initialized = True
                return

            # 固定列数布局
            columns = self.DEFAULT_COLUMNS

            # 添加卡片到网格
            for idx, doc in enumerate(current_docs):
                card = KnowledgeCard(self, doc)
                row = idx // columns
                col = idx % columns
                self.gridLayout.addWidget(card, row, col)

            # 设置列等宽拉伸
            for col in range(columns):
                self.gridLayout.setColumnStretch(col, 1)

            # 标记布局已初始化
            self._layout_initialized = True


        except Exception as e:
            logger.error(f"❌ 渲染当前页失败: {e}")
