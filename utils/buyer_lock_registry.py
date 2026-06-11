# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""有界买家串行锁注册表，避免 MessageConsumer 中 Lock 字典无限增长。"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import AsyncIterator, Dict


class BuyerLockRegistry:
    def __init__(self, max_keys: int = 5000) -> None:
        self._max_keys = max(100, max_keys)
        self._locks: OrderedDict[str, asyncio.Lock] = OrderedDict()

    def _get_or_create_lock(self, user_key: str) -> asyncio.Lock:
        if user_key in self._locks:
            self._locks.move_to_end(user_key)
            return self._locks[user_key]
        lock = asyncio.Lock()
        self._locks[user_key] = lock
        return lock

    def _evict_idle_unlocked(self) -> None:
        """仅在锁已释放后淘汰空闲条目，避免 lock_for 与 acquire 之间被 prune 导致双锁。"""
        while len(self._locks) > self._max_keys:
            evicted = False
            for key, existing in list(self._locks.items()):
                if existing.locked():
                    continue
                self._locks.pop(key, None)
                evicted = True
                break
            if not evicted:
                break

    @asynccontextmanager
    async def hold(self, user_key: str) -> AsyncIterator[None]:
        """获取买家锁并在释放后尝试 LRU 淘汰（推荐 Consumer 使用）。"""
        lock = self._get_or_create_lock(user_key)
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
            self._evict_idle_unlocked()

    def lock_for(self, user_key: str) -> asyncio.Lock:
        """返回买家锁（兼容旧调用；勿在 acquire 前调用 prune_idle）。"""
        lock = self._get_or_create_lock(user_key)
        self._evict_idle_unlocked()
        return lock

    def prune_idle(self) -> int:
        """淘汰未持有的锁条目，返回移除数量。"""
        before = len(self._locks)
        self._evict_idle_unlocked()
        return before - len(self._locks)

    def clear(self) -> None:
        """退出时释放全部买家锁引用。"""
        self._locks.clear()
