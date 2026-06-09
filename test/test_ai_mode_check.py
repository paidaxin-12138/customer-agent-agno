# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""ai_mode 检查：重试、fail_open、统计。"""
from unittest.mock import MagicMock, patch

import pytest

from bridge.context import Context, ContextType
from utils import ai_mode_check


@pytest.fixture(autouse=True)
def _reset_stats():
    ai_mode_check._fail_count = 0
    ai_mode_check._recover_count = 0
    yield


def test_missing_metadata_defaults_true():
    ctx = Context(type=ContextType.TEXT, content="hi")
    assert ai_mode_check.is_ai_mode_enabled(ctx, {}) is True


def _cfg_mock():
    return MagicMock(
        get=lambda k, d=None: {
            "chat.ai_mode_check_retries": 1,
            "chat.ai_mode_check_retry_delay_sec": 0.01,
            "chat.ai_mode_check_fail_open": True,
        }.get(k, d)
    )


def test_db_failure_fail_open(monkeypatch):
    monkeypatch.setattr("utils.ai_mode_check.config", _cfg_mock())
    ctx = Context(type=ContextType.TEXT, content="hi")
    meta = {
        "channel_name": "pinduoduo",
        "shop_id": "s1",
        "user_id": "u1",
        "from_uid": "b1",
    }
    with patch(
        "database.db_manager.db_manager.get_account",
        side_effect=RuntimeError("db down"),
    ):
        assert ai_mode_check.is_ai_mode_enabled(ctx, meta) is True
    assert ai_mode_check.get_ai_mode_check_stats()["fail"] == 1


def test_retry_recovers(monkeypatch):
    monkeypatch.setattr(
        "utils.ai_mode_check.config",
        MagicMock(
            get=lambda k, d=None: {
                "chat.ai_mode_check_retries": 3,
                "chat.ai_mode_check_retry_delay_sec": 0.01,
                "chat.ai_mode_check_fail_open": False,
            }.get(k, d)
        ),
    )
    calls = {"n": 0}

    def flaky_resolve(*_a, **_k):
        calls["n"] += 1
        if calls["n"] < 2:
            raise OSError("busy")
        return 1

    from database.session_store import SessionSummary

    summary = SessionSummary(
        session_id=1,
        account_id=1,
        buyer_uid="b1",
        buyer_nickname="",
        preview="",
        unread_count=0,
        ai_mode=False,
        updated_at=0.0,
    )
    ctx = Context(type=ContextType.TEXT, content="hi")
    meta = {
        "channel_name": "pinduoduo",
        "shop_id": "s1",
        "user_id": "u1",
        "from_uid": "b1",
    }
    with patch(
        "database.session_store.resolve_session_id", side_effect=flaky_resolve
    ), patch(
        "database.session_store.load_session_summary", return_value=summary
    ):
        assert ai_mode_check.is_ai_mode_enabled(ctx, meta) is False
    assert ai_mode_check.get_ai_mode_check_stats()["recovered_after_retry"] >= 1
