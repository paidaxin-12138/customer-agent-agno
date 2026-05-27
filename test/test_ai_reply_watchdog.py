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


def test_escalate_default_150_sec(monkeypatch):
    monkeypatch.setattr(w.config, "get", lambda k, d=None: d)
    assert w._escalate_after_sec() == 150.0


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
async def test_sleep_until_delivered_exits_early():
    key = "sess_early"
    e = await w.begin_watchdog_turn(key)
    w.mark_delivered(key, e)
    done = await w._sleep_until_delivered(time.monotonic() + 5, key, e)
    assert done is False
