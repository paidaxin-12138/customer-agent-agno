# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""实时聊天 — 表情 / 图片 / 商品卡 / AI 辅助输入。"""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QLineEdit,
    QMessageBox,
)

from ui.chat.dialogs import EmojiPickerDialog, GoodsIdInputDialog
from ui.chat.send_workers import SendGoodsCardThread, SendImageMessageThread


class ChatAttachmentMixin:
    def _on_emoji_clicked(self) -> None:
        self.logger.info("表情按钮被点击")
        dialog = EmojiPickerDialog(self)
        emoji = dialog.exec()
        if emoji:
            cursor = self.input_edit.textCursor()
            cursor.insertText(emoji)
            self.input_edit.setFocus()

    def _on_img_clicked(self):
        if not self._current:
            QMessageBox.warning(self, "无会话", "请先选择一个会话")
            return

        chooser = QMessageBox(self)
        chooser.setWindowTitle("发送图片")
        chooser.setText("请选择发送方式：")
        local_btn = chooser.addButton("本地图片", QMessageBox.ButtonRole.AcceptRole)
        url_btn = chooser.addButton("图片 URL", QMessageBox.ButtonRole.ActionRole)
        chooser.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        chooser.setDefaultButton(local_btn)
        chooser.exec()

        clicked = chooser.clickedButton()
        if clicked is local_btn:
            file_path, _ = QFileDialog.getOpenFileName(
                self,
                "选择本地图片",
                "",
                "Images (*.png *.jpg *.jpeg *.gif *.webp *.bmp)",
            )
            if file_path:
                self._send_local_image(file_path)
            return
        if clicked is url_btn:
            self._prompt_and_send_image_url()

    def _prompt_and_send_image_url(self, default_url: str = "https://") -> None:
        url, ok = QInputDialog.getText(
            self,
            "发送图片",
            "请输入可公网访问的图片 URL：",
            QLineEdit.EchoMode.Normal,
            default_url,
        )
        if not ok:
            return
        image_url = (url or "").strip()
        if not image_url.startswith(("http://", "https://")):
            QMessageBox.warning(self, "图片地址无效", "请输入 http/https 开头的图片 URL")
            return
        self._send_image_via_url(image_url)

    def _send_local_image(self, file_path: str) -> None:
        acc = self._current["account"]
        try:
            from Channel.pinduoduo.utils.API.upload_media import MediaUploader

            uploader = MediaUploader(str(acc["platform_shop_id"]), str(acc["seller_user_id"]))
            result = uploader.upload_local_image(file_path)
            if result.get("success") and result.get("image_url"):
                self._send_image_via_url(str(result["image_url"]))
                return
            err = str(result.get("error_msg") or "图片上传失败")
        except Exception as e:
            err = str(e)

        fallback = QMessageBox.question(
            self,
            "本地图片上传未就绪",
            f"{err}\n\n是否改为手动输入图片 URL 发送？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if fallback == QMessageBox.StandardButton.Yes:
            self._prompt_and_send_image_url(default_url="https://")

    def _send_image_via_url(self, image_url: str) -> None:
        if not self._current:
            return
        acc = self._current["account"]
        self.btn_img.setEnabled(False)
        self._send_image_thread = SendImageMessageThread(
            str(acc["platform_shop_id"]),
            str(acc["seller_user_id"]),
            str(self._current["buyer_uid"]),
            image_url,
        )
        self._send_image_thread.finished_with_result.connect(self._on_image_send_done)
        self._send_image_thread.start()

    def _on_image_send_done(self, ok: bool, err: str) -> None:
        self.btn_img.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "图片发送失败", err or "")
            return
        QMessageBox.information(self, "发送成功", "图片已发送")

    def _on_goods_card_clicked(self) -> None:
        if not self._current:
            QMessageBox.warning(self, "无会话", "请先选择一个会话")
            return

        dialog = GoodsIdInputDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        goods_id = dialog.get_goods_id()
        if goods_id <= 0:
            QMessageBox.warning(self, "输入错误", "请输入有效的商品 ID（1-12 位数字）")
            return

        acc = self._current["account"]
        self.btn_goods.setEnabled(False)
        self._send_goods_thread = SendGoodsCardThread(
            str(acc["platform_shop_id"]),
            str(acc["seller_user_id"]),
            str(self._current["buyer_uid"]),
            int(goods_id),
        )
        self._send_goods_thread.finished_with_result.connect(self._on_goods_send_done)
        self._send_goods_thread.start()

    def _on_goods_send_done(self, ok: bool, err: str) -> None:
        self.btn_goods.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "商品卡发送失败", err or "")
            return
        QMessageBox.information(self, "发送成功", "商品卡已发送")

    def _on_ai_help_clicked(self):
        self.logger.info("AI 助手按钮被点击")
        if not self._current:
            QMessageBox.warning(self, "无会话", "请先选择一个会话")
            return

        last_message = self._current.get("last_message", "") or "客户消息"
        reply, ok = QInputDialog.getText(
            self,
            "AI 辅助回复",
            f"客户消息：{last_message}\n\n请输入或修改回复内容：",
            QLineEdit.EchoMode.Normal,
            "您好，感谢您的咨询！",
        )
        if ok and reply:
            self.input_edit.clear()
            self.input_edit.insertPlainText(reply)
            self.input_edit.setFocus()
