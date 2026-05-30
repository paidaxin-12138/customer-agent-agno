"""BuyerLockRegistry LRU 与并发行为测试。"""
import asyncio

import pytest

from utils.buyer_lock_registry import BuyerLockRegistry


def test_lru_evicts_oldest_when_over_capacity():
    # 实现中 max_keys 下限为 100
    reg = BuyerLockRegistry(max_keys=100)
    for i in range(100):
        reg.lock_for(f"k{i}")
    assert len(reg._locks) == 100

    reg.lock_for("k_new")
    assert len(reg._locks) == 100
    assert "k0" not in reg._locks
    assert "k_new" in reg._locks


def test_touch_moves_key_to_end_and_prevents_eviction():
    reg = BuyerLockRegistry(max_keys=100)
    for i in range(100):
        reg.lock_for(f"k{i}")
    la = reg.lock_for("k0")
    reg.lock_for("k_new")
    assert "k0" in reg._locks
    assert "k1" not in reg._locks
    assert la is reg.lock_for("k0")


@pytest.mark.asyncio
async def test_concurrent_locks_serialize_same_buyer():
    reg = BuyerLockRegistry(max_keys=100)
    lock = reg.lock_for("buyer_x")
    order: list[str] = []

    async def worker(tag: str):
        async with lock:
            order.append(f"{tag}_start")
            await asyncio.sleep(0.02)
            order.append(f"{tag}_end")

    await asyncio.gather(worker("w1"), worker("w2"))
    assert order.index("w1_start") < order.index("w1_end")
    assert order.index("w2_start") < order.index("w2_end")
    for i in range(0, len(order), 2):
        assert order[i].endswith("_start")
        assert order[i + 1].endswith("_end")
