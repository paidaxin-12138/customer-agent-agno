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
