# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""本地健康检查 HTTP 服务（aiohttp）。"""
from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional, Tuple

from aiohttp import web

from core.app_metrics import get_handler_chain_metrics, get_metrics_payload
from utils.logger_loguru import get_logger

_logger = get_logger("HealthServer")
_runner: Optional[web.AppRunner] = None
_site: Optional[web.TCPSite] = None


def _configured_health_token() -> str:
    token = (os.getenv("HEALTH_CHECK_TOKEN") or "").strip()
    if token:
        return token
    try:
        from config import get_config

        return str(get_config("production.health_token") or "").strip()
    except Exception:
        return ""


def _health_auth_ok(request: web.Request) -> bool:
    """未配置 Token 时保持兼容；/ready、/metrics 在配置 Token 后需认证。"""
    token = _configured_health_token()
    if not token:
        return True
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer ") and auth[7:].strip() == token:
        return True
    if (request.query.get("token") or "").strip() == token:
        return True
    return False


def _with_health_auth(handler):
    async def wrapped(request: web.Request) -> web.Response:
        if not _health_auth_ok(request):
            return web.json_response(
                {"error": "unauthorized", "timestamp": int(time.time())},
                status=401,
            )
        return await handler(request)

    return wrapped


def _require_handler_chain_for_ready() -> bool:
    return os.getenv("READINESS_REQUIRE_HANDLERS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _evaluate_handler_chain() -> Tuple[bool, str, Dict[str, Any]]:
    detail = get_handler_chain_metrics()
    if detail.get("ok"):
        return True, "", detail
    missing = detail.get("missing") or []
    return False, "handler_chain_degraded", {**detail, "missing_handlers": missing}


async def _health_handler(_request: web.Request) -> web.Response:
    body = {"status": "ok", "timestamp": int(time.time())}
    return web.json_response(body)


def _evaluate_readiness() -> Tuple[bool, str, Dict[str, Any]]:
    """
    就绪条件：至少一个账号 WebSocket 已连接，且对应 pdd_{shop_id}_{user_id} 消费者正在运行。
    所有依赖未初始化或异常时安全返回 not ready。
    """
    detail: Dict[str, Any] = {
        "ws_connected": 0,
        "ws_total": 0,
        "consumers_running": [],
    }
    try:
        from core.connection_status import ConnectionState, ConnectionStatusManager

        statuses = ConnectionStatusManager().get_all_status()
        detail["ws_total"] = len(statuses)
        connected = [s for s in statuses if s.state == ConnectionState.CONNECTED]
        detail["ws_connected"] = len(connected)
    except Exception as e:
        _logger.debug("readiness: connection status unavailable: {}", e)
        return False, "connection_status_unavailable", detail

    if detail["ws_total"] == 0:
        return False, "no_connection_registered", detail
    if detail["ws_connected"] == 0:
        return False, "no_websocket_connected", detail

    try:
        from Channel.pinduoduo.ws_config import queue_name_for_account
        from Message.core.consumer import message_consumer_manager
    except Exception as e:
        _logger.debug("readiness: consumer manager unavailable: {}", e)
        return False, "consumer_manager_unavailable", detail

    for status in connected:
        queue_name = queue_name_for_account(str(status.shop_id), str(status.user_id))
        consumer = message_consumer_manager.get_consumer(queue_name)
        running = bool(consumer and consumer.is_running())
        detail["consumers_running"].append(
            {
                "shop_id": status.shop_id,
                "user_id": status.user_id,
                "queue_name": queue_name,
                "running": running,
            }
        )
        if running:
            return True, "", detail

    return False, "no_running_consumer_for_connected_shop", detail


async def _ready_handler(_request: web.Request) -> web.Response:
    try:
        handler_ok, handler_reason, handler_detail = _evaluate_handler_chain()
        ready, reason, detail = _evaluate_readiness()
        body: Dict[str, Any] = {
            "ready": ready and handler_ok,
            "timestamp": int(time.time()),
            "handler_chain": handler_detail,
            **detail,
        }
        if not ready:
            body["reason"] = reason
        elif not handler_ok and _require_handler_chain_for_ready():
            body["reason"] = handler_reason
        status = 200 if body["ready"] else 503
        return web.json_response(body, status=status)
    except Exception as e:
        _logger.warning("readiness handler error: {}", e)
        return web.json_response(
            {"ready": False, "reason": "readiness_check_error", "timestamp": int(time.time())},
            status=503,
        )


async def _metrics_handler(_request: web.Request) -> web.Response:
    payload = {"status": "ok", "timestamp": int(time.time()), **get_metrics_payload()}
    return web.json_response(payload)


def _is_loopback_host(host: str) -> bool:
    h = (host or "").strip().lower()
    return h in ("127.0.0.1", "::1", "localhost")


async def start_health_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    global _runner, _site
    if _site is not None:
        return
    if not _is_loopback_host(host) and not _configured_health_token():
        import os

        strict = os.getenv("STRICT_CONFIG", "").strip() in ("1", "true", "yes")
        msg = (
            f"health_host={host} 非本机地址且未配置 HEALTH_CHECK_TOKEN，"
            "拒绝启动健康检查服务"
        )
        if strict:
            raise RuntimeError(msg)
        _logger.error("{}（设置 HEALTH_CHECK_TOKEN 或绑定 127.0.0.1）", msg)
        return
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _with_health_auth(_ready_handler))
    app.router.add_get("/metrics", _with_health_auth(_metrics_handler))
    _runner = web.AppRunner(app)
    await _runner.setup()
    _site = web.TCPSite(_runner, host, port)
    await _site.start()
    _logger.info(
        "健康检查已启动 http://{}:{}/health , http://{}:{}/ready",
        host,
        port,
        host,
        port,
    )


async def stop_health_server() -> None:
    global _runner, _site
    if _runner:
        await _runner.cleanup()
    _runner = None
    _site = None
