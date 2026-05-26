"""媒体上传适配层（预留）。

当前项目尚未接入拼多多本地图片上传接口，这里提供统一入口，便于后续无缝替换。
"""

from __future__ import annotations

from typing import Dict, Any

from ..base_request import BaseRequest


class MediaUploader(BaseRequest):
    """图片上传适配器。"""

    def __init__(self, shop_id: str, user_id: str, channel_name: str = "pinduoduo"):
        super().__init__(shop_id, user_id, channel_name)

    def upload_local_image(self, file_path: str) -> Dict[str, Any]:
        """上传本地图片并返回可发送URL。

        Returns:
            {"success": bool, "image_url": str, "error_msg": str}
        """
        _ = file_path
        return {
            "success": False,
            "image_url": "",
            "error_msg": "当前版本未接入平台图片上传接口，请先使用公网图片 URL 发送。",
        }
