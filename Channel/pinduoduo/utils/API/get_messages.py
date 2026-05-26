"""预留：从拼多多平台拉取会话/历史消息（需对接具体 plateau 接口）。"""
from typing import Any, Dict, List


class GetMessages:
    """不继承 BaseRequest，避免在未登录上下文中实例化失败。"""

    def __init__(self, shop_id: str = "", user_id: str = "", channel_name: str = "pinduoduo"):
        self.shop_id = shop_id
        self.user_id = user_id
        self.channel_name = channel_name

    def get_chat_messages(self, buyer_uid: str, page: int = 1, page_size: int = 50) -> List[Dict[str, Any]]:
        _ = (buyer_uid, page, page_size)
        return []

    def get_all_sessions(self) -> List[Dict[str, Any]]:
        return []
