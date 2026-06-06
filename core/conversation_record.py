"""入站会话登记门面（Channel 层调用，避免直接依赖 UI 模块路径）。"""
from __future__ import annotations

from bridge.context import Context


def record_inbound_from_context(
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    context: Context,
) -> None:
    from ui.conversation_hub import get_conversation_hub

    get_conversation_hub().record_from_context(
        channel_name, shop_id, user_id, username, context
    )


def record_platform_civility_from_context(
    channel_name: str,
    shop_id: str,
    user_id: str,
    username: str,
    context: Context,
) -> None:
    from ui.conversation_hub import get_conversation_hub

    get_conversation_hub().record_platform_civility_from_context(
        channel_name, shop_id, user_id, username, context
    )
