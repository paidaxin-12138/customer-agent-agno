# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""实时聊天后台发送线程（避免阻塞 UI）。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from PyQt6.QtCore import QThread, pyqtSignal


def _build_outbox_metadata(
    *,
    shop_id: str,
    user_id: str,
    recipient_uid: str,
    login_username: str = "",
    channel_name: str = "pinduoduo",
    session_id: Optional[int] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "shop_id": shop_id,
        "user_id": user_id,
        "from_uid": recipient_uid,
        "username": login_username,
        "login_username": login_username,
        "channel_name": channel_name,
    }
    if session_id is not None:
        meta["session_id"] = int(session_id)
    return meta


class SendHumanMessageThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(
        self,
        shop_id: str,
        user_id: str,
        recipient_uid: str,
        text: str,
        *,
        login_username: str = "",
        channel_name: str = "pinduoduo",
        session_id: Optional[int] = None,
    ):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.text = text
        self.login_username = login_username
        self.channel_name = channel_name
        self.session_id = session_id

    def run(self):
        try:
            from Message.handlers.channel_send import send_human_text_sync

            meta = _build_outbox_metadata(
                shop_id=self.shop_id,
                user_id=self.user_id,
                recipient_uid=self.recipient_uid,
                login_username=self.login_username,
                channel_name=self.channel_name,
                session_id=self.session_id,
            )
            ok, err = send_human_text_sync(
                self.shop_id,
                self.user_id,
                self.recipient_uid,
                text=self.text,
                metadata=meta,
            )
            self.finished_with_result.emit(bool(ok), err or "")
        except Exception as e:
            self.finished_with_result.emit(False, str(e))


class SendImageMessageThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(
        self,
        shop_id: str,
        user_id: str,
        recipient_uid: str,
        image_url: str,
        *,
        login_username: str = "",
        channel_name: str = "pinduoduo",
        session_id: Optional[int] = None,
    ):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.image_url = image_url
        self.login_username = login_username
        self.channel_name = channel_name
        self.session_id = session_id

    def run(self):
        try:
            from Message.handlers.channel_send import send_image_sync

            meta = _build_outbox_metadata(
                shop_id=self.shop_id,
                user_id=self.user_id,
                recipient_uid=self.recipient_uid,
                login_username=self.login_username,
                channel_name=self.channel_name,
                session_id=self.session_id,
            )
            ok, err = send_image_sync(
                self.shop_id,
                self.user_id,
                self.recipient_uid,
                image_url=self.image_url,
                metadata=meta,
            )
            self.finished_with_result.emit(bool(ok), err or "")
        except Exception as e:
            self.finished_with_result.emit(False, str(e))


class SendGoodsCardThread(QThread):
    finished_with_result = pyqtSignal(bool, str)

    def __init__(
        self,
        shop_id: str,
        user_id: str,
        recipient_uid: str,
        goods_id: int,
        *,
        login_username: str = "",
        channel_name: str = "pinduoduo",
        session_id: Optional[int] = None,
    ):
        super().__init__()
        self.shop_id = shop_id
        self.user_id = user_id
        self.recipient_uid = recipient_uid
        self.goods_id = goods_id
        self.login_username = login_username
        self.channel_name = channel_name
        self.session_id = session_id

    def run(self):
        try:
            from Message.handlers.channel_send import send_goods_card_sync

            meta = _build_outbox_metadata(
                shop_id=self.shop_id,
                user_id=self.user_id,
                recipient_uid=self.recipient_uid,
                login_username=self.login_username,
                channel_name=self.channel_name,
                session_id=self.session_id,
            )
            ok, err = send_goods_card_sync(
                self.shop_id,
                self.user_id,
                self.recipient_uid,
                goods_id=int(self.goods_id),
                metadata=meta,
            )
            self.finished_with_result.emit(bool(ok), err or "")
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
            from Message.handlers.channel_send import send_human_text_sync

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
                meta = _build_outbox_metadata(
                    shop_id=shop_id,
                    user_id=user_id,
                    recipient_uid=buyer_uid,
                    login_username=str(self.payload.get("login_username") or ""),
                    channel_name=str(self.payload.get("channel_name") or "pinduoduo"),
                )
                send_ok, send_err = send_human_text_sync(
                    shop_id,
                    user_id,
                    buyer_uid,
                    text=msg,
                    metadata=meta,
                )
                if not send_ok:
                    self.finished_with_result.emit(False, msg, send_err or "话术发送失败")
                    return
            api_err = str(result.get("api_error") or "")
            self.finished_with_result.emit(ok, msg, api_err)
        except Exception as e:
            self.finished_with_result.emit(False, "", str(e))
