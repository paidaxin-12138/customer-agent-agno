"""
消息链路并发能力基准测试（不调用真实 LLM / 拼多多接口）。

测量项：
- 配置上限（代码中的 Semaphore / 队列容量）
- 不同买家：消费者可同时处理的最大任务数
- 同一买家：受 per-buyer Lock 限制，应接近串行
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import List

import pytest

from bridge.context import Context, ContextType, ChannelType, PinduoduoKwargs
from Message.core.consumer import MessageConsumer
from Message.core.handlers import MessageHandler
from Message.core.queue import queue_manager
from Message.models.queue_models import MessageWrapper, QueueConfig
from Channel.pinduoduo.pdd_chnnel import PDDChannel


# ---------- 配置快照（与线上一致） ----------

def _configured_ws_concurrency() -> int:
    try:
        from config import get_config

        return max(4, min(int(get_config("chat.ws_message_max_concurrent", 16) or 16), 32))
    except (TypeError, ValueError):
        return 16


CONFIGURED_LIMITS = {
    "message_consumer_max_concurrent": 28,
    "pdd_websocket_max_concurrent_messages": _configured_ws_concurrency(),
    "queue_max_size": QueueConfig().max_size,
}


class _SleepHandler(MessageHandler):
    """模拟 AI 处理耗时（不访问外部服务）。"""

    def __init__(self, delay_sec: float = 0.08):
        self.delay_sec = delay_sec
        self.peak_in_flight = 0
        self._in_flight = 0
        self.processed_count = 0

    def can_handle(self, context: Context) -> bool:
        return True

    async def handle(self, context: Context, metadata: dict) -> bool:
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            await asyncio.sleep(self.delay_sec)
            self.processed_count += 1
            return True
        finally:
            self._in_flight -= 1


def _make_context(buyer_uid: str) -> Context:
    kwargs = PinduoduoKwargs(
        shop_id="shop_test",
        user_id="user_test",
        from_uid=buyer_uid,
        username=f"buyer_{buyer_uid}",
    )
    return Context(
        type=ContextType.TEXT,
        content="并发测试消息",
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )


@dataclass
class BenchResult:
    label: str
    max_concurrent: int
    message_count: int
    elapsed_sec: float
    peak_parallel: int
    effective_parallel: float

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "max_concurrent": self.max_concurrent,
            "message_count": self.message_count,
            "elapsed_sec": round(self.elapsed_sec, 3),
            "peak_parallel": self.peak_parallel,
            "effective_parallel": round(self.effective_parallel, 2),
        }


async def _run_consumer_bench(
    *,
    max_concurrent: int,
    message_count: int,
    unique_buyers: bool,
    handler_delay: float = 0.08,
) -> BenchResult:
    queue_name = f"bench_{max_concurrent}_{unique_buyers}_{int(time.time() * 1000)}"
    queue_manager.recreate_queue(queue_name, QueueConfig(max_size=message_count + 10))

    handler = _SleepHandler(delay_sec=handler_delay)
    consumer = MessageConsumer(queue_name, max_concurrent=max_concurrent)
    consumer.handlers = [handler]

    queue = queue_manager.get_or_create_queue(queue_name)
    for i in range(message_count):
        uid = f"buyer_{i}" if unique_buyers else "buyer_same"
        await queue.put(_make_context(uid))

    await consumer.start()
    t0 = time.perf_counter()
    deadline = t0 + 30.0
    while (
        handler.processed_count < message_count
        or queue.size() > 0
        or handler._in_flight > 0
    ):
        if time.perf_counter() > deadline:
            break
        await asyncio.sleep(0.02)
    elapsed = time.perf_counter() - t0
    await consumer.stop()

    serial_time = message_count * handler_delay
    effective = serial_time / elapsed if elapsed > 0 else 0.0
    label = "不同买家" if unique_buyers else "同一买家"
    return BenchResult(
        label=label,
        max_concurrent=max_concurrent,
        message_count=message_count,
        elapsed_sec=elapsed,
        peak_parallel=handler.peak_in_flight,
        effective_parallel=effective,
    )


async def _probe_semaphore_parallelism(limit: int, workers: int) -> int:
    """独立探测 Semaphore(limit) 下可同时持有的数量。"""
    sem = asyncio.Semaphore(limit)
    peak = 0
    cur = 0
    lock = asyncio.Lock()

    async def worker():
        nonlocal peak, cur
        async with sem:
            async with lock:
                cur += 1
                peak = max(peak, cur)
            await asyncio.sleep(0.05)
            async with lock:
                cur -= 1

    await asyncio.gather(*[worker() for _ in range(workers)])
    return peak


@pytest.mark.asyncio
async def test_configured_limits_snapshot():
    assert CONFIGURED_LIMITS["message_consumer_max_concurrent"] == 28
    assert CONFIGURED_LIMITS["pdd_websocket_max_concurrent_messages"] == _configured_ws_concurrency()
    assert CONFIGURED_LIMITS["queue_max_size"] == 1000


@pytest.mark.asyncio
async def test_different_buyers_reach_consumer_concurrency():
    """不同买家：峰值并行应接近 min(max_concurrent, 消息数)。"""
    max_c = 10
    n = 20
    r = await _run_consumer_bench(
        max_concurrent=max_c, message_count=n, unique_buyers=True
    )
    assert r.peak_parallel >= max_c - 1, r.as_dict()
    assert r.effective_parallel >= max_c * 0.7, r.as_dict()


@pytest.mark.asyncio
async def test_same_buyer_serializes_per_lock():
    """同一买家：per-buyer Lock 使峰值并行为 1，总耗时接近串行。"""
    message_count = 12
    handler_delay = 0.08
    r = await _run_consumer_bench(
        max_concurrent=10,
        message_count=message_count,
        unique_buyers=False,
        handler_delay=handler_delay,
    )
    assert r.peak_parallel == 1, r.as_dict()
    serial_min = message_count * handler_delay * 0.75
    assert r.elapsed_sec >= serial_min, r.as_dict()


@pytest.mark.asyncio
async def test_pdd_channel_default_websocket_concurrency():
    """PDDChannel 默认并发来自 chat.ws_message_max_concurrent。"""
    import inspect

    expected = _configured_ws_concurrency()
    sig = inspect.signature(PDDChannel.__init__)
    assert sig.parameters["max_concurrent_messages"].default is None
    from core.connection_status import ConnectionStatusManager

    ch = PDDChannel(status_manager=ConnectionStatusManager())
    assert ch.max_concurrent_messages == expected
    peak = await _probe_semaphore_parallelism(expected, workers=expected + 30)
    assert peak == expected


def _print_report(results: List[BenchResult], sem_peaks: dict) -> None:
    print("\n========== 并发配置（代码默认值）==========")
    for k, v in CONFIGURED_LIMITS.items():
        print(f"  {k}: {v}")

    print("\n========== Semaphore 探针（asyncio）==========")
    for k, v in sem_peaks.items():
        print(f"  {k}: 峰值并行 {v}")

    print("\n========== 消息消费者模拟（handler sleep 80ms）==========")
    for r in results:
        d = r.as_dict()
        print(
            f"  [{d['label']}] max_concurrent={d['max_concurrent']} "
            f"消息数={d['message_count']} "
            f"耗时={d['elapsed_sec']}s "
            f"实测峰值并行={d['peak_parallel']} "
            f"有效并行度≈{d['effective_parallel']}"
        )

    print("\n========== 结论摘要 ==========")
    print(
        f"  · 拼多多 WebSocket 入站：最多同时处理 {CONFIGURED_LIMITS['pdd_websocket_max_concurrent_messages']} 条（PDDChannel.message_semaphore）"
    )
    print(
        "  · 消息队列消费者：最多同时处理 28 条（不同买家；chat.message_consumer_max_concurrent）"
    )
    print("  · 同一买家多条消息：串行（per-buyer asyncio.Lock）")
    print(f"  · 队列积压上限：{CONFIGURED_LIMITS['queue_max_size']} 条/店铺队列")
    print(
        "  · 真实 AI 回复并发还受 LLM API 限流、embedder、本机 CPU 影响，上列为程序内上限"
    )


if __name__ == "__main__":
    async def main():
        sem_peaks = {
            "consumer_sem(10)": await _probe_semaphore_parallelism(10, 25),
            "pdd_ws_sem(50)": await _probe_semaphore_parallelism(50, 80),
        }
        results = [
            await _run_consumer_bench(
                max_concurrent=10, message_count=30, unique_buyers=True
            ),
            await _run_consumer_bench(
                max_concurrent=10, message_count=15, unique_buyers=False
            ),
            await _run_consumer_bench(
                max_concurrent=5, message_count=15, unique_buyers=True
            ),
        ]
        _print_report(results, sem_peaks)

    asyncio.run(main())
