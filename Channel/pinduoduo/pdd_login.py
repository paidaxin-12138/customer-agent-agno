"""
拼多多账号异步登录认证
"""
import os
# 必须在导入 playwright 之前设置浏览器路径
from pathlib import Path
from utils.path_utils import get_app_dir
from utils.logger_loguru import get_logger

# 设置 Playwright 浏览器路径
app_dir = get_app_dir()
browsers_path = app_dir / ".browsers"
if browsers_path.exists():
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)
    logger_temp = get_logger("Pdd_login_init")
    logger_temp.info(f"设置 Playwright 浏览器路径: {browsers_path}")
else:
    # 回退到用户目录
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(os.getenv("LOCALAPPDATA", ""), "ms-playwright")

from http import cookies
import asyncio
import requests
import json
from typing import Optional, Dict, Any, Tuple
import sys
from urllib.parse import urlparse

from database import db_manager
from playwright.async_api import async_playwright
from Channel.pinduoduo.utils.API.get_shop_info import GetShopInfo
from Channel.pinduoduo.utils.API.get_user_info import GetUserInfo
from Channel.pinduoduo.utils.base_request import CLIENT_UA_EMBED_KEY


def _cookies_json_embed_ua(cookies_json: str, user_agent: Optional[str]) -> str:
    """把登录浏览器的 UA 写入 Cookie JSON，供 BaseRequest 持久化并与后续 HTTP 一致。"""
    if not user_agent or not str(user_agent).strip():
        return cookies_json
    try:
        d = json.loads(cookies_json)
        if not isinstance(d, dict):
            return cookies_json
        merged = dict(d)
        merged[CLIENT_UA_EMBED_KEY] = str(user_agent).strip()
        return json.dumps(merged)
    except (json.JSONDecodeError, TypeError):
        return cookies_json


def _persistent_user_data_dir(account_key: str) -> str:
    """与 login() 使用同一规则，禁止用内置 hash()（进程间不稳定）。"""
    return str(app_dir / "user_data" / account_key)


def _mms_backstage_url_not_login(url: str) -> bool:
    """
    是否已进入商家后台（非登录/扫码页）。

    旧逻辑用「标题含商家后台」或「mms 域名且 URL 不含子串 '/login'」，
    会把根路径 / 或部分扫码页误判为已登录，从而在用户未扫码时就关浏览器。
    """
    try:
        p = urlparse(url)
    except Exception:
        return False
    host = (p.netloc or "").lower()
    if "mms.pinduoduo.com" not in host:
        return False
    path = (p.path or "").lower()
    if path.startswith("/login") or path.startswith("/sign"):
        return False
    # 根路径多为登录 SPA，不算已进入后台
    if path in ("/", ""):
        # 部分 SPA 用 hash 路由，例如 /#/home
        frag = (p.fragment or "").lower()
        if frag.startswith("home") or "/home" in frag:
            return True
        if "goods" in frag or "order" in frag:
            return True
        return False
    prefixes = (
        "/home",
        "/goods",
        "/orders",
        "/order",
        "/comment",
        "/setting",
        "/finance",
        "/tool",
        "/marketing",
        "/activity",
        "/index",
        "/gates",
        "/mall",
        "/message",
        "/chart",
    )
    return any(
        path == pref or path.startswith(pref + "/") or path.startswith(pref + "?")
        for pref in prefixes
    )


