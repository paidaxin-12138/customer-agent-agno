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
            evicted = False
            for key, existing in list(self._locks.items()):
                if key == user_key:
                    continue
                if existing.locked():
                    continue
                self._locks.pop(key, None)
                evicted = True
                break
            if not evicted:
                break
        return lock

    def prune_idle(self) -> int:
        """淘汰未持有的锁条目，返回移除数量。"""
        removed = 0
        while len(self._locks) > self._max_keys:
            evicted = False
            for key, existing in list(self._locks.items()):
                if existing.locked():
                    continue
                self._locks.pop(key, None)
                removed += 1
                evicted = True
                break
            if not evicted:
                break
        return removed

    def clear(self) -> None:
        """退出时释放全部买家锁引用。"""
        self._locks.clear()
