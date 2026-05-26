#!/usr/bin/env python3
"""
为 widgets.py 添加 edit_document 方法
"""
from pathlib import Path

# 读取文件
file_path = Path("ui/knowledge/widgets.py")
content = file_path.read_text(encoding="utf-8")

# 要插入的代码
edit_method = '''
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
                
                updates = {'title': new_title, 'content': new_content}
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

'''

# 在 delete_document 之前插入
insert_marker = "    def delete_document(self) -> None:"
content = content.replace(insert_marker, edit_method + insert_marker)

# 写回文件
file_path.write_text(content, encoding="utf-8")

print("✅ 已添加 edit_document 方法")
