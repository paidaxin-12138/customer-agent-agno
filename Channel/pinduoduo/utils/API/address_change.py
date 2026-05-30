"""MMS 改址 HTTP（URL 需抓包后在 config 中配置）。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from config import config

from ..base_request import BaseRequest
from .chat_orders import _chat_mms_headers


class AddressChangeAPI(BaseRequest):
    """提交收货地址修改。"""

    def submit_address_change(
        self,
        order_sn: str,
        *,
        name: str,
        mobile: str,
        province: str,
        city: str,
        district: str,
        detail: str,
        shipped_override: bool = False,
    ) -> Dict[str, Any]:
        url = str(config.get("chat.address_change_mms_url") or "").strip()
        if not url:
            return {
                "success": False,
                "error_msg": "改址 MMS 接口未配置（chat.address_change_mms_url）",
                "not_configured": True,
            }

        body: Dict[str, Any] = {
            "orderSn": str(order_sn).strip(),
            "receiverName": name,
            "receiverPhone": mobile,
            "province": province,
            "city": city,
            "district": district,
            "address": detail,
            "shippedOverride": bool(shipped_override),
        }
        headers = _chat_mms_headers(self.cookies)
        result = self.post(url, json_data=body, headers=headers)
        if not result:
            return {"success": False, "error_msg": "改址请求无响应"}
        if result.get("success") is True:
            return {"success": True, "result": result.get("result")}
        err = (
            result.get("errorMsg")
            or result.get("error_msg")
            or result.get("error_msg")
            or "改址失败"
        )
        return {"success": False, "error_msg": str(err), "raw": result}
