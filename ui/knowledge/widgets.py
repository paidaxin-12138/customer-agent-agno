"""
知识库UI组件

提供知识库相关的UI组件，包括卡片、对话框和弹窗。
"""

from typing import Optional, Tuple, Dict, Any
from PyQt6.QtCore import Qt, QEvent, QObject, QTimer, QPropertyAnimation, QEasingCurve
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSizePolicy, QFrame, QTextEdit, QDialog, QLineEdit, QGraphicsOpacityEffect, QCheckBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QTabWidget, QScrollArea, QApplication,
)
from PyQt6.QtGui import QCursor
from qfluentwidgets import (
    ElevatedCardWidget, Flyout, FlyoutViewBase, FluentIcon,
    PrimaryPushButton, PushButton, InfoBar, InfoBarPosition, MessageBox
)

from .models import (
    SimpleDocument,
    DocumentTitleExtractor,
    MarkdownConverter,
    infer_import_format,
    parse_display_payload,
    format_preview_line,
)
from utils.logger_loguru import get_logger

logger = get_logger(__name__)


class KnowledgeCard(ElevatedCardWidget):
    """
    知识库卡片组件

    显示文档的标题、预览内容和操作按钮。
    """

    # 类常量
    CARD_MIN_WIDTH = 280
    CARD_MAX_HEIGHT = 180
    PREVIEW_LENGTH = 150
    ID_DISPLAY_LENGTH = 16
    TOOLTIP_SHORT_LENGTH = 30

    def __init__(self, parent: QWidget, doc: SimpleDocument):
        """
        初始化知识卡片

        Args:
            parent: 父组件
            doc: 文档数据
        """
        super().__init__(parent)
        self.doc = doc
        self.current_dialog: Optional[QDialog] = None
        self._delete_worker = None  # 删除工作线程
        self._setup_ui()

        # 设置样式
        self._setup_style()

        # 安装事件过滤器用于点击弹窗
        self.installEventFilter(self)

    def _setup_ui(self) -> None:
        """初始化UI布局"""
        vbox = QVBoxLayout(self)
        vbox.setContentsMargins(10, 10, 10, 10)
        vbox.setSpacing(6)

        # 获取文档标题
        doc_title = DocumentTitleExtractor.extract(self.doc)

        # 标题
        title = QLabel(doc_title)
        title.setStyleSheet("font-weight: bold; font-size: 14px;")
        title.setMaximumHeight(20)
        vbox.addWidget(title)

        # 文档ID
        if self.doc.id:
            cid = QLabel(f"ID: {self.doc.id[:self.ID_DISPLAY_LENGTH]}...")
            cid.setStyleSheet("color: #8A8A98; font-size: 10px;")
            cid.setMaximumHeight(15)
            vbox.addWidget(cid)

        # 内容预览（按导入形式摘要：表格 / JSON / 文本等）
        if self.doc.content or self.doc.metadata:
            content_preview = format_preview_line(self.doc)
            self._content_label = QLabel(content_preview)
            self._content_label.setStyleSheet("color: #9EA6B8; font-size: 12px;")
            self._content_label.setWordWrap(True)
            self._content_label.setMaximumHeight(36)
            vbox.addWidget(self._content_label)

        # 底部信息栏
        info_layout = QHBoxLayout()

        # 文档长度信息
        if self.doc.content:
            length_label = QLabel(f"{len(self.doc.content)}字")
            length_label.setStyleSheet("color: #8A8A98; font-size: 10px;")
            info_layout.addWidget(length_label)

        # 元数据信息
        if self.doc.metadata:
            psid = self.doc.metadata.get("platform_shop_id")
            if psid:
                shop_tag = QLabel(f"店铺 {psid}")
                shop_tag.setStyleSheet("color: #5AC8FA; font-size: 10px;")
                info_layout.addWidget(shop_tag)
            ikey = self.doc.metadata.get("inherit_key")
            if ikey:
                ik_tag = QLabel(f"键 {ikey}")
                ik_tag.setStyleSheet("color: #FFD60A; font-size: 10px;")
                info_layout.addWidget(ik_tag)
            aco = self.doc.metadata.get("allow_child_override")
            if aco in (True, "True", "true", "1", 1):
                ov_tag = QLabel("可被子覆盖")
                ov_tag.setStyleSheet("color: #34C759; font-size: 10px;")
                info_layout.addWidget(ov_tag)
            for key in ['row_number', 'sheet_name', 'section']:
                if key in self.doc.metadata:
                    meta_label = QLabel(f"{self.doc.metadata[key]}")
                    meta_label.setStyleSheet("color: #8A8A98; font-size: 10px;")
                    info_layout.addWidget(meta_label)
                    break

        info_layout.addStretch(1)
        info_layout.setContentsMargins(0, 0, 0, 0)
        vbox.addLayout(info_layout)

        # 按钮栏
        btn_bar = QHBoxLayout()
        view_btn = PrimaryPushButton("详情")
        edit_btn = PushButton("编辑")
        delete_btn = PushButton("删除")
        view_btn.setFixedHeight(30)
        edit_btn.setFixedHeight(30)
        delete_btn.setFixedHeight(30)
        view_btn.setMinimumWidth(60)
        edit_btn.setMinimumWidth(60)
        delete_btn.setMinimumWidth(60)
        view_btn.setIcon(FluentIcon.VIEW)
        edit_btn.setIcon(FluentIcon.EDIT)
        delete_btn.setIcon(FluentIcon.DELETE)

        # 设置删除按钮样式为红色
        delete_btn.setStyleSheet(delete_btn.styleSheet() + "QPushButton { color: #FF453A; }")

        btn_bar.addWidget(view_btn)
        btn_bar.addWidget(edit_btn)
        btn_bar.addWidget(delete_btn)
        btn_bar.setContentsMargins(0, 4, 0, 0)
        vbox.addLayout(btn_bar)

        # 连接信号
        view_btn.clicked.connect(self.show_detail)
        edit_btn.clicked.connect(self.edit_document)
        delete_btn.clicked.connect(self.delete_document)

    def _setup_style(self) -> None:
        """设置组件样式"""
        self.setMinimumWidth(self.CARD_MIN_WIDTH)
        self.setMaximumWidth(16777215)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMaximumHeight(self.CARD_MAX_HEIGHT)
        self.setContentsMargins(8, 8, 8, 8)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """事件过滤器，点击卡片显示详情"""
        if obj is self and event.type() == QEvent.Type.MouseButtonPress:
            self.show_detail()
            return True
        return super().eventFilter(obj, event)

    def show_detail(self) -> None:
        """显示详情弹窗"""
        # 防止重复点击
        if self.current_dialog and self.current_dialog.isVisible():
            return

        doc_title = DocumentTitleExtractor.extract(self.doc)
        flyout_view = KnowledgeDetailFlyout(title=doc_title, doc=self.doc)

        # 使用Flyout控件显示
        self.current_dialog = Flyout.make(
            flyout_view,
            self,
            self.parentWidget(),
            isDeleteOnClose=False
        )


    def edit_document(self) -> None:
        """编辑文档 - 打开编辑对话框"""
        if self.current_dialog and self.current_dialog.isVisible():
            return
        
        doc_title = DocumentTitleExtractor.extract(self.doc)
        
        from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QTextEdit, 
                                     QPushButton, QHBoxLayout, QLabel, QLineEdit)
        from PyQt6.QtCore import Qt
        from qfluentwidgets import InfoBar
        
        dialog = QDialog(self)
        dialog.setWindowTitle(f"编辑文档 - {doc_title}")
        dialog.setMinimumSize(600, 500)
        dialog.setModal(True)
        
        layout = QVBoxLayout(dialog)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        layout.addWidget(QLabel("文档标题："))
        title_edit = QLineEdit(doc_title)
        layout.addWidget(title_edit)
        
        # 内容
        layout.addWidget(QLabel("文档内容："))
        content_edit = QTextEdit()
        content_edit.setPlainText(self.doc.content)
        layout.addWidget(content_edit)
        
        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = PushButton("取消")
        save_btn = PrimaryPushButton("保存")
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)
        
        cancel_btn.clicked.connect(dialog.reject)
        
        def save_changes():
            new_title = title_edit.text().strip()
            new_content = content_edit.toPlainText().strip()
            
            if not new_title or not new_content:
                InfoBar.error("错误", "标题和内容不能为空", parent=dialog, duration=2000)
                return
            
            try:
                parent_widget = self._find_knowledge_ui_parent()
                if not parent_widget or not hasattr(parent_widget, 'knowledge_manager'):
                    InfoBar.error("错误", "无法找到知识库管理器", parent=dialog, duration=2000)
                    return
                
                updates = {
                    "title": new_title,
                    "content": new_content,
                    "import_format": "text",
                }
                success = parent_widget.knowledge_manager.update_document(self.doc.id, updates)
                
                if success:
                    InfoBar.success("成功", "文档已更新", parent=dialog, duration=2000)
                    dialog.accept()
                    if hasattr(parent_widget, 'refresh_data'):
                        parent_widget.refresh_data(force_reload=True)
                else:
                    InfoBar.error("错误", "更新失败", parent=dialog, duration=2000)
            except Exception as e:
                InfoBar.error("错误", f"更新失败：{str(e)}", parent=dialog, duration=2000)
        
        save_btn.clicked.connect(save_changes)
        self.current_dialog = dialog
        dialog.exec()
        self.current_dialog = None

    def delete_document(self) -> None:
        """
        删除文档 - 优化后的确认对话框

        1. 使用顶层窗口确保对话框在屏幕中央
        2. 用户确认后，立即从UI移除卡片（乐观更新）
        3. 后台异步执行删除操作
        4. 失败时恢复卡片并提示错误
        """
        doc_title = DocumentTitleExtractor.extract(self.doc)

        # 获取顶层窗口，确保对话框在屏幕中央
        top_level_widget = self._get_top_level_widget()

        # 确认对话框
        title = "确认删除"
        content = f"确定要删除文档「{doc_title}」吗？\n\n⚠️ 此操作不可恢复！删除后数据将无法找回。"

        box = MessageBox(title, content, top_level_widget)

        # 设置按钮文本
        box.yesButton.setText("确认删除")
        box.cancelButton.setText("取消")

        # 设置对话框为应用模态，确保在屏幕中央显示
        box.setWindowModality(Qt.WindowModality.ApplicationModal)

        if box.exec():
            try:
                # 获取文档ID
                doc_id = self.doc.id
                if not doc_id:
                    self._show_message(
                        'error',
                        "删除失败",
                        "无法获取文档ID"
                    )
                    return

                # 查找知识库管理器
                parent_widget = self._find_knowledge_ui_parent()
                if not parent_widget:
                    self._show_message(
                        'error',
                        "删除失败",
                        "无法找到知识库管理器"
                    )
                    return

                # 乐观删除：先从UI移除卡片
                self._fade_out_and_remove()

                # 后台执行删除操作
                self._execute_delete_background(parent_widget, doc_id, doc_title)

            except Exception as e:
                self._show_message(
                    'error',
                    "删除失败",
                    f"删除文档时出错: {str(e)}"
                )

    def _get_top_level_widget(self) -> QWidget:
        """
        获取顶层窗口（主窗口）

        确保对话框在屏幕中央显示，而不是跟随卡片位置。

        Returns:
            顶层窗口组件
        """
        widget = self
        while widget.parent() is not None:
            widget = widget.parent()
        return widget

    def _find_knowledge_ui_parent(self) -> Optional[QWidget]:
        """
        查找包含 knowledge_manager 的父组件

        Returns:
            知识库UI父组件，如果未找到则返回None
        """
        parent_widget = self.parent()
        while parent_widget and not hasattr(parent_widget, 'knowledge_manager'):
            parent_widget = parent_widget.parent()
        return parent_widget

    def _fade_out_and_remove(self) -> None:
        """
        淡出动画并从布局中移除卡片

        使用乐观删除策略，立即从UI移除，提供快速反馈。
        """
        try:
            # 创建透明度效果
            opacity_effect = QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(opacity_effect)

            # 创建淡出动画
            self._fade_animation = QPropertyAnimation(opacity_effect, b"opacity")
            self._fade_animation.setDuration(300)  # 300ms动画
            self._fade_animation.setStartValue(1.0)
            self._fade_animation.setEndValue(0.0)
            self._fade_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)

            # 动画完成后移除卡片
            self._fade_animation.finished.connect(self._remove_from_layout)

            # 启动动画
            self._fade_animation.start()

            # 禁用删除按钮，防止重复点击
            self.setEnabled(False)

        except Exception as e:
            # 如果动画失败，直接移除
            logger.warning(f"淡出动画失败，直接移除: {e}")
            self._remove_from_layout()

    def _remove_from_layout(self) -> None:
        """从布局中移除卡片"""
        try:
            parent_widget = self.parent()
            if parent_widget and hasattr(parent_widget, 'gridLayout'):
                # 从网格布局中移除
                parent_widget.gridLayout.removeWidget(self)
                self.setParent(None)
                self.deleteLater()
        except Exception as e:
            logger.warning(f"从布局移除失败: {e}")

    def _execute_delete_background(self, parent_ui: QWidget, doc_id: str, doc_title: str) -> None:
        """
        在后台执行删除操作

        Args:
            parent_ui: 知识库UI父组件
            doc_id: 文档ID
            doc_title: 文档标题
        """
        from ui.Knowledge_ui import DeleteWorker

        # 创建删除工作线程
        self._delete_worker = DeleteWorker(
            parent_ui.knowledge_manager,
            doc_id,
            doc_title
        )

        # 连接信号
        self._delete_worker.success.connect(
            lambda did, dtitle: self._on_delete_success(parent_ui, did, dtitle)
        )
        self._delete_worker.failed.connect(
            lambda did, dtitle, error: self._on_delete_failed(parent_ui, did, dtitle, error)
        )

        # 启动后台删除
        self._delete_worker.start()

    def _on_delete_success(self, parent_ui: QWidget, doc_id: str, doc_title: str) -> None:
        """
        删除成功回调 - 自动刷新页面

        Args:
            parent_ui: 知识库UI父组件
            doc_id: 文档ID
            doc_title: 文档标题
        """
        try:
            # 从主数据列表中移除（不仅是缓存）
            if hasattr(parent_ui, 'docs') and parent_ui.docs:
                parent_ui.docs = [doc for doc in parent_ui.docs if doc.id != doc_id]

            # 从缓存中移除（如果存在）
            if hasattr(parent_ui, '_cached_docs'):
                parent_ui._cached_docs = [
                    doc for doc in parent_ui._cached_docs if doc.id != doc_id
                ]

            # 重新计算分页 - 如果当前页空了，跳转到前一页
            if hasattr(parent_ui, '_current_page') and hasattr(parent_ui, '_page_size'):
                total_docs = len(parent_ui.docs)
                page_size = parent_ui._page_size
                current_page = parent_ui._current_page

                # 计算当前页是否还有数据
                start_idx = (current_page - 1) * page_size
                if start_idx >= total_docs and current_page > 1:
                    # 当前页空了，跳转到前一页
                    parent_ui._current_page = current_page - 1

            # 重新渲染当前页
            if hasattr(parent_ui, '_populate_current_page'):
                parent_ui._populate_current_page()

            # 显示成功消息 - 使用 parent_ui 作为父组件
            self._show_message(
                'success',
                "删除成功",
                f"已删除文档「{doc_title}」",
                parent=parent_ui
            )

            logger.info(f"✅ 成功删除文档: {doc_title} (ID: {doc_id})")

        except Exception as e:
            logger.error(f"删除成功回调处理失败: {e}")

    def _on_delete_failed(self, parent_ui: QWidget, doc_id: str, doc_title: str, error: str) -> None:
        """
        删除失败回调 - 刷新页面恢复卡片

        Args:
            parent_ui: 知识库UI父组件
            doc_id: 文档ID
            doc_title: 文档标题
            error: 错误消息
        """
        try:
            # 重新渲染当前页（卡片会被恢复显示）
            if hasattr(parent_ui, '_populate_current_page'):
                parent_ui._populate_current_page()

            # 显示错误消息 - 使用 parent_ui 作为父组件
            self._show_message(
                'error',
                "删除失败",
                f"删除文档「{doc_title}」失败: {error}\n\n数据已恢复显示",
                parent=parent_ui
            )

            logger.error(f"❌ 删除文档失败: {doc_title}, 错误: {error}")

        except Exception as e:
            logger.error(f"删除失败回调处理失败: {e}")

    def _show_message(self, level: str, title: str, content: str, duration: int = 3000, parent: Optional[QWidget] = None) -> None:
        """
        显示消息提示 - 使用 InfoBar 顶部提示条

        Args:
            level: 消息级别 (success, error, warning, info)
            title: 标题
            content: 内容
            duration: 持续时间（毫秒）
            parent: 父组件（如果为None，则自动获取顶层窗口）
        """
        # 如果没有指定父组件，尝试获取顶层窗口
        if parent is None:
            parent = self._get_top_level_widget()

        # 确保父组件有效
        if parent is None:
            logger.warning(f"无法显示消息提示（未找到父组件）: {title} - {content}")
            return

        try:
            info_method = getattr(InfoBar, level)
            info_method(
                title=title,
                content=content,
                orient=InfoBarPosition.TOP,
                duration=duration,
                parent=parent
            )
        except Exception as e:
            logger.error(f"显示消息提示失败: {e}")


