"""Turn Abort Phase D：tool 副作用防护 + registry 驱逐 abort。"""
from __future__ import annotations

import inspect
from unittest.mock import MagicMock, patch

from core.turn_abort import (
    TurnAbortRegistry,
    reset_current_turn_abort,
    set_current_turn_abort,
)


def _transfer_deps() -> dict:
    return {
        "shop_id": "1",
        "user_id": "u",
        "from_uid": "b",
        "buyer_message": "转人工客服",
    }


def test_registry_eviction_aborts_active_signal():
    reg = TurnAbortRegistry(max_sessions=2)
    s1 = reg.begin_turn("session/a")
    s2 = reg.begin_turn("session/b")
    assert s1 is not None and s2 is not None
    assert not s1.is_aborted()
    assert not s2.is_aborted()

    s3 = reg.begin_turn("session/c")

    assert s1.is_aborted()
    assert s1.reason() == "registry_evicted"
    assert reg.get_active("session/a") is None
    assert reg.get_active("session/c") is s3
    assert not s2.is_aborted()
    assert not s3.is_aborted()


def test_registry_lru_evicts_least_recently_used():
    reg = TurnAbortRegistry(max_sessions=2)
    s1 = reg.begin_turn("session/a")
    reg.end_turn("session/a", s1.turn_id)

    s2 = reg.begin_turn("session/b")
    s3a = reg.begin_turn("session/a")
    reg.end_turn("session/a", s3a.turn_id)

    s3 = reg.begin_turn("session/c")

    assert s2 is not None
    assert s2.is_aborted()
    assert s2.reason() == "registry_evicted"
    assert reg.get_active("session/b") is None
    assert reg.get_active("session/c") is s3


def test_end_turn_clears_active_without_aborting_completed():
    reg = TurnAbortRegistry()
    sig = reg.begin_turn("s/u/b")
    assert sig is not None
    reg.end_turn("s/u/b", sig.turn_id)
    assert reg.get_active("s/u/b") is None
    assert not sig.is_aborted()

    s2 = reg.begin_turn("s/u/b")
    assert s2 is not None
    assert not s2.is_aborted()
    assert s2.epoch == 2


def test_transfer_conversation_skips_move_when_aborted_before_mms():
    from Agent.CustomerAgent.tools.move_conversation import transfer_conversation

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("1/u/b")
    tok = set_current_turn_abort(sig)

    run_ctx = MagicMock()
    run_ctx.dependencies = _transfer_deps()

    with patch(
        "Agent.CustomerAgent.tools.move_conversation.SendMessage"
    ) as sm_cls:
        sm = sm_cls.return_value

        def _abort_then_list():
            sig.abort("arun_timeout")
            return {"cs_1_2": {"online": True, "current_sessions": 0}}

        sm.getAssignCsList.side_effect = _abort_then_list
        fn = inspect.unwrap(transfer_conversation.entrypoint)
        result = fn(run_ctx, "1", "u", "b")

        sm.move_conversation.assert_not_called()

    reset_current_turn_abort(tok)
    assert "arun_timeout" in str(result)


def test_send_goods_link_skips_card_when_aborted_before_mms():
    from Agent.CustomerAgent.tools.send_goods_link import send_goods_link

    reg = TurnAbortRegistry()
    sig = reg.begin_turn("1/u/b")
    tok = set_current_turn_abort(sig)

    run_ctx = MagicMock()
    run_ctx.dependencies = {
        "shop_id": "1",
        "user_id": "u",
        "from_uid": "b",
    }

    with patch(
        "Agent.CustomerAgent.tools.send_goods_link.validate_shop_goods_id",
        side_effect=lambda *a, **k: (sig.abort("arun_timeout") or (True, "")),
    ), patch("Agent.CustomerAgent.tools.send_goods_link.SendMessage") as sm_cls:
        sm = sm_cls.return_value
        fn = inspect.unwrap(send_goods_link.entrypoint)
        result = fn(run_ctx, "b", 12345, "1", "u")
        sm.send_mallGoodsCard.assert_not_called()

    reset_current_turn_abort(tok)
    assert "arun_timeout" in str(result)
