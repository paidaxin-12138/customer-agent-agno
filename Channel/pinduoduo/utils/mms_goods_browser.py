"""
通过 Playwright 在商家后台页面上下文中拉取商品列表/详情。

拼多多 goodsList 需带页面 JS 生成的 anti-content；裸 requests 常返回 54001。
本模块用数据库 Cookie 注入浏览器，拦截或复用页面发起的 goodsList 请求。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from config import get_config
from utils.async_helper import run_async_in_thread
from utils.logger_loguru import get_logger

logger = get_logger("MmsGoodsBrowser")

GOODS_LIST_PATH = "/vodka/v2/mms/query/display/mall/goodsList"
DETAIL_PATH = "/glide/v2/mms/query/commit/on_shop/detail"
GOODS_LIST_PAGE_URL = "https://mms.pinduoduo.com/goods/goods_list"
RISK_ERROR_CODE = 54001

DEFAULT_GOODS_LIST_BODY: Dict[str, Any] = {
    "page": 1,
    "page_size": 50,
    "pre_sale_type": 0,
    "out_goods_sn_gray_flag": True,
    "shipment_time_type": 3,
    "is_onsale": 1,
    "sold_out": 0,
    "order_by": "created_at:desc,id:desc",
}


def is_risk_blocked_response(data: Optional[dict]) -> bool:
    if not isinstance(data, dict):
        return False
    if data.get("error_code") == RISK_ERROR_CODE:
        return True
    msg = str(data.get("error_msg") or data.get("errorMsg") or "")
    return "verifyAuthToken" in str(data.get("result") or "") or (
        "频繁" in msg and data.get("success") is not True
    )


def normalize_risk_error_message(data: Optional[dict]) -> str:
    if not isinstance(data, dict):
        return "商品列表接口无响应"
    msg = str(data.get("error_msg") or data.get("errorMsg") or "商品列表接口失败")
    if data.get("error_code") == RISK_ERROR_CODE or "verifyAuthToken" in str(
        data.get("result") or ""
    ):
        return (
            "拼多多商品列表接口触发风控校验（非点击次数过多）。"
            "请在「用户管理」重新验证登录后重试；若仍失败，用浏览器打开商家后台「商品管理」完成一次人机验证。"
        )
    return msg


class MmsGoodsBrowserSession:
    """单次同步复用的浏览器会话（Cookie 来自数据库）。"""

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
            bool(get_config("knowledge_base.goods_sync_browser_headless", True))
            if headless is None
            else headless
        )
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._opened = False
        self._first_page_loaded = False

    @classmethod
    def from_product_manager(cls, pm: Any) -> "MmsGoodsBrowserSession":
        return cls(
            shop_id=pm.shop_id,
            user_id=pm.user_id,
            account_name=getattr(pm, "account_name", ""),
            cookies=getattr(pm, "cookies", {}) or {},
            user_agent=(pm.default_headers or {}).get("User-Agent"),
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
        logger.info(
            "商品浏览器会话已启动: {} (shop={} headless={})",
            self.account_name,
            self.shop_id,
            self.headless,
        )

    async def soft_recycle(self) -> None:
        """不重启 Chromium，仅重置商品列表页上下文以降低内存占用。"""
        if not self._page:
            return
        logger.info("商品浏览器：轻量重置页面（不重启 Chromium）")
        try:
            await self._page.goto("about:blank", wait_until="commit", timeout=15_000)
        except Exception as e:
            logger.warning("轻量重置 about:blank 失败: {}", e)
        self._first_page_loaded = False
        await asyncio.sleep(0.3)
        await self.fetch_goods_list_raw(1, 1)

    async def close(self) -> None:
        try:
            if self._context:
                await self._context.close()
        except Exception as e:
            logger.debug("关闭 browser context: {}", e)
        try:
            if self._browser:
                await self._browser.close()
        except Exception as e:
            logger.debug("关闭 browser: {}", e)
        try:
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.debug("停止 playwright: {}", e)
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._opened = False
        self._first_page_loaded = False

    async def _dismiss_modals(self) -> None:
        if not self._page:
            return
        for sel in (
            ".MDL_closeIcon",
            '[data-testid="beast-core-icon-close"]',
            'button:has-text("知道了")',
            'button:has-text("关闭")',
            'button:has-text("暂不")',
        ):
            try:
                loc = self._page.locator(sel).first
                if await loc.count() and await loc.is_visible():
                    await loc.click(timeout=1500)
                    await asyncio.sleep(0.3)
            except Exception:
                pass

    async def _route_goods_list_page(self, page_num: int, page_size: int) -> None:
        assert self._page is not None

        async def handler(route) -> None:
            req = route.request
            if GOODS_LIST_PATH in req.url and req.method == "POST":
                body = req.post_data_json
                if not isinstance(body, dict):
                    body = dict(DEFAULT_GOODS_LIST_BODY)
                body["page"] = int(page_num)
                body["page_size"] = int(page_size)
                await route.continue_(post_data=json.dumps(body, ensure_ascii=False))
            else:
                await route.continue_()

        await self._page.unroute_all(behavior="ignoreErrors")
        await self._page.route(f"**{GOODS_LIST_PATH}**", handler)

    async def _ensure_goods_list_page(self) -> None:
        """打开商品管理页，让页面注入 anti-content 等请求头。"""
        assert self._page is not None
        if self._first_page_loaded:
            return
        await self._page.goto(
            GOODS_LIST_PAGE_URL,
            wait_until="domcontentloaded",
            timeout=60_000,
        )
        self._first_page_loaded = True
        await self._dismiss_modals()
        await asyncio.sleep(0.8)

    async def _post_goods_list_in_page(self, page_num: int, page_size: int) -> dict:
        """在页面上下文中 POST goodsList（自动带 anti-content）。"""
        assert self._page is not None
        body = dict(DEFAULT_GOODS_LIST_BODY)
        body["page"] = int(page_num)
        body["page_size"] = int(page_size)
        data = await self._page.evaluate(
            """async (payload) => {
                const resp = await fetch(
                    'https://mms.pinduoduo.com/vodka/v2/mms/query/display/mall/goodsList',
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
            body,
        )
        if not isinstance(data, dict):
            raise RuntimeError("商品列表接口返回非 JSON 对象")
        return data

    def _validate_goods_list_data(self, data: dict) -> dict:
        if is_risk_blocked_response(data):
            raise RuntimeError(normalize_risk_error_message(data))
        if data.get("success") is not True:
            err = str(data.get("error_msg") or data.get("errorMsg") or "商品列表加载失败")
            if "会话已过期" in err or data.get("error_code") == 43001:
                raise RuntimeError(
                    "拼多多商家后台登录已过期，请在「用户管理」重新登录后再同步商品。"
                )
            raise RuntimeError(err)
        return data

    async def fetch_goods_list_raw(self, page_num: int = 1, page_size: int = 50) -> dict:
        """返回 goodsList 原始 JSON（与 MMS 接口一致）。"""
        await self.open()
        assert self._page is not None
        page_num = max(1, int(page_num))
        page_size = max(1, min(int(page_size), 100))
        await self._route_goods_list_page(page_num, page_size)

        async with self._page.expect_response(
            lambda r: GOODS_LIST_PATH in r.url and r.request.method == "POST",
            timeout=45_000,
        ) as resp_info:
            if not self._first_page_loaded:
                await self._page.goto(
                    GOODS_LIST_PAGE_URL,
                    wait_until="domcontentloaded",
                    timeout=60_000,
                )
                self._first_page_loaded = True
                await self._dismiss_modals()
            else:
                await self._page.reload(wait_until="domcontentloaded")

        response = await resp_info.value
        data = await response.json()
        try:
            return self._validate_goods_list_data(data)
        except RuntimeError as first_err:
            logger.warning("拦截 goodsList 失败: {}，尝试页面内 fetch", first_err)
            if not self._first_page_loaded:
                await self._ensure_goods_list_page()
            try:
                data2 = await self._post_goods_list_in_page(page_num, page_size)
                return self._validate_goods_list_data(data2)
            except RuntimeError:
                raise first_err from None

    async def fetch_product_detail_raw(self, goods_id: Any) -> dict:
        await self.open()
        if not self._first_page_loaded:
            await self.fetch_goods_list_raw(1, 1)
        assert self._page is not None
        gid = goods_id
        try:
            gid = int(goods_id)
        except (TypeError, ValueError):
            pass
        body = {"goods_id": gid}
        async with self._page.expect_response(
            lambda r: DETAIL_PATH in r.url and r.request.method == "POST",
            timeout=30_000,
        ) as resp_info:
            await self._page.evaluate(
                """async (payload) => {
                    await fetch('https://mms.pinduoduo.com/glide/v2/mms/query/commit/on_shop/detail', {
                        method: 'POST',
                        credentials: 'include',
                        headers: {
                            'accept': 'application/json, text/plain, */*',
                            'content-type': 'application/json;charset=UTF-8',
                        },
                        body: JSON.stringify(payload),
                    });
                }""",
                body,
            )
        response = await resp_info.value
        data = await response.json()
        if is_risk_blocked_response(data):
            raise RuntimeError(normalize_risk_error_message(data))
        return data

    def fetch_goods_list_raw_sync(self, page_num: int = 1, page_size: int = 50) -> dict:
        return run_async_in_thread(self.fetch_goods_list_raw(page_num, page_size))

    def fetch_product_detail_raw_sync(self, goods_id: Any) -> dict:
        return run_async_in_thread(self.fetch_product_detail_raw(goods_id))

    async def __aenter__(self) -> "MmsGoodsBrowserSession":
        await self.open()
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    def __enter__(self) -> "MmsGoodsBrowserSession":
        run_async_in_thread(self.open())
        return self

    def __exit__(self, *args) -> None:
        run_async_in_thread(self.close())


def fetch_mall_goods_list_via_browser(
    pm: Any,
    page_num: int = 1,
    page_size: int = 50,
) -> Optional[dict]:
    """一次性浏览器拉取（无会话复用时）。"""
    try:
        with MmsGoodsBrowserSession.from_product_manager(pm) as session:
            return session.fetch_goods_list_raw_sync(page_num, page_size)
    except Exception as e:
        logger.error("浏览器拉取商品列表失败: {}", e)
        return {
            "success": False,
            "error_msg": str(e),
            "error_code": RISK_ERROR_CODE if "风控" in str(e) else None,
        }