class AddKnowledgeDialog(QDialog):
    """
    添加知识对话框

    允许用户输入知识的标题和内容。
    """

    # 类常量
    DIALOG_WIDTH = 600
    DIALOG_HEIGHT = 680
    TITLE_HEIGHT = 35
    CONTENT_MIN_HEIGHT = 350
    BUTTON_WIDTH = 100

    def __init__(self, parent: Optional[QWidget] = None):
        """
        初始化对话框

        Args:
            parent: 父组件
        """
        super().__init__(parent)
        self.setWindowTitle("添加知识")
        self.setFixedSize(self.DIALOG_WIDTH, self.DIALOG_HEIGHT)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._init_ui()

    def _init_ui(self) -> None:
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        # 标题
        title_label = QLabel("知识标题")
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #F2F2F7;")
        layout.addWidget(title_label)

        self.title_edit = QLineEdit()
        self.title_edit.setPlaceholderText("请输入知识标题...")
        self.title_edit.setFixedHeight(self.TITLE_HEIGHT)
        layout.addWidget(self.title_edit)

        # 内容
        content_label = QLabel("知识内容")
        content_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #F2F2F7;")
        layout.addWidget(content_label)

        self.content_edit = QTextEdit()
        self.content_edit.setPlaceholderText("请输入知识内容，支持Markdown格式...")
        self.content_edit.setMinimumHeight(self.CONTENT_MIN_HEIGHT)
        layout.addWidget(self.content_edit)

        shop_label = QLabel("拼多多店铺 ID（可选）")
        shop_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #F2F2F7;")
        layout.addWidget(shop_label)
        self.shop_id_edit = QLineEdit()
        self.shop_id_edit.setPlaceholderText("仅本店使用的宣发文案填店铺 ID；留空表示全店通用")
        self.shop_id_edit.setFixedHeight(self.TITLE_HEIGHT)
        layout.addWidget(self.shop_id_edit)

        ik_label = QLabel("继承/覆盖键 inherit_key（可选）")
        ik_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #F2F2F7;")
        layout.addWidget(ik_label)
        self.inherit_key_edit = QLineEdit()
        self.inherit_key_edit.setPlaceholderText(
            "与父知识库某条「同一键」时，本店文档会覆盖父库检索；留空则本条独立"
        )
        self.inherit_key_edit.setFixedHeight(self.TITLE_HEIGHT)
        layout.addWidget(self.inherit_key_edit)

        self.allow_child_cb = QCheckBox(
            "父库：允许子店铺使用相同 inherit_key 时在检索中隐藏本条"
        )
        self.allow_child_cb.setEnabled(False)
        self.allow_child_cb.setStyleSheet("color: #E5E5EA; font-size: 13px;")
        self.allow_child_cb.setToolTip(
            "仅当「店铺 ID 留空」且填写了 inherit_key 时可勾选；未勾选则子店同键不会替换本条。"
        )
        layout.addWidget(self.allow_child_cb)
        self.shop_id_edit.textChanged.connect(self._sync_allow_child_checkbox)
        self.inherit_key_edit.textChanged.connect(self._sync_allow_child_checkbox)
        self._sync_allow_child_checkbox()

        # 提示信息
        hint_label = QLabel("提示：内容将自动进行分块和向量化处理")
        hint_label.setStyleSheet("color: #8A8A98; font-size: 12px;")
        layout.addWidget(hint_label)

        # 按钮栏
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 10, 0, 0)

        cancel_btn = PushButton("取消")
        cancel_btn.setFixedWidth(self.BUTTON_WIDTH)
        cancel_btn.clicked.connect(self.reject)

        save_btn = PrimaryPushButton("保存")
        save_btn.setFixedWidth(self.BUTTON_WIDTH)
        save_btn.clicked.connect(self._validate_and_accept)

        button_layout.addStretch()
        button_layout.addWidget(cancel_btn)
        button_layout.addWidget(save_btn)

        layout.addLayout(button_layout)

    def _sync_allow_child_checkbox(self) -> None:
        sid = self.shop_id_edit.text().strip()
        ik = self.inherit_key_edit.text().strip()
        ok = (not sid) and bool(ik)
        self.allow_child_cb.setEnabled(ok)
        if not ok:
            self.allow_child_cb.setChecked(False)

    def _validate_and_accept(self) -> None:
        """验证输入并接受"""
        title = self.title_edit.text().strip()
        content = self.content_edit.toPlainText().strip()

        if not title:
            self._show_message('warning', "提示", "请输入知识标题")
            self.title_edit.setFocus()
            return

        if not content:
            self._show_message('warning', "提示", "请输入知识内容")
            self.content_edit.setFocus()
            return

        self.accept()

    def _show_message(self, level: str, title: str, content: str, duration: int = 2000) -> None:
        """显示消息提示"""
        info_method = getattr(InfoBar, level)
        info_method(
            title=title,
            content=content,
            orient=InfoBarPosition.TOP,
            duration=duration,
            parent=self
        )

    def get_data(self) -> Tuple[str, str, str, str, bool]:
        """
        Returns:
            (标题, 内容, 拼多多店铺 ID, inherit_key, allow_child_override)
        """
        sid = self.shop_id_edit.text().strip()
        ik = self.inherit_key_edit.text().strip()
        allow = self.allow_child_cb.isChecked() if self.allow_child_cb.isEnabled() else False
        return (
            self.title_edit.text().strip(),
            self.content_edit.toPlainText().strip(),
            sid,
            ik,
            allow,
        )


