"""
会话内最近订单号缓存（买家发订单卡或文本带单号时写入）。
"""

from __future__ import annotations

import time
from typing import Dict, Optional, Tuple

_CACHE: Dict[str, Tuple[str, float]] = {}
_DEFAULT_TTL_SEC = 3600


def _key(shop_id: str, buyer_uid: str) -> str:
    return f"{shop_id}:{buyer_uid}"


def remember_order(shop_id: str, buyer_uid: str, order_sn: str, ttl_sec: int = _DEFAULT_TTL_SEC) -> None:
    if not shop_id or not buyer_uid or not order_sn:
        return
    _CACHE[_key(str(shop_id), str(buyer_uid))] = (str(order_sn).strip(), time.time() + max(60, int(ttl_sec)))


def get_recent_order(shop_id: str, buyer_uid: str) -> Optional[str]:
    entry = _CACHE.get(_key(str(shop_id), str(buyer_uid)))
    if not entry:
        return None
    order_sn, expires = entry
    if time.time() > expires:
        _CACHE.pop(_key(str(shop_id), str(buyer_uid)), None)
        return None
    return order_sn


_REFUND_CARD_BLOCKED: Dict[str, float] = {}


def _refund_block_key(shop_id: str, buyer_uid: str, order_sn: str) -> str:
    return f"{shop_id}:{buyer_uid}:{order_sn}"


def mark_refund_card_unusable(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
    *,
    ttl_sec: int = 86400,
) -> None:
    """平台通知快捷退款卡已过期/不可用时，避免重复发卡。"""
    if not all([shop_id, buyer_uid, order_sn]):
        return
    key = _refund_block_key(str(shop_id), str(buyer_uid), str(order_sn).strip())
    _REFUND_CARD_BLOCKED[key] = time.time() + max(300, int(ttl_sec))


def is_refund_card_unusable(shop_id: str, buyer_uid: str, order_sn: str) -> bool:
    key = _refund_block_key(str(shop_id), str(buyer_uid), str(order_sn).strip())
    until = _REFUND_CARD_BLOCKED.get(key)
    if until is None:
        return False
    if time.time() > until:
        _REFUND_CARD_BLOCKED.pop(key, None)
        return False
    return True


_REFUND_CARD_SENT: Dict[str, float] = {}


def mark_refund_card_sent(
    shop_id: str,
    buyer_uid: str,
    order_sn: str,
    *,
    ttl_sec: int = 86400,
) -> None:
    """该订单已成功调用过 ask_refund_apply/send（平台对同单代申请次数/时效有限）。"""
    if not all([shop_id, buyer_uid, order_sn]):
        return
    key = _refund_block_key(str(shop_id), str(buyer_uid), str(order_sn).strip())
    _REFUND_CARD_SENT[key] = time.time() + max(300, int(ttl_sec))


def has_sent_refund_card(shop_id: str, buyer_uid: str, order_sn: str) -> bool:
    key = _refund_block_key(str(shop_id), str(buyer_uid), str(order_sn).strip())
    until = _REFUND_CARD_SENT.get(key)
    if until is None:
        return False
    if time.time() > until:
        _REFUND_CARD_SENT.pop(key, None)
        return False
    return True
