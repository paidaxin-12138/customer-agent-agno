"""快捷退款卡 type=19 / type=90 消息解析。"""

from Channel.pinduoduo.pdd_message import MessageTypeHandler, PDDChatMessage
from bridge.context import ContextType


def test_mall_system_refund_card_expired_status_int():
    msg = {
        "response": "mall_system_msg",
        "message": {
            "type": 90,
            "data": {"msg_id": "1", "status": 4, "text": "已过期", "uid": "99"},
        },
    }
    _, content = MessageTypeHandler.handle_mall_system_msg(msg)
    assert content["event"] == "refund_card_expired"
    assert content["user_id"] == "99"


def test_refund_card_push_valid_mstate_status_0():
    from Channel.pinduoduo.utils.API.chat_orders import refund_card_push_expired

    assert not refund_card_push_expired(
        {"expire_text": ""},
        {"expire_text": "", "status": 0},
    )


def test_refund_card_push_expired_mstate_status_1():
    from Channel.pinduoduo.utils.API.chat_orders import refund_card_push_expired

    assert refund_card_push_expired(
        {"expire_text": "已过期"},
        {"expire_text": "已过期", "status": 1, "text": "等待消费者确认"},
    )


def test_mall_cs_ask_refund_card_push_expired():
    raw = {
        "response": "push",
        "message": {
            "type": 19,
            "msg_id": "card1",
            "template_name": "ask_refund_apply",
            "from": {"role": "mall_cs", "uid": "1"},
            "to": {"role": "user", "uid": "4216881609"},
            "content": "[商家想帮您申请快捷退款]",
            "info": {
                "card_id": "ask_refund_apply",
                "goods_info": {"order_sequence_no": "260527-006427778640457"},
                "state": {"expire_text": "已过期", "status": 0},
                "mstate": {"expire_text": "已过期", "status": 1},
            },
        },
    }
    pdd = PDDChatMessage(raw)
    assert pdd.user_msg_type == ContextType.MALL_CS
    assert pdd.content["event"] == "ask_refund_card_push"
    assert pdd.content["expire_text"] == "已过期"
    assert pdd.content["order_sn"] == "260527-006427778640457"