class KnowledgeDetailFlyout(FlyoutViewBase):
    """
    知识详情弹窗视图

    按文档导入形式展示：Excel/CSV 为表格，Markdown 为渲染，JSON/文本为等宽或纯文本。
    """

    FLYOUT_WIDTH = 800
    FLYOUT_HEIGHT = 600
    CONTENT_MIN_HEIGHT = 400
    BUTTON_WIDTH_COPY = 120
    BUTTON_WIDTH_CLOSE = 100
    BUTTON_HEIGHT = 36

    def __init__(self, title: str, doc: SimpleDocument):
        super().__init__()
        self._title = title
        self._doc = doc
        self._text_edit: Optional[QTextEdit] = None
        self._plain_copy_text = ""
        self._setup_ui()

    @staticmethod
    def _format_mode_caption(mode: str) -> str:
        return {
            "excel": "展示方式：Excel 表格（与导入行列一致；行数过多时仅展示前 1000 行）",
            "csv": "展示方式：CSV 表格（与导入行列一致；行数过多时仅展示前 1000 行）",
            "json": "展示方式：JSON（等宽文本，与导入格式化结果一致）",
            "markdown": "展示方式：Markdown 渲染（与导入 .md 正文一致）",
            "pdf": "展示方式：PDF 提取纯文本",
            "manual": "展示方式：手动录入（纯文本）",
            "text": "展示方式：纯文本",
        }.get(mode, "展示方式：纯文本")

    @staticmethod
    def _build_table_widget(sheet: Dict[str, Any]) -> QTableWidget:
        cols = [str(c) for c in (sheet.get("columns") or [])]
        rows = sheet.get("rows") or []
        tw = QTableWidget(len(rows), len(cols))
        tw.setHorizontalHeaderLabels(cols)
        tw.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        tw.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectItems)
        tw.setAlternatingRowColors(True)
        tw.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tw.verticalHeader().setVisible(False)
        tw.setStyleSheet(
            """
            QTableWidget {
                gridline-color: #3A3F55;
                background-color: #1B1F2A;
                color: #F2F2F7;
                font-size: 12px;
            }
            QHeaderView::section {
                background-color: #2A3140;
                color: #F2F2F7;
                padding: 4px;
                border: none;
            }
            """
        )
        for r, row in enumerate(rows):
            for c in range(len(cols)):
                val = row[c] if c < len(row) else ""
                item = QTableWidgetItem(str(val))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                tw.setItem(r, c, item)
        return tw

    @staticmethod
    def _tabular_to_tsv(payload: Dict[str, Any]) -> str:
        lines: list[str] = []
        for sh in payload.get("sheets") or []:
            cols = [str(x) for x in (sh.get("columns") or [])]
            if cols:
                lines.append("\t".join(cols))
            for row in sh.get("rows") or []:
                cells = [str(row[i]) if i < len(row) else "" for i in range(len(cols))]
                lines.append("\t".join(cells))
            lines.append("")
        return "\n".join(lines).strip()

    def _setup_ui(self) -> None:
        self.setFixedSize(self.FLYOUT_WIDTH, self.FLYOUT_HEIGHT)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(10)

        title_label = QLabel(self._title)
        title_label.setStyleSheet("font-weight: 600; font-size: 16px; color: #F2F2F7;")
        main_layout.addWidget(title_label)

        mode = infer_import_format(self._doc)
        pl = parse_display_payload(self._doc)
        use_table = bool(
            mode in ("excel", "csv")
            and pl
            and isinstance(pl.get("sheets"), list)
            and pl["sheets"]
        )
        caption = self._format_mode_caption(mode)
        if mode in ("excel", "csv") and not use_table:
            caption += "\n（本条无表格快照，一般为升级前导入；下方为合并后的文本内容）"

        mode_label = QLabel(caption)
        mode_label.setWordWrap(True)
        mode_label.setStyleSheet("color: #9EA6B8; font-size: 11px;")
        main_layout.addWidget(mode_label)

        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("color: #2A3140;")
        main_layout.addWidget(line)

        if use_table:
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            inner = QWidget()
            inner_layout = QVBoxLayout(inner)
            inner_layout.setContentsMargins(0, 0, 0, 0)
            tabs = QTabWidget()
            for sheet in pl["sheets"]:
                tw = self._build_table_widget(sheet)
                name = str(sheet.get("name") or "表")
                tabs.addTab(tw, name[:28])
            inner_layout.addWidget(tabs)
            if any(bool(s.get("truncated")) for s in pl["sheets"]):
                tip = QLabel("部分内容行数较多，表格仅展示前 1000 行；复制为制表符分隔文本时亦同。")
                tip.setWordWrap(True)
                tip.setStyleSheet("color: #8A8A98; font-size: 11px;")
                inner_layout.addWidget(tip)
            scroll.setWidget(inner)
            main_layout.addWidget(scroll, 1)
            self._plain_copy_text = self._tabular_to_tsv(pl)
        else:
            text_edit = QTextEdit()
            text_edit.setReadOnly(True)
            text_edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            text_edit.setMinimumHeight(self.CONTENT_MIN_HEIGHT)
            text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            base_style = """
                QTextEdit {
                    border: none;
                    background-color: transparent;
                    color: #F2F2F7;
                    font-size: 13px;
                }
            """
            body = self._doc.content or ""
            if mode == "markdown":
                text_edit.setHtml(MarkdownConverter.to_html(body))
                self._plain_copy_text = body
                text_edit.setStyleSheet(
                    base_style
                    + "font-family: -apple-system, 'PingFang SC', 'Segoe UI', sans-serif;"
                )
            elif mode == "json":
                text_edit.setPlainText(body)
                self._plain_copy_text = body
                text_edit.setStyleSheet(
                    base_style + "font-family: 'Consolas', 'Monaco', 'Courier New', monospace;"
                )
            else:
                text_edit.setPlainText(body)
                self._plain_copy_text = body
                text_edit.setStyleSheet(
                    base_style + "font-family: 'Consolas', 'Monaco', 'Courier New', monospace;"
                )
            main_layout.addWidget(text_edit, 1)
            self._text_edit = text_edit

        meta_bits = []
        if self._doc.id:
            meta_bits.append(f"ID: {self._doc.id}")
        fn = (self._doc.metadata or {}).get("filename")
        if fn:
            meta_bits.append(f"文件: {fn}")
        if meta_bits:
            foot = QLabel(" · ".join(meta_bits))
            foot.setStyleSheet("color: #6B7280; font-size: 10px;")
            main_layout.addWidget(foot)

        btn_bar = QHBoxLayout()
        btn_bar.setSpacing(12)
        btn_bar.setContentsMargins(0, 10, 0, 0)

        copy_btn = PrimaryPushButton("复制内容")
        copy_btn.setFixedWidth(self.BUTTON_WIDTH_COPY)
        copy_btn.setFixedHeight(self.BUTTON_HEIGHT)
        copy_btn.setIcon(FluentIcon.COPY)

        close_btn = PushButton("关闭")
        close_btn.setFixedWidth(self.BUTTON_WIDTH_CLOSE)
        close_btn.setFixedHeight(self.BUTTON_HEIGHT)
        close_btn.setIcon(FluentIcon.CLOSE)

        copy_btn.clicked.connect(self._copy_content)
        close_btn.clicked.connect(lambda: Flyout.close(self.parent()))

        btn_bar.addStretch(1)
        btn_bar.addWidget(copy_btn)
        btn_bar.addWidget(close_btn)

        main_layout.addLayout(btn_bar)

    def _copy_content(self) -> None:
        if self._plain_copy_text:
            QApplication.clipboard().setText(self._plain_copy_text)
            return
        if self._text_edit is not None:
            self._text_edit.selectAll()
            self._text_edit.copy()
