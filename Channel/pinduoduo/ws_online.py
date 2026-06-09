# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""账号上线状态（MMS set_csstatus）。"""
from __future__ import annotations

import asyncio

from utils.logger_loguru import get_logger

_logger = get_logger("WSOnline")


async def set_account_online(
    channel_name: str,
    shop_id: str,
    user_id: str,
    *,
    logger=None,
) -> bool:
    """WebSocket 连通后调用 MMS set_csstatus，与自动回复「上线」一致。"""
    log = logger or _logger
    from database import db_manager

    account_info = db_manager.get_account(channel_name, str(shop_id), str(user_id))
    if not account_info:
        log.warning("set_account_online: 无账号记录 shop_id={} user_id={}", shop_id, user_id)
        return False
    cookies = account_info.get("cookies")
    if not cookies:
        log.warning("set_account_online: 账号缺少 cookies shop_id={} user_id={}", shop_id, user_id)
        return False

    def _sync_set() -> bool:
        from Channel.pinduoduo.utils.API.Set_up_online import AccountMonitor

        return bool(AccountMonitor(cookies).set_csstatus(1))

    return await asyncio.to_thread(_sync_set)
