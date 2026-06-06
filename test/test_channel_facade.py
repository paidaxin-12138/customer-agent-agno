"""channel_facade UI 门面单测。"""
from __future__ import annotations

import pytest

from core.channel_facade import (
    account_display_status,
    create_pdd_channel,
    list_connected_accounts,
)
from core.connection_status import ConnectionState, ConnectionStatusManager


@pytest.fixture(autouse=True)
def _clear_status():
    ConnectionStatusManager().clear_all()
    yield
    ConnectionStatusManager().clear_all()


def test_create_pdd_channel_returns_instance():
    ch = create_pdd_channel(status_manager=ConnectionStatusManager())
    assert ch.__class__.__name__ == "PDDChannel"
    assert ch.channel_name == "pinduoduo"


def test_account_display_status_connected():
    mgr = ConnectionStatusManager()
    mgr.update_status("shop1", "user1", "cs", ConnectionState.CONNECTED)
    assert account_display_status("shop1", "user1") == "在线"
    assert len(list_connected_accounts()) == 1


def test_account_display_status_connecting():
    mgr = ConnectionStatusManager()
    mgr.update_status("shop1", "user1", "cs", ConnectionState.CONNECTING)
    assert account_display_status("shop1", "user1") == "连接中"


def test_account_display_status_missing():
    assert account_display_status("shop1", "user1") is None
