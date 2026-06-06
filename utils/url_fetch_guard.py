"""
出站 HTTP 拉取前的 URL 安全校验（防 SSRF / 内网探测）。

chat_image：聊天图片，沿用 utils.chat_message_html 白名单。
pdd_asset：平台 Logo / 商品 OCR 图，允许拼多多相关 CDN 根域。
"""
from __future__ import annotations

import ipaddress
import socket
from typing import Optional, Tuple
from urllib.parse import urlparse

from utils.chat_message_html import DEFAULT_CHAT_BUBBLE_OPTIONS

_PDD_ASSET_HOST_ROOTS = (
    "pddugc.com",
    "pddpic.com",
    "pinduoduo.com",
    "yangkeduo.com",
)


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
