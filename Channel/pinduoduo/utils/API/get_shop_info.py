from typing import Optional

from ..base_request import BaseRequest


class GetShopInfo(BaseRequest):
    def __init__(self, cookies=None, user_agent: Optional[str] = None):
        # 如果直接传入cookies，不需要从数据库获取
        super().__init__()
        if cookies:
            self.update_cookies(cookies)
        if user_agent and str(user_agent).strip():
            self.default_headers["User-Agent"] = str(user_agent).strip()
    
    def get_shop_info(self):
        url = "https://mms.pinduoduo.com/earth/api/merchant/queryMerchantInfoByMallId"

        headers = {
            "Referer": "https://mms.pinduoduo.com/home",
            "Origin": "https://mms.pinduoduo.com",
        }
        result = self.post(url, json_data={}, headers=headers, timeout=45)

        if not result:
            self.logger.error("获取店铺信息失败: 无响应或解析失败")
            return False

        result_data = result.get("result") or {}
        if result.get("success") is True and isinstance(result_data, dict):
            shop_id = result_data.get("mallId")
            shop_name = result_data.get("mallName")
            mall_logo = result_data.get("mallLogo")
            if shop_id is not None or shop_name:
                return shop_id, shop_name, mall_logo

        if isinstance(result_data, dict) and (
            result_data.get("mallId") is not None or result_data.get("mallName")
        ):
            return (
                result_data.get("mallId"),
                result_data.get("mallName"),
                result_data.get("mallLogo"),
            )

        error_msg = (
            result.get("errorMsg")
            or result.get("error_msg")
            or result.get("error_code")
        )
        self.logger.error(f"获取店铺信息失败: {error_msg}")
        return False