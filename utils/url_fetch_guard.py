# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
出站 HTTP 拉取前的 URL 安全校验（防 SSRF / 内网探测）。

chat_image：聊天图片，沿用 utils.chat_message_html 白名单。
pdd_asset：平台 Logo / 商品 OCR 图，允许拼多多相关 CDN 根域。

连接前会再次解析 DNS 并校验 IP，缩小 DNS 重绑定窗口。
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

from utils.chat_message_html import DEFAULT_CHAT_BUBBLE_OPTIONS

_PDD_ASSET_HOST_ROOTS = (
    "pddugc.com",
    "pddpic.com",
    "pinduoduo.com",
    "yangkeduo.com",
)


class BlockedFetchError(Exception):
    """URL 或解析 IP 未通过安全校验。"""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def _host_on_roots(hostname: str, roots: Tuple[str, ...]) -> bool:
    host = (hostname or "").lower().rstrip(".")
    if not host:
        return False
    for root in roots:
        r = root.lower().lstrip(".")
        if host == r or host.endswith("." + r):
            return True
    return False


def _ip_blocked(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True
    if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved:
        return True
    if ip.is_multicast:
        return True
    return False


def _hostname_resolves_to_blocked(hostname: str) -> bool:
    host = (hostname or "").strip().lower()
    if not host:
        return True
    try:
        ip = ipaddress.ip_address(host)
        return _ip_blocked(str(ip))
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return True
    if not infos:
        return True
    for info in infos:
        addr = info[4][0]
        if _ip_blocked(addr):
            return True
    return False


def _assert_resolved_ips_allowed(hostname: str, port: Optional[int] = None) -> None:
    """连接前再次解析 hostname，拒绝内网/回环等地址。"""
    host = (hostname or "").strip().lower()
    if not host:
        raise BlockedFetchError("missing_host")
    try:
        ip = ipaddress.ip_address(host)
        if _ip_blocked(str(ip)):
            raise BlockedFetchError("blocked_host")
        return
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(
            host,
            port or 0,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise BlockedFetchError("dns_resolve_failed") from exc
    if not infos:
        raise BlockedFetchError("dns_empty")
    for info in infos:
        addr = info[4][0]
        if _ip_blocked(addr):
            raise BlockedFetchError("blocked_host")


def is_url_safe_to_fetch(url: str, *, purpose: str = "chat_image") -> Tuple[bool, str]:
    """
    校验 URL 是否允许本机发起 GET。

    Returns:
        (allowed, reason_if_denied)
    """
    raw = (url or "").strip()
    if not raw:
        return False, "empty_url"
    if len(raw) > 2048:
        return False, "url_too_long"

    low = raw.lower()
    if low.startswith(("javascript:", "data:", "file:", "ftp:")):
        return False, "disallowed_scheme"

    try:
        parsed = urlparse(raw)
    except Exception:
        return False, "invalid_url"

    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return False, "disallowed_scheme"

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return False, "missing_host"

    if _hostname_resolves_to_blocked(hostname):
        return False, "blocked_host"

    if purpose == "chat_image":
        # 出站拉取比气泡展示更严：必须命中 CDN 根域，不能仅凭 .jpg 后缀放行任意站
        if not _host_on_roots(hostname, DEFAULT_CHAT_BUBBLE_OPTIONS.image_host_allowlist):
            return False, "not_on_image_allowlist"
        return True, ""

    if purpose == "pdd_asset":
        if _host_on_roots(hostname, _PDD_ASSET_HOST_ROOTS):
            return True, ""
        return False, "not_on_pdd_allowlist"

    return False, "unknown_purpose"


def filter_safe_fetch_url(url: Optional[str], *, purpose: str = "chat_image") -> Optional[str]:
    """允许则返回原 URL，否则 None。"""
    if not url:
        return None
    ok, _ = is_url_safe_to_fetch(url, purpose=purpose)
    return url if ok else None


def _parsed_port(parsed) -> int:
    if parsed.port:
        return int(parsed.port)
    return 443 if (parsed.scheme or "").lower() == "https" else 80


def safe_requests_get(
    url: str,
    *,
    purpose: str = "chat_image",
    timeout: float = 10,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
):
    """requests GET：校验 URL + 连接前再次校验解析 IP。"""
    import requests
    from requests.adapters import HTTPAdapter

    ok, reason = is_url_safe_to_fetch(url, purpose=purpose)
    if not ok:
        raise BlockedFetchError(reason)

    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise BlockedFetchError("missing_host")

    class _SafeHTTPAdapter(HTTPAdapter):
        def send(self, request, **send_kwargs):
            req_host = urlparse(request.url).hostname
            req_port = _parsed_port(urlparse(request.url))
            if req_host:
                _assert_resolved_ips_allowed(req_host, req_port)
            return super().send(request, **send_kwargs)

    session = requests.Session()
    adapter = _SafeHTTPAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session.get(url, timeout=timeout, headers=headers, **kwargs)


class SafeTCPConnector:
    """aiohttp TCPConnector：在 DNS 解析后校验 IP。"""

    @staticmethod
    def create(**kwargs: Any):
        import aiohttp

        class _Connector(aiohttp.TCPConnector):
            async def _resolve_host(self, host, port, traces=None):
                results = await super()._resolve_host(host, port, traces)
                for res in results:
                    ip = res["host"] if isinstance(res, dict) else res[4][0]
                    if _ip_blocked(ip):
                        raise BlockedFetchError("blocked_host")
                return results

        return _Connector(**kwargs)


async def aiohttp_fetch_bytes(
    url: str,
    *,
    purpose: str = "chat_image",
    headers: Optional[Dict[str, str]] = None,
    timeout_sec: float = 12,
) -> bytes:
    """aiohttp GET body：校验 URL + SafeTCPConnector。"""
    import aiohttp

    ok, reason = is_url_safe_to_fetch(url, purpose=purpose)
    if not ok:
        raise BlockedFetchError(reason)

    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    connector = SafeTCPConnector.create()
    async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
        async with session.get(url, headers=headers) as response:
            if response.status >= 400:
                raise ValueError(f"HTTP {response.status}")
            return await response.read()
