# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""入站会话登记门面（Channel 层调用，避免直接依赖 UI 模块路径）。"""
from __future__ import annotations

from bridge.context import Context
from utils.best_effort import run_best_effort
from utils.logger_loguru import get_logger

_log = get_logger("ConversationRecord")


def record_inbound_from_context(
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    context: Context,
) -> None:
    def _do() -> None:
        from ui.conversation_hub import get_conversation_hub

        get_conversation_hub().record_from_context(
            channel_name, shop_id, user_id, username, context
        )

    run_best_effort(
        f"Hub.record_inbound shop={shop_id} user={user_id}",
        _do,
        logger=_log,
    )


def record_platform_civility_from_context(
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    context: Context,
) -> None:
    def _do() -> None:
        from ui.conversation_hub import get_conversation_hub

        get_conversation_hub().record_platform_civility_from_context(
            channel_name, shop_id, user_id, username, context
        )

    run_best_effort(
        f"Hub.record_civility shop={shop_id} user={user_id}",
        _do,
        logger=_log,
    )
