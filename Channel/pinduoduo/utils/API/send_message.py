from ..base_request import BaseRequest
from typing import Any, Dict, Optional

from .chat_orders import _chat_mms_headers


class SendMessage(BaseRequest):
    def __init__(self, shop_id: str, user_id: str, channel_name: str = "pinduoduo"):
        super().__init__(shop_id, user_id, channel_name)
        
        # 检查账户信息是否正确加载
        if not hasattr(self, 'account_name'):
            self.logger.error(f"无法在数据库中找到账户: shop_id={shop_id}, user_id={user_id}")
            raise ValueError("找不到指定的账户信息")

    def send_text(self, recipient_uid, message_content):
        """
        发送文本消息
        """
        url = "https://mms.pinduoduo.com/plateau/chat/send_message"
        data = {
            "data": {
                "cmd": "send_message",
                "request_id": self.generate_request_id(),
                "message": {
                    "to": {
                        "role": "user",
                        "uid": recipient_uid
                    },
                    "from": {
                        "role": "mall_cs"
                    },
                    "content": message_content,
                    "msg_id": None,
                    "type": 0,
                    "is_aut": 0,
                    "manual_reply": 1,
                },
            },
            "client": "WEB"
        }

        result = self.post(url, json_data=data)
        if result and result.get("success") == True:
            if result.get("result", {}).get("error_code") == 10002:
                error_msg = result.get('result', {}).get('error')
                self.logger.error(f"发送文本消息失败: {error_msg}")
                return error_msg
            else:
                return result
        else:
            self.logger.error(f"发送文本消息失败: {result}")
            return None

 
        
    def send_image(self, recipient_uid, image_url):
        """
        发送图片消息
        """
        url = "https://mms.pinduoduo.com/plateau/chat/send_message"
        data = {
            "data": {
                "cmd": "send_message",
                "request_id": self.generate_request_id(),
                "message": {
                    "to": {
                        "role": "user",
                        "uid": recipient_uid
                    },
                    "from": {
                        "role": "mall_cs"
                    },
                    "content": image_url,
                    "msg_id": None,
                    "chat_type": "cs",
                    "type": 1,
                    "is_aut": 0,
                    "manual_reply": 1,
                }
            },
            "client": "WEB"
        }

        result = self.post(url, json_data=data)
        if result:
            self.logger.debug(f"发送图片消息成功: {result}")
            return result


    def send_mallGoodsCard(self, recipient_uid, goods_id, biz_type: int = 2):
        """
        发送商城商品卡片消息

        Args:
            recipient_uid: 接收消息的用户UID
            goods_id: 商品ID
            biz_type: 业务类型，默认2（客服推荐商品）
        """
        url = "https://mms.pinduoduo.com/plateau/message/send/mallGoodsCard"
        data = {
            "uid": recipient_uid,
            "goods_id": goods_id,
            "biz_type": biz_type
        }

        headers = _chat_mms_headers(self.cookies)
        headers["priority"] = "u=1, i"

        result = self.post(url, json_data=data, headers=headers)
        if result:
            if result.get("success"):
                self.logger.info(f"商品卡片发送成功: goods_id={goods_id}, to={recipient_uid}, biz_type={biz_type}")
            else:
                self.logger.error(f"商品卡片发送失败: {result.get('error_msg', '未知错误')}")
            return result

    def send_ask_refund_apply(
        self,
        order_sn: str,
        *,
        after_sales_type: int = 3,
        question_type: int = 1,
        refund_amount: int,
        message: Optional[str] = None,
        user_ship_status: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        向买家发送「申请退换货/退款」卡片（MMS 非公开接口，需商家 Cookie）。

        Args:
            order_sn: 拼多多订单号
            after_sales_type: 售后类型（常见：2 仅退款，3 退货退款，4 换货，以抓包为准）
            question_type: 原因类型（以商家后台抓包为准，默认 1）
            refund_amount: 申请金额，单位：分
            message: 附带说明（可为空）
            user_ship_status: 发货状态，默认 0
        """
        from .chat_orders import ChatOrdersAPI

        orders_api = ChatOrdersAPI(self.shop_id, self.user_id, self.channel_name)
        orders_api.cookies = self.cookies
        orders_api.default_headers = self.default_headers
        repose_info = orders_api.get_order_pickup_info(order_sn)

        url = "https://mms.pinduoduo.com/plateau/message/ask_refund_apply/send"
        data: Dict[str, Any] = {
            "order_sn": str(order_sn),
            "manualEditedNote": False,
            "after_sales_type": int(after_sales_type),
            "question_type": int(question_type),
            "refund_amount": int(refund_amount),
            "message": message,
            "user_ship_status": int(user_ship_status),
            "reposeInfo": repose_info,
        }
        headers = _chat_mms_headers(self.cookies)
        headers["priority"] = "u=1, i"

        result = self.post(url, json_data=data, headers=headers)
        if result and result.get("success"):
            self.logger.info(
                f"申请退换货卡片已发送: order_sn={order_sn}, type={after_sales_type}"
            )
        else:
            err = None
            if isinstance(result, dict):
                err = result.get("errorMsg") or result.get("error_msg") or result
            self.logger.error(f"申请退换货卡片发送失败: {err}")
        return result


    def getAssignCsList(self):
        """
        获取分配的客服列表
        """
        url = "https://mms.pinduoduo.com/latitude/assign/getAssignCsList"
        data = {"wechatCheck": True}
        
        result = self.post(url, json_data=data)
        if result and result.get('success'):
            return result['result']['csList']
        else:
            error_msg = result.get('result', {}).get('error') if result else "请求失败"
            self.logger.error(f"获取分配的客服列表失败: {error_msg}")
            return None


    def move_conversation(self, recipient_uid, cs_uid):
        """
        转移会话
        """
        url = "https://mms.pinduoduo.com/plateau/chat/move_conversation"
        data = {
            "data": {
                "cmd": "move_conversation",
                "request_id": self.generate_request_id(),
                "conversation": {
                    "csid": cs_uid,
                    "uid": recipient_uid,
                    "need_wx": False,
                    "remark": "无原因直接转移"
                }
            },
            "client": "WEB"
        }
        
        result = self.post(url, json_data=data)
        if result:
            self.logger.debug(f"转移会话成功: {result}")
            return result
