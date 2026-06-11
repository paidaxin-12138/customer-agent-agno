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
    """未配置 Token 时保持兼容；配置 Token 后 /health、/ready、/metrics 均需 Bearer 认证。"""
    token = _configured_health_token()
    if not token:
        return True
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer ") and auth[7:].strip() == token:
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


def _readiness_require_all_connected() -> bool:
    """True：所有已连接 WS 账号均须有 running consumer；False：至少一个即可（旧行为）。"""
    import os

    raw = os.getenv("READINESS_REQUIRE_ALL_CONNECTED", "")
    if raw.strip():
        return raw.strip().lower() not in ("0", "false", "no")
    try:
        from config import get_config

        return bool(get_config("production.readiness_require_all_connected", True))
    except Exception:
        return True


def _readiness_reconnect_grace_sec() -> float:
    """WS 已连但 consumer 尚未就绪时的宽限秒数，减轻重连瞬间 503 误报。"""
    raw = os.getenv("READINESS_RECONNECT_GRACE_SEC", "").strip()
    if raw:
        try:
            return max(0.0, min(float(raw), 300.0))
        except (TypeError, ValueError):
            return 30.0
    try:
        from config import get_config

        v = get_config("production.readiness_reconnect_grace_sec", 30)
        return max(0.0, min(float(v if v is not None else 30), 300.0))
    except (TypeError, ValueError):
        return 30.0


def _consumer_in_reconnect_grace(status: Any, grace_sec: float) -> bool:
    if grace_sec <= 0:
        return False
    from core.connection_status import ConnectionState

    if status.state == ConnectionState.RECONNECTING:
        return True
    ref = getattr(status, "last_connect_time", None) or getattr(
        status, "connect_time", None
    )
    if ref is None:
        return False
    from datetime import datetime

    try:
        age = (datetime.now() - ref).total_seconds()
    except Exception:
        return False
    return age <= grace_sec


def _evaluate_readiness() -> Tuple[bool, str, Dict[str, Any]]:
    """
    就绪条件：已连接 WebSocket 账号均有对应消费者 running（可配置为至少一个）。
    所有依赖未初始化或异常时安全返回 not ready。
    """
    detail: Dict[str, Any] = {
        "ws_connected": 0,
        "ws_total": 0,
        "consumers_running": [],
        "consumers_not_ready": [],
        "consumers_in_grace": [],
        "readiness_grace_sec": _readiness_reconnect_grace_sec(),
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

    status_by_key = {
        (str(s.shop_id), str(s.user_id)): s for s in connected
    }

    for status in connected:
        queue_name = queue_name_for_account(str(status.shop_id), str(status.user_id))
        consumer = message_consumer_manager.get_consumer(queue_name)
        running = bool(consumer and consumer.is_running())
        entry = {
            "shop_id": status.shop_id,
            "user_id": status.user_id,
            "queue_name": queue_name,
            "running": running,
            "ws_state": status.state.value if hasattr(status.state, "value") else str(status.state),
        }
        detail["consumers_running"].append(entry)
        if not running:
            detail["consumers_not_ready"].append(entry)

    running_count = sum(1 for e in detail["consumers_running"] if e["running"])
    if running_count == 0:
        return False, "no_running_consumer_for_connected_shop", detail

    if _readiness_require_all_connected():
        if detail["consumers_not_ready"]:
            grace_sec = detail["readiness_grace_sec"]
            outside_grace: list = []
            for entry in detail["consumers_not_ready"]:
                st = status_by_key.get(
                    (str(entry["shop_id"]), str(entry["user_id"]))
                )
                in_grace = bool(st and _consumer_in_reconnect_grace(st, grace_sec))
                entry["in_grace"] = in_grace
                if in_grace:
                    detail["consumers_in_grace"].append(entry)
                else:
                    outside_grace.append(entry)
            if not outside_grace and running_count >= 1:
                detail["readiness_grace_active"] = True
                return True, "reconnect_grace", detail
            return False, "not_all_connected_shops_ready", detail
        return True, "", detail

    return True, "", detail


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
        elif reason == "reconnect_grace":
            body["readiness_grace_active"] = True
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
    app.router.add_get("/health", _with_health_auth(_health_handler))
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
