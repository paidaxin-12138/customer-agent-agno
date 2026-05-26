"""
拼多多消息处理类
"""
from bridge.context import  ContextType
from Message.message import ChatMessage

class BaseMessageHandler:
    def __init__(self, msg):
        self.msg = msg
        self.data = msg.get("message",{})
    def get_basic_info(self):
        """获取基础信息"""
        return {
            "msg_id": self.data.get("msg_id"),
            "nickname": self.data.get("nickname"),
            "from_role": self.data.get("from",{}).get("role"),
            "from_uid": self.data.get("from",{}).get("uid"),
            "to_role": self.data.get("to",{}).get("role"),
            "to_uid": self.data.get("to",{}).get("uid"),
            "timestamp": self.data.get("time"),
        }

        
class MessageTypeHandler:
    """消息类型处理类"""
    @staticmethod
    def handle_text(msg_data):
        """处理文本消息"""
        return ContextType.TEXT,msg_data.get("message",{}).get("content")

    @staticmethod
    def handle_image(msg_data):
        """处理图片消息"""
        image_url = msg_data.get("message",{}).get("content")
        return ContextType.IMAGE,image_url

    @staticmethod
    def handle_video(msg_data):
        """处理视频消息"""
        video_url = msg_data.get("message",{}).get("content")
        return ContextType.VIDEO,video_url

    @staticmethod
    def handle_emotion(msg_data):
        """处理表情消息"""
        emotion_data = msg_data.get("info",{}).get("description")
        return ContextType.EMOTION,emotion_data

    @staticmethod
    def handle_withdraw(msg_data):
        """处理撤回消息"""
        withdraw_hint = msg_data.get("info",{}).get("withdraw_hint")
        return ContextType.WITHDRAW,withdraw_hint

    @staticmethod
    def handle_goods_inquiry(msg_data):
        """处理商品咨询消息"""
        goods_info = {
            "goods_id": msg_data.get("message",{}).get("info",{}).get("goodsID"),##商品ID
            "goods_name": msg_data.get("message",{}).get("info",{}).get("goodsName"),##商品名称
            "goods_price": msg_data.get("message",{}).get("info",{}).get("goodsPrice"),##商品价格
            "goods_thumb_url": msg_data.get("message",{}).get("info",{}).get("goodsThumbUrl"),##商品缩略图
            "link_url": msg_data.get("message",{}).get("info",{}).get("linkUrl"),##商品链接
        }
        return ContextType.GOODS_INQUIRY,goods_info

    @staticmethod
    def handle_goods_spec(msg_data):
        """咨询商品规格"""
        goods_info = {
            "goods_id": msg_data.get("message",{}).get("info",{}).get("data",{}).get("goodsID"),##商品ID
            "goods_name": msg_data.get("message",{}).get("info",{}).get("data",{}).get("goodsName"),##商品名称
            "goods_price": msg_data.get("message",{}).get("info",{}).get("data",{}).get("goodsPrice"),##商品价格
            "goods_spec": msg_data.get("message",{}).get("info",{}).get("data",{}).get("spec"),##商品规格
        }
        return ContextType.GOODS_SPEC,goods_info

    @staticmethod
    def handle_order_info(msg_data):
        """处理订单信息消息"""
        order_info = {
            "order_id": msg_data.get("message",{}).get("info",{}).get("orderSequenceNo"),##订单编号
            "goods_id": msg_data.get("message",{}).get("info",{}).get("goodsID"),##商品ID
            "goods_name": msg_data.get("message",{}).get("info",{}).get("goodsName"),##商品名称
            "afterSalesStatus": msg_data.get("message",{}).get("info",{}).get("afterSalesStatus"),##售后状态
            "afterSalesType": msg_data.get("message",{}).get("info",{}).get("afterSalesType"),##售后类型
            "spec": msg_data.get("message",{}).get("info",{}).get("spec"),##规格
        }
        return ContextType.ORDER_INFO,order_info
    
    @staticmethod
    def handle_mall_system_msg(msg_data):
        """处理商城消息"""
        system_msg = {
            "user_id":msg_data.get("message",{}).get("data",{}).get("user_id"),
        }
        return ContextType.MALL_SYSTEM_MSG,system_msg


    @staticmethod
    def handle_auth(msg_data):
        """处理认证消息"""
        auth_info = {
            "uid":msg_data.get("uid"),
            "result":msg_data.get("auth",{}).get("result"),
            "status":msg_data.get("status"),
        }
        return ContextType.AUTH,auth_info

    @staticmethod
    def handle_transfer(msg_data):
        """处理转接消息"""
        transfer_info = {
            "from_uid":msg_data.get("message",{}).get("from",{}).get("uid"),
            "to_uid":msg_data.get("message",{}).get("to",{}).get("uid")
        }
        return ContextType.TRANSFER,transfer_info
class PDDChatMessage(ChatMessage):
    """拼多多消息实现类"""
    
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg
        self.base_handler = BaseMessageHandler(msg)
        #获取基本信息
        basic_info = self.base_handler.get_basic_info()
        self.msg_id = basic_info.get("msg_id")
        self.nickname = basic_info.get("nickname")
        self.from_user = basic_info.get("from_role")
        self.from_uid = basic_info.get("from_uid")
        self.to_user = basic_info.get("to_role")
        self.to_uid = basic_info.get("to_uid")
        
        # 检查是否非用户消息
        if self.from_user == "mall_cs":
            self.user_msg_type = ContextType.MALL_CS
            self.content = self.msg.get("message",{}).get("content")
            
            return
        # 处理消息
        self._process_message()
        
    def _process_message(self):
        """处理消息"""
        self.msg_type=self.msg.get("response")
        if self.msg_type == "push":
            user_msg_type=self.msg.get("message",{}).get("type")
            if user_msg_type == 0:
                sub_type=self.msg.get("message",{}).get("sub_type")
                if sub_type == 1:
                    self.user_msg_type,self.content = MessageTypeHandler.handle_order_info(self.msg)
                elif sub_type == 0:
                    self.user_msg_type,self.content = MessageTypeHandler.handle_goods_inquiry(self.msg)
                else:
                    self.user_msg_type,self.content = MessageTypeHandler.handle_text(self.msg)
            elif user_msg_type == 1:
                self.user_msg_type,self.content = MessageTypeHandler.handle_image(self.msg)
            elif user_msg_type == 14:
                self.user_msg_type,self.content = MessageTypeHandler.handle_video(self.msg)
            elif user_msg_type == 1002:
                self.user_msg_type,self.content = MessageTypeHandler.handle_withdraw(self.msg)
            elif user_msg_type == 5:
                self.user_msg_type,self.content = MessageTypeHandler.handle_emotion(self.msg)
            elif user_msg_type == 64:
                self.user_msg_type,self.content = MessageTypeHandler.handle_goods_spec(self.msg)
            elif user_msg_type == 24:
                self.user_msg_type,self.content = MessageTypeHandler.handle_transfer(self.msg)
            else:
                self.user_msg_type = ContextType.SYSTEM_STATUS
                self.content = f"不支持的消息类型: {user_msg_type}"
        elif self.msg_type == "auth":
            self.user_msg_type,self.content = MessageTypeHandler.handle_auth(self.msg)
        elif self.msg_type == "mall_system_msg":
            self.user_msg_type,self.content = MessageTypeHandler.handle_mall_system_msg(self.msg)
        else:
            self.user_msg_type = ContextType.SYSTEM_STATUS
            self.content = f"不支持的消息类型: {self.msg_type}"
