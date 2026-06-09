# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""实时聊天后台发送线程（避免阻塞 UI）。"""
from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal


class SendHumanMessageThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(self, shop_id: str, user_id: str, recipient_uid: str, text: str):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.text = text

    def run(self):
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(self.shop_id, self.user_id)
            result = sender.send_text(self.recipient_uid, self.text)
            if isinstance(result, dict) and result.get("success"):
                self.finished_with_result.emit(True, "")
                return
            if isinstance(result, str) and result:
                self.finished_with_result.emit(False, result)
                return
            self.finished_with_result.emit(False, "发送失败")
        except Exception as e:
            self.finished_with_result.emit(False, str(e))


class SendImageMessageThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(self, shop_id: str, user_id: str, recipient_uid: str, image_url: str):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.image_url = image_url

    def run(self):
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(self.shop_id, self.user_id)
            result = sender.send_image(self.recipient_uid, self.image_url)
            if isinstance(result, dict) and result.get("success"):
                self.finished_with_result.emit(True, "")
                return
            err = ""
            if isinstance(result, dict):
                err = str(result.get("error_msg") or result.get("error") or "")
            self.finished_with_result.emit(False, err or "图片发送失败")
        except Exception as e:
            self.finished_with_result.emit(False, str(e))


class SendGoodsCardThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(self, shop_id: str, user_id: str, recipient_uid: str, goods_id: int):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.goods_id = goods_id

    def run(self):
        try:
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            sender = SendMessage(self.shop_id, self.user_id)
            result = sender.send_mallGoodsCard(self.recipient_uid, self.goods_id, biz_type=2)
            if isinstance(result, dict) and result.get("success"):
                self.finished_with_result.emit(True, "")
                return
            err = ""
            if isinstance(result, dict):
                err = str(result.get("error_msg") or result.get("error") or "")
            self.finished_with_result.emit(False, err or "商品卡发送失败")
        except Exception as e:
            self.finished_with_result.emit(False, str(e))


class AddressChangeExecuteThread(QThread):
    finished_with_result = pyqtSignal(bool, str, str)

    def __init__(self, payload: dict):
        super().__init__()
        self.payload = payload

    def run(self):
        try:
            from utils.merchant_address_change_record import execute_address_change
            from Channel.pinduoduo.utils.API.send_message import SendMessage

            result = execute_address_change(self.payload)
            ok = bool(result.get("success"))
            msg = str(result.get("message") or "")
            shop_id = str(
                self.payload.get("platform_shop_id")
                or self.payload.get("shop_id")
                or ""
            )
            user_id = str(self.payload.get("seller_user_id") or "")
            buyer_uid = str(self.payload.get("buyer_uid") or "")
            if msg and shop_id and user_id and buyer_uid:
                sender = SendMessage(shop_id, user_id)
                send_result = sender.send_text(buyer_uid, msg)
                if isinstance(send_result, dict) and not send_result.get("success"):
                    err = str(send_result.get("error_msg") or "话术发送失败")
                    self.finished_with_result.emit(False, msg, err)
                    return
            api_err = str(result.get("api_error") or "")
            self.finished_with_result.emit(ok, msg, api_err)
        except Exception as e:
            self.finished_with_result.emit(False, "", str(e))
