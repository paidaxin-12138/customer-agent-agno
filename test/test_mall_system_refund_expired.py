"""mall_system_msg type=90 快捷退款卡过期解析。"""

from Channel.pinduoduo.pdd_message import MessageTypeHandler
from bridge.context import ContextType


def test_mall_system_refund_card_expired():
    msg = {
        "message": {
            "type": 90,
            "data": {
                "msg_id": "1779863259458",
                "status": 4,
                "text": "已过期",
                "uid": "4216881609",
            },
        }
    }
    ctx_type, content = MessageTypeHandler.handle_mall_system_msg(msg)
    assert ctx_type == ContextType.MALL_SYSTEM_MSG
    assert content["event"] == "refund_card_expired"
    assert content["user_id"] == "4216881609"
    assert content["status"] == 4