class PDDLogin():
    def __init__(self, name, password, login_type: str = "password"):
        self.logger = get_logger("Pdd_login")
        self.channel_name = "pinduoduo"  # 渠道名称固定为"pinduoduo"
        self.base_url = "https://mms.pinduoduo.com/login"
        self.name = name
        self.password = password
        self.login_type = login_type
    async def login(self):
        """使用账号密码登录
        
        Args:
            name: 账号名称
            password: 账号密码

        """
        try:
            # 启动Playwright
            playwright = await async_playwright().start()
            
            user_data_dir = _persistent_user_data_dir(self.name)
            self.logger.debug(f"使用用户数据目录: {user_data_dir}")
            
            # 使用持久化上下文，自动处理用户数据目录
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=False,
                args=[
                    '--disable-gpu',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-notifications',  # 禁用通知
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            )
            
            page = await context.new_page()
            
            # 访问登录页面
            await page.goto(self.base_url)
            
            if self.login_type == "qrcode":
                try:
                    await page.click("text=扫码登录", timeout=3000)
                except Exception:
                    # 页面默认可能已是扫码页，忽略切换失败
                    pass
                self.logger.info("请在弹出的浏览器中使用拼多多扫码登录...")
            else:
                # 账号登录入口（避免依赖会变更的 CSS Modules 类名）
                try:
                    await page.get_by_text("账号登录", exact=True).first.click(timeout=8000)
                except Exception:
                    await page.locator("text=账号登录").first.click(timeout=8000)
                
                # 等待页面加载
                await page.wait_for_selector("input[type='text']")
                
                # 输入店铺名
                await page.fill("input[type='text']", self.name)
                
                # 输入密码
                await page.fill("input[type='password']", self.password)
                
                # 点击登录按钮
                await page.click("button:has-text('登录')")
            
            timeout_ms = 120000 if self.login_type == "qrcode" else 60000
            # 仅用「已进入后台路径」判断成功，避免扫码页/根路径/标题「首页」误判
            await page.wait_for_function(
                """() => {
                    try {
                        const u = new URL(location.href);
                        if (u.hostname !== 'mms.pinduoduo.com') return false;
                        const path = (u.pathname || '').toLowerCase();
                        if (path.startsWith('/login') || path.startsWith('/sign')) return false;
                        const hash = (u.hash || '').toLowerCase();
                        if (path === '/' || path === '') {
                            if (hash.startsWith('#/home') || hash.includes('/home')) return true;
                            if (hash.includes('goods') || hash.includes('order')) return true;
                            return false;
                        }
                        const ok = ['/home','/goods','/orders','/order','/comment','/setting',
                          '/finance','/tool','/marketing','/activity','/index','/gates',
                          '/mall','/message','/chart'];
                        return ok.some(p => path === p || path.startsWith(p + '/') || path.startsWith(p + '?'));
                    } catch (e) { return false; }
                }""",
                timeout=timeout_ms,
            )

            await page.wait_for_load_state("domcontentloaded")
            if not _mms_backstage_url_not_login(page.url):
                self.logger.error(
                    "登录等待结束，但当前 URL 仍不像已进入后台（可能未完成扫码/密码登录），"
                    f"url={page.url!r}"
                )
                await context.close()
                await playwright.stop()
                return False

            # 进入后台首页，确保 Janus / Earth 接口所需 Cookie 已落盘
            try:
                await page.goto(
                    "https://mms.pinduoduo.com/home/",
                    wait_until="domcontentloaded",
                    timeout=30000,
                )
                await asyncio.sleep(2.0)
            except Exception as nav_err:
                self.logger.warning(f"登录后跳转首页等待会话: {nav_err}")

            if not _mms_backstage_url_not_login(page.url):
                self.logger.error(
                    "跳转首页后仍不在商家后台（可能未完成扫码或会话无效），"
                    f"url={page.url!r}"
                )
                await context.close()
                await playwright.stop()
                return False

            # 获取cookies并转换为字典格式（含 mms 域）
            cookies_list = await context.cookies(urls=["https://mms.pinduoduo.com"])
            if not cookies_list:
                cookies_list = await context.cookies()
            # 将playwright格式的cookies列表转换为字典格式，使用安全的get方法
            cookies_dict = {cookie.get('name', ''): cookie.get('value', '') for cookie in cookies_list if cookie.get('name')}
            if not cookies_dict:
                self.logger.error("登录流程结束但未读到任何 Cookie，请确认已进入商家后台（非登录页）")
                await context.close()
                await playwright.stop()
                return False
            cookies_json = json.dumps(cookies_dict)
            try:
                user_agent = await page.evaluate("() => navigator.userAgent")
            except Exception as e:
                self.logger.debug(f"读取 navigator.userAgent 失败: {e}")
                user_agent = None
            # 关闭浏览器上下文
            await context.close()
            await playwright.stop()

            return {"cookies": cookies_json, "user_agent": user_agent}

        except Exception as e:
            self.logger.error(f"登录失败: {str(e)}")
            return False
        
    async def refresh_cookies(self):
        """重新获取cookies，使用已保存的用户数据，无需再次登录

        Returns:
            dict: ``{"cookies": str, "user_agent": str|None}``，失败时 ``False``
        """
        playwright = None
        try:
            # 启动Playwright
            playwright = await async_playwright().start()
            
            user_data_dir = _persistent_user_data_dir(self.name)
            self.logger.debug(f"使用用户数据目录刷新cookies: {user_data_dir}")
            
            # 检查用户数据目录是否存在
            if not os.path.exists(user_data_dir):
                self.logger.error(f"用户数据目录不存在: {user_data_dir}，请先登录")
                await playwright.stop()
                return False
            
            # 使用持久化上下文，自动加载用户数据
            context = await playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=True,  # 刷新cookies时可以使用无头模式
                args=[
                    '--disable-gpu',
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-notifications',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            )
            
            page = await context.new_page()
            
            # 访问拼多多商家后台首页，验证登录状态
            await page.goto("https://mms.pinduoduo.com/home/")
            
            # 等待页面加载，检查是否需要重新登录
            try:
                # 如果页面跳转到登录页面，说明登录状态已失效
                await page.wait_for_url("**/login**", timeout=5000)
                self.logger.warning("登录状态已失效，需要重新登录")
                await context.close()
                await playwright.stop()
                return False
            except Exception as e:
                # 超时未进入登录 URL → 视为仍在已登录态
                self.logger.debug(f"未在超时内匹配登录页（视为 Cookie 仍有效）: {e}")

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception as e:
                self.logger.debug(f"等待 domcontentloaded: {e}")
            await asyncio.sleep(1.5)

            cookies_list = await context.cookies(urls=["https://mms.pinduoduo.com"])
            if not cookies_list:
                cookies_list = await context.cookies()
            cookies_dict = {cookie.get('name', ''): cookie.get('value', '') for cookie in cookies_list if cookie.get('name')}
            cookies_json = json.dumps(cookies_dict)
            try:
                user_agent = await page.evaluate("() => navigator.userAgent")
            except Exception as e:
                self.logger.debug(f"读取 navigator.userAgent 失败: {e}")
                user_agent = None

            # 关闭浏览器上下文
            await context.close()
            await playwright.stop()

            self.logger.info(f"成功刷新账号 '{self.name}' 的cookies")
            return {"cookies": cookies_json, "user_agent": user_agent}

        except Exception as e:
            self.logger.error(f"刷新cookies失败: {str(e)}")
            if playwright:
                try:
                    await playwright.stop()
                except Exception as e:
                    self.logger.debug(f"playwright.stop 清理: {e}")
            return False

    def Set_user_info(self, cookies_json, user_agent: Optional[str] = None):
        user_info = GetUserInfo(cookies_json, user_agent=user_agent)
        result = user_info.get_user_info()
        if result is False:
            self.logger.error("获取用户信息失败")
            return None, None, None
        user_id, user_name, mall_id = result
        return user_id, user_name, mall_id

    def Set_shop_info(self, cookies_json, user_agent: Optional[str] = None):
        shop_info = GetShopInfo(cookies_json, user_agent=user_agent)
        result = shop_info.get_shop_info()
        if result is False:
            self.logger.error("获取店铺信息失败")
            return None, None, None
        shop_id, shop_name, mallLogo = result
        return shop_id, shop_name, mallLogo
    
async def login_pdd(name, password, login_type: str = "password"):
    """
    使用账号密码登录并返回账号、店铺信息，不直接操作数据库。
    如果登录成功，返回包含详细信息的字典。
    如果登录失败，返回 False。

    :param name: 用户名
    :param password: 密码
    :return: dict or bool
    """
    pdd_login = PDDLogin(name=name, password=password, login_type=login_type)
    login_payload = await pdd_login.login()
    if not login_payload or not isinstance(login_payload, dict):
        pdd_login.logger.error(f"账号 '{name}' 登录失败，未能获取cookies")
        return False

    cookies_json = login_payload.get("cookies")
    user_agent = login_payload.get("user_agent")
    if not cookies_json:
        pdd_login.logger.error(f"账号 '{name}' 登录失败，返回数据缺少 cookies")
        return False

    try:
        # 获取用户信息和店铺信息（须与 Playwright 使用同一 UA，否则易被判定会话无效）
        user_id, user_name, mall_id = pdd_login.Set_user_info(cookies_json, user_agent=user_agent)
        shop_id, shop_name, mallLogo = pdd_login.Set_shop_info(cookies_json, user_agent=user_agent)
        
        # 检查是否成功获取到必要信息
        if user_id is None or shop_id is None:
            pdd_login.logger.error(
                f"账号 '{name}' 已进入后台并拿到 Cookie，但用户信息/店铺信息接口失败（会话过期或风控），"
                "请重试登录或更换网络"
            )
            return False

        pdd_login.logger.info(f"账号 '{name}' 登录成功，获取到店铺: {shop_name}({shop_id})")

        # 登录成功，返回包含所有信息的字典
        resolved_username = user_name or name or f"pdd_user_{user_id}"
        return {
            "channel_name": pdd_login.channel_name,
            "shop_id": shop_id,
            "shop_name": shop_name,
            "shop_logo": mallLogo,
            "user_id": user_id,
            "username": resolved_username,
            "password": password, # 使用传入的密码
            "cookies": _cookies_json_embed_ua(cookies_json, user_agent),
        }
    except Exception as e:
        pdd_login.logger.error(f"账号 '{name}' 拿到 Cookie 后处理用户信息时出错: {e}")
        return False

async def refresh_pdd_cookies(name, password=None):
    """
    刷新拼多多账号的cookies，使用已保存的用户数据，无需再次输入账号密码。
    如果刷新成功，返回包含最新cookies的字典。
    如果刷新失败（如登录状态已失效），返回 False。

    :param name: 用户名
    :param password: 密码（可选，仅用于创建PDDLogin实例）
    :return: dict or bool
    """
    pdd_login = PDDLogin(name=name, password=password or "")
    refresh_payload = await pdd_login.refresh_cookies()

    if not refresh_payload or not isinstance(refresh_payload, dict):
        pdd_login.logger.error(f"账号 '{name}' cookies刷新失败")
        return False

    cookies_json = refresh_payload.get("cookies")
    user_agent = refresh_payload.get("user_agent")
    if not cookies_json:
        pdd_login.logger.error(f"账号 '{name}' cookies刷新失败，返回数据缺少 cookies")
        return False

    try:
        # 获取用户信息和店铺信息
        user_id, user_name, mall_id = pdd_login.Set_user_info(cookies_json, user_agent=user_agent)
        shop_id, shop_name, mallLogo = pdd_login.Set_shop_info(cookies_json, user_agent=user_agent)
        
        # 检查是否成功获取到必要信息
        if user_id is None or shop_id is None:
            pdd_login.logger.error(f"账号 '{name}' cookies刷新成功，但获取用户信息或店铺信息失败")
            return False

        pdd_login.logger.info(f"账号 '{name}' cookies刷新成功，店铺: {shop_name}({shop_id})")

        # 刷新成功，返回包含最新信息的字典
        return {
            "channel_name": pdd_login.channel_name,
            "shop_id": shop_id,
            "shop_name": shop_name,
            "shop_logo": mallLogo,
            "user_id": user_id,
            "username": name,
            "password": password or "",
            "cookies": _cookies_json_embed_ua(cookies_json, user_agent),
        }
    except Exception as e:
        pdd_login.logger.error(f"账号 '{name}' cookies刷新成功，但在处理后续信息时出错: {e}")
        return False

