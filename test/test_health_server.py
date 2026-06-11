# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
import pytest


@pytest.mark.asyncio
async def test_health_endpoint():
    from aiohttp import ClientSession

    from core.health_server import start_health_server, stop_health_server

    await start_health_server("127.0.0.1", 18081)
    try:
        async with ClientSession() as session:
            async with session.get("http://127.0.0.1:18081/health") as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["status"] == "ok"
                assert "timestamp" in data
    finally:
        await stop_health_server()


@pytest.mark.asyncio
async def test_ready_endpoint_returns_json():
    from aiohttp import ClientSession

    from core.health_server import start_health_server, stop_health_server

    await start_health_server("127.0.0.1", 18082)
    try:
        async with ClientSession() as session:
            async with session.get("http://127.0.0.1:18082/ready") as resp:
                assert resp.status in (200, 503)
                data = await resp.json()
                assert "ready" in data
                assert isinstance(data["ready"], bool)
                assert "handler_chain" in data
                if not data["ready"]:
                    assert "reason" in data
    finally:
        await stop_health_server()


@pytest.mark.asyncio
async def test_ready_requires_token_when_configured(monkeypatch):
    from aiohttp import ClientSession

    from core.health_server import start_health_server, stop_health_server

    monkeypatch.setenv("HEALTH_CHECK_TOKEN", "test-health-secret")
    await start_health_server("127.0.0.1", 18083)
    try:
        async with ClientSession() as session:
            async with session.get("http://127.0.0.1:18083/ready") as resp:
                assert resp.status == 401
            async with session.get(
                "http://127.0.0.1:18083/ready",
                headers={"Authorization": "Bearer test-health-secret"},
            ) as resp:
                assert resp.status in (200, 503)
            async with session.get("http://127.0.0.1:18083/health") as resp:
                assert resp.status == 401
            async with session.get(
                "http://127.0.0.1:18083/health",
                headers={"Authorization": "Bearer test-health-secret"},
            ) as resp:
                assert resp.status == 200
    finally:
        monkeypatch.delenv("HEALTH_CHECK_TOKEN", raising=False)
        await stop_health_server()
