"""转接消息买家 UID 解析与售后客服优选。"""
import json

from bridge.context import Context, ContextType
from utils.pdd_transfer import (
    format_transfer_system_preview,
    pick_transfer_cs_uid,
    resolve_buyer_uid_from_transfer,
)


def _transfer_context(**overrides):
    raw = {
        "response": "push",
        "message": {
            "type": 24,
            "from": {"role": "mall_cs", "uid": "cs_722406697_111"},
            "to": {"role": "user", "uid": "4216881609"},
            "msg_id": "t1",
        },
    }
    raw.update(overrides.get("raw_patch") or {})
    kwargs = {
        "from_user": "mall_cs",
        "from_uid": "cs_722406697_111",
        "to_user": "user",
        "to_uid": "4216881609",
        "raw_data": raw,
    }
    return Context.create_pinduoduo_context(
        content=json.dumps({"from_uid": "cs_1", "to_uid": "cs_2"}, ensure_ascii=False),
        user_msg_type=ContextType.TRANSFER,
        **kwargs,
    )


def test_resolve_buyer_uid_from_transfer_to_user():
    ctx = _transfer_context()
    assert resolve_buyer_uid_from_transfer(ctx) == "4216881609"


def test_resolve_buyer_uid_from_transfer_info():
    raw = {
        "response": "push",
        "message": {
            "type": 24,
            "from": {"role": "mall_cs", "uid": "1"},
            "to": {"role": "mall_cs", "uid": "2"},
            "info": {"uid": "5047840775"},
        },
    }
    ctx = Context.create_pinduoduo_context(
        content="{}",
        user_msg_type=ContextType.TRANSFER,
        from_user="mall_cs",
        from_uid="1",
        to_user="mall_cs",
        to_uid="2",
        raw_data=raw,
    )
    assert resolve_buyer_uid_from_transfer(ctx) == "5047840775"


def test_format_transfer_system_preview():
    ctx = _transfer_context()
    assert "转接" in format_transfer_system_preview(ctx)


def test_pick_transfer_cs_uid_prefers_config(monkeypatch):
    cs_list = {
        "cs_1_1": {"online": True, "current_sessions": 0},
        "cs_1_99": {"online": True, "current_sessions": 5},
    }

    def _get(key, default=None):
        if key == "chat.preferred_transfer_seller_user_ids":
            return ["99"]
        return default

    monkeypatch.setattr("config.config.get", _get)
    assert pick_transfer_cs_uid(cs_list, "1", "1", exclude_self=True) == "cs_1_99"
