# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
通过 Playwright 在商家后台页面上下文中拉取会话列表（latest_conversations）。

使用「商品管理」页而非 chat-merchant，避免与浏览器/WebSocket 抢接待连接。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from config import get_config
from utils.async_helper import run_async_in_thread
from utils.logger_loguru import get_logger

logger = get_logger("MmsChatBrowser")

LATEST_CONVERSATIONS_URL = (
    "https://mms.pinduoduo.com/plateau/chat/latest_conversations"
)
GOODS_LIST_PAGE_URL = "https://mms.pinduoduo.com/goods/goods_list"


class MmsChatBrowserSession:
    """复用浏览器上下文拉取 MMS 会话列表（Cookie 来自数据库）。"""

    def __init__(
        self,
        *,
        shop_id: str,
        user_id: str,
        account_name: str,
        cookies: Dict[str, Any],
        user_agent: Optional[str] = None,
        headless: Optional[bool] = None,
    ) -> None:
        self.shop_id = str(shop_id)
        self.user_id = str(user_id)
        self.account_name = account_name or "unknown"
        self.cookies = dict(cookies or {})
        self.user_agent = (user_agent or "").strip() or (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
        )
        self.headless = (
            bool(get_config("chat.mms_session_sync_browser_headless", True))
            if headless is None
            else headless
        )
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._opened = False
        self._page_ready = False

    @classmethod
    def from_account_row(cls, row: Dict[str, Any]) -> "MmsChatBrowserSession":
        from database.db_manager import db_manager

        shop_id = str(row.get("platform_shop_id") or row.get("shop_id") or "")
        user_id = str(row.get("seller_user_id") or row.get("user_id") or "")
        channel_name = str(row.get("channel_name") or "pinduoduo")
        acc = db_manager.get_account(channel_name, shop_id, user_id) or row
        cookies = acc.get("cookies") or {}
        if isinstance(cookies, str):
            try:
                cookies = json.loads(cookies)
            except json.JSONDecodeError:
                cookies = {}
        from Channel.pinduoduo.utils.base_request import BaseRequest

        api = BaseRequest(shop_id, user_id, channel_name)
        return cls(
            shop_id=shop_id,
            user_id=user_id,
            account_name=str(acc.get("username") or row.get("username") or ""),
            cookies=cookies if isinstance(cookies, dict) else {},
            user_agent=(api.default_headers or {}).get("User-Agent"),
        )

    def _playwright_cookies(self) -> List[dict]:
        out: List[dict] = []
        for name, value in self.cookies.items():
            if not name or str(name).startswith("___"):
                continue
            out.append(
                {
                    "name": str(name),
                    "value": str(value),
                    "domain": ".pinduoduo.com",
                    "path": "/",
                }
            )
        return out

    async def open(self) -> None:
        if self._opened:
            return
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        self._context = await self._browser.new_context(user_agent=self.user_agent)
        await self._context.add_cookies(self._playwright_cookies())
        self._page = await self._context.new_page()
        self._opened = True
        logger.debug(
            "MMS 会话同步浏览器已启动: {} (shop={})",
            self.account_name,
            self.shop_id,
        )

    async def close(self) -> None:
        for closer in (
            self._context.close if self._context else None,
            self._browser.close if self._browser else None,
            self._playwright.stop if self._playwright else None,
        ):
            if closer is None:
                continue
            try:
                await closer()
            except Exception as e:
                logger.debug("关闭 MMS 会话浏览器: {}", e)
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._opened = False
        self._page_ready = False

    async def _ensure_goods_page(self) -> None:
        assert self._page is not None
        if self._page_ready:
            return
        await self._page.goto(
            GOODS_LIST_PAGE_URL,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        self._page_ready = True
        await asyncio.sleep(0.6)

    async def fetch_latest_conversations_raw(
        self,
        *,
        offset: int = 0,
        size: int = 50,
    ) -> dict:
        await self.open()
        assert self._page is not None
        await self._ensure_goods_page()
        offset = max(0, int(offset))
        size = max(1, min(int(size), 100))
        data = await self._page.evaluate(
            """async (payload) => {
                const resp = await fetch(
                    'https://mms.pinduoduo.com/plateau/chat/latest_conversations',
                    {
                        method: 'POST',
                        credentials: 'include',
                        headers: {
                            'accept': 'application/json, text/plain, */*',
                            'content-type': 'application/json;charset=UTF-8',
                        },
                        body: JSON.stringify(payload),
                    }
                );
                return await resp.json();
            }""",
            {"data": {"offset": offset, "size": size}, "client": 1},
        )
        if not isinstance(data, dict):
            raise RuntimeError("latest_conversations 返回非 JSON 对象")
        if data.get("success") is not True:
            err = str(
                data.get("error_msg")
                or data.get("errorMsg")
                or data.get("error_code")
                or "latest_conversations 失败"
            )
            if "会话已过期" in err or data.get("error_code") == 43001:
                raise RuntimeError(
                    "拼多多商家后台登录已过期，请在「用户管理」重新登录后再同步会话。"
                )
            raise RuntimeError(err)
        return data

    def fetch_latest_conversations_raw_sync(
        self,
        *,
        offset: int = 0,
        size: int = 50,
    ) -> dict:
        return run_async_in_thread(
            self.fetch_latest_conversations_raw(offset=offset, size=size)
        )

    async def __aenter__(self) -> "MmsChatBrowserSession":
        await self.open()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    def __enter__(self) -> "MmsChatBrowserSession":
        run_async_in_thread(self.open())
        return self

    def __exit__(self, *args) -> None:
        run_async_in_thread(self.close())


_session_pool: Dict[str, MmsChatBrowserSession] = {}


def get_or_create_chat_browser_session(row: Dict[str, Any]) -> MmsChatBrowserSession:
    key = f"{row.get('channel_name')}_{row.get('platform_shop_id') or row.get('shop_id')}_{row.get('seller_user_id') or row.get('user_id')}"
    sess = _session_pool.get(key)
    if sess is None:
        sess = MmsChatBrowserSession.from_account_row(row)
        _session_pool[key] = sess
    return sess


def close_chat_browser_session(row: Dict[str, Any]) -> None:
    key = f"{row.get('channel_name')}_{row.get('platform_shop_id') or row.get('shop_id')}_{row.get('seller_user_id') or row.get('user_id')}"
    sess = _session_pool.pop(key, None)
    if sess is not None:
        run_async_in_thread(sess.close())
