"""出站 URL 拉取安全校验。"""
import socket
from unittest.mock import patch

import pytest

from utils.url_fetch_guard import (
    BlockedFetchError,
    aiohttp_fetch_bytes,
    is_url_safe_to_fetch,
    safe_requests_get,
)


def test_blocks_localhost():
    ok, reason = is_url_safe_to_fetch("http://127.0.0.1:8080/metrics", purpose="chat_image")
    assert not ok
    assert reason == "blocked_host"


def test_blocks_private_lan():
    ok, reason = is_url_safe_to_fetch("http://192.168.1.1/admin", purpose="pdd_asset")
    assert not ok
    assert reason == "blocked_host"


def test_blocks_file_scheme():
    ok, reason = is_url_safe_to_fetch("file:///etc/passwd", purpose="pdd_asset")
    assert not ok
    assert reason == "disallowed_scheme"


def test_allows_pdd_chat_image():
    url = "https://chat-img.pddugc.com/chat-pic-mall-user-v1/2026/foo.jpg"
    ok, reason = is_url_safe_to_fetch(url, purpose="chat_image")
    assert ok, reason


@patch("utils.url_fetch_guard._hostname_resolves_to_blocked", return_value=False)
def test_rejects_random_host_for_chat_image(_mock):
    ok, reason = is_url_safe_to_fetch("https://evil.example.com/a.jpg", purpose="chat_image")
    assert not ok
    assert reason == "not_on_image_allowlist"


def test_allows_pdd_asset_logo():
    ok, reason = is_url_safe_to_fetch(
        "https://img.pddpic.com/mall-logo/shop.png",
        purpose="pdd_asset",
    )
    assert ok, reason


@patch("utils.url_fetch_guard._hostname_resolves_to_blocked", return_value=False)
def test_pdd_asset_rejects_unknown_domain(_mock):
    ok, reason = is_url_safe_to_fetch("https://cdn.example.com/logo.png", purpose="pdd_asset")
    assert not ok
    assert reason == "not_on_pdd_allowlist"


@patch("utils.url_fetch_guard.socket.getaddrinfo")
def test_safe_requests_blocks_dns_rebind_at_connect(mock_getaddrinfo):
    public = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("203.0.113.10", 443))]
    loopback = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))]
    mock_getaddrinfo.side_effect = [public, loopback]

    url = "https://img.pddpic.com/mall-logo/shop.png"
    with pytest.raises(BlockedFetchError):
        safe_requests_get(url, purpose="pdd_asset", timeout=1)


def test_assert_resolved_ips_blocks_loopback_direct():
    from utils.url_fetch_guard import _assert_resolved_ips_allowed

    with pytest.raises(BlockedFetchError):
        _assert_resolved_ips_allowed("127.0.0.1", 80)


@pytest.mark.asyncio
@patch("utils.url_fetch_guard.socket.getaddrinfo")
async def test_aiohttp_connector_blocks_loopback_on_resolve(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
    ]
    url = "https://img.pddpic.com/mall-logo/shop.png"
    with patch(
        "utils.url_fetch_guard.is_url_safe_to_fetch",
        return_value=(True, ""),
    ):
        with pytest.raises((BlockedFetchError, OSError)):
            await aiohttp_fetch_bytes(url, purpose="pdd_asset", timeout_sec=1)
