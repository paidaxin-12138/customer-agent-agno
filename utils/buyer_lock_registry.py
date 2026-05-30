"""有界买家串行锁注册表，避免 MessageConsumer 中 Lock 字典无限增长。"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from typing import Dict


class BuyerLockRegistry:
    def __init__(self, max_keys: int = 5000) -> None:
        self._max_keys = max(100, max_keys)
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

    def lock_for(self, user_key: str) -> asyncio.Lock:
        if user_key in self._locks:
            self._locks.move_to_end(user_key)
            return self._locks[user_key]
        lock = asyncio.Lock()
        self._locks[user_key] = lock
        while len(self._locks) > self._max_keys:
            self._locks.popitem(last=False)
        return lock
