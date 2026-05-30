"""本地健康检查 HTTP 服务（aiohttp）。"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

from aiohttp import web

from core.app_metrics import get_metrics_payload
from utils.logger_loguru import get_logger

_logger = get_logger("HealthServer")
_runner: Optional[web.AppRunner] = None
_site: Optional[web.TCPSite] = None


async def _health_handler(_request: web.Request) -> web.Response:
    body = {"status": "ok", "timestamp": int(time.time())}
    return web.json_response(body)


def _evaluate_readiness() -> Tuple[bool, str, Dict[str, Any]]:
    """
    就绪条件：至少一个店铺 WebSocket 已连接，且对应 pdd_{shop_id} 消费者正在运行。
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
        from Message.core.consumer import message_consumer_manager
    except Exception as e:
        _logger.debug("readiness: consumer manager unavailable: {}", e)
        return False, "consumer_manager_unavailable", detail

    for status in connected:
        queue_name = f"pdd_{status.shop_id}"
        consumer = message_consumer_manager.get_consumer(queue_name)
        running = bool(consumer and consumer.is_running())
        detail["consumers_running"].append(
            {"shop_id": status.shop_id, "queue_name": queue_name, "running": running}
        )
        if running:
            return True, "", detail

    return False, "no_running_consumer_for_connected_shop", detail


async def _ready_handler(_request: web.Request) -> web.Response:
    try:
        ready, reason, detail = _evaluate_readiness()
        body: Dict[str, Any] = {
            "ready": ready,
            "timestamp": int(time.time()),
            **detail,
        }
        if not ready:
            body["reason"] = reason
        status = 200 if ready else 503
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


async def start_health_server(host: str = "127.0.0.1", port: int = 8080) -> None:
    global _runner, _site
    if _site is not None:
        return
    app = web.Application()
    app.router.add_get("/health", _health_handler)
    app.router.add_get("/ready", _ready_handler)
    app.router.add_get("/metrics", _metrics_handler)
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
