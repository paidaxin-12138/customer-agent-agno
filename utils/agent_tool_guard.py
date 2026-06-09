# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""Agent 工具调用二次校验（防提示注入误触发敏感操作）。"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from utils.human_transfer_intent import has_explicit_transfer_intent


def buyer_message_from_dependencies(deps: Optional[Dict[str, Any]]) -> str:
    if not deps:
        return ""
    for key in ("buyer_message", "last_buyer_message", "user_message"):
        val = deps.get(key)
        if val is not None and str(val).strip():
            return str(val).strip()
    return ""


def bind_tool_session_params(
    deps: Optional[Dict[str, Any]],
    *,
    shop_id: str,
    user_id: str,
    recipient_uid: str,
) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
    """
    将 LLM 传入的会话参数绑定到 run_context.dependencies，防止跨买家误操作。
    返回 (shop_id, user_id, recipient_uid, error_msg)；error_msg 非空表示拒绝。
    """
    dep = deps or {}
    bound_shop = str(dep.get("shop_id") or "").strip()
    bound_user = str(dep.get("user_id") or "").strip()
    bound_buyer = str(dep.get("from_uid") or "").strip()

    if not bound_shop or not bound_user or not bound_buyer:
        return None, None, None, "缺少会话上下文（shop_id/user_id/from_uid），拒绝执行"

    req_shop = str(shop_id or "").strip()
    req_user = str(user_id or "").strip()
    req_recipient = str(recipient_uid or "").strip()

    if req_shop and req_shop != bound_shop:
        return None, None, None, "shop_id 与会话上下文不一致，拒绝执行"
    if req_user and req_user != bound_user:
        return None, None, None, "user_id 与会话上下文不一致，拒绝执行"
    if req_recipient and req_recipient != bound_buyer:
        return None, None, None, "recipient_uid 与当前买家不一致，拒绝执行"

    return bound_shop, bound_user, bound_buyer, ""


def allow_transfer_tool_call(deps: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """
    仅当买家当前轮消息含明确转人工意图时，允许 transfer_conversation 工具。
    """
    text = buyer_message_from_dependencies(deps)
    if not text:
        return False, "缺少买家消息上下文，拒绝自动转接"
    if not has_explicit_transfer_intent(text):
        return False, "买家未明确要求转人工，拒绝自动转接"
    return True, ""


def validate_shop_goods_id(shop_id: str, user_id: str, goods_id: Any) -> Tuple[bool, str]:
    """确认 goods_id 属于当前店铺且平台可查到详情。"""
    gid = str(goods_id or "").strip()
    if not gid or not str(shop_id or "").strip() or not str(user_id or "").strip():
        return False, "缺少 shop_id / user_id / goods_id"
    try:
        gid_int = int(gid)
        if gid_int <= 0:
            return False, "无效商品 ID"
    except (TypeError, ValueError):
        return False, "无效商品 ID"

    try:
        from Channel.pinduoduo.utils.API.product_manager import ProductManager

        pm = ProductManager(str(shop_id), str(user_id))
        raw = pm.get_product_detail(gid)
    except Exception as e:
        return False, f"商品校验失败: {e}"

    if not isinstance(raw, dict) or not raw.get("success"):
        err = ""
        if isinstance(raw, dict):
            err = str(raw.get("error_msg") or raw.get("message") or "")
        return False, err or "商品不存在或不属于当前店铺"

    info = raw.get("product_info")
    if not isinstance(info, dict) or not info:
        return False, "无法获取商品详情"
    return True, ""
