from typing import Optional

from ..base_request import BaseRequest


class GetUserInfo(BaseRequest):
    def __init__(self, cookies=None, user_agent: Optional[str] = None):
        super().__init__()
        if cookies:
            self.update_cookies(cookies)
        if user_agent and str(user_agent).strip():
            self.default_headers["User-Agent"] = str(user_agent).strip()
    def get_user_info(self):
        url = "https://mms.pinduoduo.com/janus/api/new/userinfo"
        # 与浏览器一致：须为合法 JSON 体；勿用 data=""（在 application/json 下不是合法 JSON）
        headers = {
            "Referer": "https://mms.pinduoduo.com/home",
            "Origin": "https://mms.pinduoduo.com",
        }
        result = self.post(url, json_data={}, headers=headers, timeout=45)

        if not result:
            self.logger.error("获取用户信息失败: 无响应或解析失败")
            return False

        result_data = result.get("result") or {}
        if result.get("success") is True and isinstance(result_data, dict):
            user_id = result_data.get("id")
            user_name = result_data.get("username")
            mall_id = result_data.get("mall_id")
            if user_id is not None or mall_id is not None:
                return user_id, user_name, mall_id

        # 部分接口省略 success，仅返回 result
        if isinstance(result_data, dict) and (
            result_data.get("id") is not None or result_data.get("mall_id") is not None
        ):
            return (
                result_data.get("id"),
                result_data.get("username"),
                result_data.get("mall_id"),
            )

        error_msg = (
            result.get("errorMsg")
            or result.get("error_msg")
            or result.get("error_code")
        )
        self.logger.error(f"获取用户信息失败: {error_msg}")
        return False