# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from ..base_request import BaseRequest


class GetToken(BaseRequest):
    def __init__(self, shop_id, user_id, channel_name="pinduoduo"):
        super().__init__(shop_id, user_id, channel_name)

    def get_token(self):
        """
        根据提供的店铺名获取对应的token
        Returns:
            str: 成功返回token字符串
            None: 获取失败返回None
        """
        url = "https://mms.pinduoduo.com/chats/getToken"
        payload = {'version': '3'}

        result = self.post(url, data=payload)
        
        if result:
            # 处理响应
            if 'token' in result:
                return result['token']
            elif 'result' in result and 'token' in result['result']:
                return result['result']['token']
            else:
                from utils.log_redact import redact_log_payload

                safe = redact_log_payload(result if isinstance(result, dict) else {"raw": result})
                self.logger.error(
                    "账号 {} 无法从响应中获取 token: {}",
                    self.account_name,
                    safe,
                )
        
        return None



