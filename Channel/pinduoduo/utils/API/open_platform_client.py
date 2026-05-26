"""拼多多开放平台 HTTP 客户端（gw-api.pinduoduo.com/api/router）。

签名规则与官方文档一致：参数排序后 key+value 拼接，secret 夹心，MD5 大写。
配置项见 config.json → pinduoduo_open。
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional

from config import config

from ..base_request import BaseRequest


class OpenPlatformAPI(BaseRequest):
    """开放平台 Router 调用基类（需 client_id、client_secret；多数接口还需 access_token）。"""

    API_BASE_URL = "https://gw-api.pinduoduo.com/api/router"

    def __init__(self, shop_id: str, user_id: str, channel_name: str = "pinduoduo"):
        super().__init__(shop_id, user_id, channel_name)
        po = config.get("pinduoduo_open") or {}
        if not isinstance(po, dict):
            po = {}
        self.client_id = str(po.get("client_id", "") or "").strip()
        self.client_secret = str(po.get("client_secret", "") or "").strip()
        self.access_token = str(po.get("access_token", "") or "").strip()

    def _call_open_platform(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """调用开放平台 router（自动附加公共参数与 sign）。"""
        if not self.client_id or not self.client_secret:
            self.logger.warning(
                "拼多多开放平台未配置：请在 config.json 中填写 pinduoduo_open.client_id 与 client_secret"
            )
            return None

        payload: Dict[str, Any] = dict(params)
        payload["client_id"] = self.client_id
        payload["timestamp"] = int(time.time())
        payload["data_type"] = "JSON"
        if self.access_token:
            payload["access_token"] = self.access_token

        sign = self._generate_open_sign(payload)
        payload["sign"] = sign
        return self.post(self.API_BASE_URL, json_data=payload)

    def _generate_open_sign(self, params: Dict[str, Any]) -> str:
        """生成开放平台 MD5 签名（不含 sign 字段）。"""
        signing = {k: v for k, v in params.items() if k != "sign"}
        sorted_params = sorted(signing.items())
        param_str = "".join([f"{k}{v}" for k, v in sorted_params])
        raw = f"{self.client_secret}{param_str}{self.client_secret}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
