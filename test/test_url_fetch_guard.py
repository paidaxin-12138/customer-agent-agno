"""出站 URL 拉取安全校验。"""
from unittest.mock import patch

import pytest

from utils.url_fetch_guard import is_url_safe_to_fetch


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
