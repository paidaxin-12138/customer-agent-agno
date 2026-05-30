#!/usr/bin/env python3
"""拼多多商家后台扫码登录：导出二维码到桌面，扫码成功后写入 Cookie。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Channel.pinduoduo.pdd_login import (
    PDDLogin,
    _cookies_json_embed_ua,
    _mms_backstage_url_not_login,
    _persistent_user_data_dir,
)
from database.db_manager import db_manager
from utils.logger_loguru import get_logger
from utils.path_utils import get_app_dir

logger = get_logger("qrcode_login")


async def _screenshot_qr(page, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    selectors = [
        "canvas",
        "img[src*='qr']",
        "img[src*='QR']",
        ".qr-code",
        "[class*='qrcode']",
        "[class*='QrCode']",
    ]
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if await loc.count() > 0 and await loc.is_visible(timeout=2000):
                await loc.screenshot(path=str(out_path))
                logger.info(f"二维码已保存: {out_path}")
                return
        except Exception:
            continue
    await page.screenshot(path=str(out_path))
    logger.warning(f"已保存登录页截图（未单独定位 QR）: {out_path}")


async def qrcode_login_and_save(username: str, password: str, qr_path: Path) -> bool:
    from playwright.async_api import async_playwright

    app_dir = get_app_dir()
    browsers_path = app_dir / ".browsers"
    if browsers_path.exists():
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers_path)

    pdd = PDDLogin(name=username, password=password, login_type="qrcode")
    user_data_dir = _persistent_user_data_dir(username)

    playwright = await async_playwright().start()
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        args=[
            "--disable-gpu",
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-notifications",
        ],
    )
    page = await context.new_page()
    try:
        await page.goto("https://mms.pinduoduo.com/login", wait_until="domcontentloaded")
        try:
            await page.get_by_text("扫码登录", exact=True).first.click(timeout=5000)
        except Exception:
            pass
        await asyncio.sleep(2.0)
        await _screenshot_qr(page, qr_path)

        print(f"\n{'=' * 56}")
        print(f"  请用【拼多多 App】扫描登录二维码")
        print(f"  图片路径: {qr_path}")
        print(f"  （浏览器窗口也会显示同一二维码，约 2 分钟内有效）")
        print(f"{'=' * 56}\n")

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
            timeout=120000,
        )
        await page.goto("https://mms.pinduoduo.com/home/", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(2.0)
        if not _mms_backstage_url_not_login(page.url):
            logger.error(f"登录未完成，当前 URL: {page.url}")
            return False

        cookies_list = await context.cookies(urls=["https://mms.pinduoduo.com"])
        if not cookies_list:
            cookies_list = await context.cookies()
        cookies_dict = {
            c.get("name", ""): c.get("value", "")
            for c in cookies_list
            if c.get("name")
        }
        if not cookies_dict:
            logger.error("未读取到 Cookie")
            return False
        cookies_json = json.dumps(cookies_dict)
        try:
            user_agent = await page.evaluate("() => navigator.userAgent")
        except Exception:
            user_agent = None
    finally:
        await context.close()
        await playwright.stop()

    cookies_embed = _cookies_json_embed_ua(cookies_json, user_agent)
    user_id, user_name, mall_id = pdd.Set_user_info(cookies_embed, user_agent=user_agent)
    shop_id, shop_name, mall_logo = pdd.Set_shop_info(cookies_embed, user_agent=user_agent)
    if user_id is None or shop_id is None:
        logger.error("Cookie 已获取，但 userinfo/shopinfo 接口失败，请重试")
        return False

    channel = "pinduoduo"
    shop_id_s = str(shop_id)
    user_id_s = str(user_id)
    resolved_username = user_name or username

    if not db_manager.get_shop(channel, shop_id_s):
        db_manager.add_shop(
            channel_name=channel,
            shop_id=shop_id_s,
            shop_name=shop_name or shop_id_s,
            shop_logo=mall_logo,
            description="扫码登录",
        )

    if not db_manager.get_account(channel, shop_id_s, user_id_s):
        db_manager.add_account(
            channel_name=channel,
            shop_id=shop_id_s,
            user_id=user_id_s,
            username=resolved_username,
            password=password,
            cookies=cookies_embed,
        )
    else:
        db_manager.update_account_cookies(channel, shop_id_s, user_id_s, cookies_embed)
        db_manager.update_account_status(channel, shop_id_s, user_id_s, 1)

    print(
        f"\n✅ 登录成功，Cookie 已写入数据库\n"
        f"   店铺: {shop_name} ({shop_id_s})\n"
        f"   客服 user_id: {user_id_s}\n"
        f"   用户名: {resolved_username}\n"
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="pdd57041465173")
    parser.add_argument("--password", default="")
    parser.add_argument("--qr-out", default="~/Desktop/拼多多登录二维码.png")
    args = parser.parse_args()
    qr_path = Path(args.qr_out).expanduser()
    ok = asyncio.run(qrcode_login_and_save(args.username, args.password, qr_path))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
