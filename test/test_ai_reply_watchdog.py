# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
import asyncio
import time

import pytest

import importlib

w = importlib.import_module("Message.handlers.ai_reply_watchdog")


@pytest.mark.asyncio
async def test_watchdog_epoch_increments_and_mark_delivered():
    key = "pinduoduo:test_shop:test_seller:test_buyer"
    e1 = await w.begin_watchdog_turn(key)
    assert e1 >= 1
    e2 = await w.begin_watchdog_turn(key)
    assert e2 == e1 + 1
    w.mark_delivered(key, e2)
    assert w._is_delivered(key, e2)
    assert not w._is_delivered(key, e2 + 1)
    assert w.was_recently_replied(key, within_sec=300)


def test_was_recently_replied_expires(monkeypatch):
    key = "pinduoduo:s:u:b"
    base = 1000.0
    monkeypatch.setattr(w.time, "monotonic", lambda: base)
    w.mark_delivered(key, 1)
    assert w.was_recently_replied(key, within_sec=60) is True
    monkeypatch.setattr(w.time, "monotonic", lambda: base + 61.0)
    assert w.was_recently_replied(key, within_sec=60) is False


def test_escalate_default_150_sec(monkeypatch):
    monkeypatch.setattr(w.config, "get", lambda k, d=None: d)
    assert w._escalate_after_sec() == 150.0


def test_escalate_fallback_to_retry_sec(monkeypatch):
    def fake_get(k, d=None):
        if k == "chat.ai_watchdog_escalate_sec":
            return None
        if k == "chat.ai_watchdog_retry_sec":
            return 60
        return d

    monkeypatch.setattr(w.config, "get", fake_get)
    assert w._escalate_after_sec() == 60.0


@pytest.mark.asyncio
async def test_escalated_flag():
    key = "sess_esc"
    e = await w.begin_watchdog_turn(key)
    w.mark_escalated(key, e)
    assert w.is_escalated(key, e)


def test_buyer_notice_ai_timeout_default(monkeypatch):
    monkeypatch.setattr(
        w.config,
        "get",
        lambda k, d=None: "" if k == "chat.ai_watchdog_escalate_notice" else d,
    )
    assert w._buyer_notice_for_escalation("ai_timeout", None) == "不好意思亲亲，让你久等了"
    assert w._buyer_notice_for_escalation("ai_failed", None) == w._DEFAULT_ESCALATE_NOTICE


@pytest.mark.asyncio
async def test_stale_outbound_does_not_cancel_current_watchdog():
    """延迟出站携带旧 epoch 时，不得取消当前轮次 watchdog。"""
    key = "pinduoduo:shop:seller:buyer"
    e1 = await w.begin_watchdog_turn(key)
    e2 = await w.begin_watchdog_turn(key)
    assert e2 == e1 + 1

    w.notify_outbound_reply(
        metadata={
            "shop_id": "shop",
            "user_id": "seller",
            "from_uid": "buyer",
            "channel_name": "pinduoduo",
            "_watchdog_epoch": e1,
        }
    )
    assert w._is_delivered(key, e1)
    assert not w._is_delivered(key, e2)
    w.schedule_inbound_watchdog(key, e2)
    assert key in w._tasks
    assert w._epoch.get(key) == e2


@pytest.mark.asyncio
async def test_outbound_with_matching_epoch_cancels_watchdog():
    key = "pinduoduo:shop2:seller2:buyer2"
    epoch = await w.begin_watchdog_turn(key)
    w.notify_outbound_reply(
        metadata={
            "shop_id": "shop2",
            "user_id": "seller2",
            "from_uid": "buyer2",
            "channel_name": "pinduoduo",
            "_watchdog_epoch": epoch,
        }
    )
    assert w._is_delivered(key, epoch)
    assert key not in w._tasks


@pytest.mark.asyncio
async def test_sleep_until_delivered_exits_early():
    key = "sess_early"
    e = await w.begin_watchdog_turn(key)
    w.mark_delivered(key, e)
    done = await w._sleep_until_delivered(time.monotonic() + 5, key, e)
    assert done is False
