# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""应用退出清理。"""
import asyncio

from core import app_shutdown


def test_shutdown_idempotent(monkeypatch):
    app_shutdown._done = False
    calls = {"auto": 0, "consumer": 0}

    monkeypatch.setattr(
        "ui.auto_reply_ui.auto_reply_manager.stop_all",
        lambda: calls.__setitem__("auto", calls["auto"] + 1),
    )

    class _FakeConsumerMgr:
        async def stop_all(self):
            calls["consumer"] += 1

    monkeypatch.setattr(
        "Message.core.consumer.message_consumer_manager",
        _FakeConsumerMgr(),
    )

    def _run(coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    monkeypatch.setattr("core.app_shutdown.asyncio.run", _run)
    monkeypatch.setattr(
        "core.pdd_channel_registry.iter_registered_channels",
        lambda: [],
    )
    monkeypatch.setattr(
        "Message.handlers.ai_reply_watchdog.cancel_all_watchdogs",
        lambda: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        "core.production_services.stop_production_background_services",
        lambda: None,
    )

    app_shutdown.shutdown_application()
    app_shutdown.shutdown_application()
    assert calls["auto"] == 1
    assert calls["consumer"] == 1
