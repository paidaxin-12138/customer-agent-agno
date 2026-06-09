# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
消息链路并发能力基准测试（不调用真实 LLM / 拼多多接口）。

测量项：
- 配置上限（代码中的 Semaphore / 队列容量）
- 不同买家：消费者可同时处理的最大任务数
- 同一买家：受 per-buyer Lock 限制，应接近串行
- ``test_perf_consumer_latency_p95``：输出 P95 处理延迟（仅报告，不作为门禁）
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass
from typing import List
from unittest.mock import AsyncMock, patch

import pytest

from bridge.context import Context, ContextType, ChannelType, PinduoduoKwargs
from Message.core.consumer import MessageConsumer
from Message.core.handlers import MessageHandler
from Message.core.queue import queue_manager
from Message.models.queue_models import MessageWrapper, QueueConfig
from Channel.pinduoduo.pdd_channel import PDDChannel
from Channel.pinduoduo.ws_config import queue_name_for_account


# ---------- 配置快照（与线上一致） ----------

def _configured_ws_concurrency() -> int:
    try:
        from config import get_config

        return max(4, min(int(get_config("chat.ws_message_max_concurrent", 16) or 16), 32))
    except (TypeError, ValueError):
        return 16


CONFIGURED_LIMITS = {
    "message_consumer_max_concurrent": 16,
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


def _make_context(
    buyer_uid: str,
    *,
    shop_id: str = "shop_test",
    user_id: str = "user_test",
) -> Context:
    kwargs = PinduoduoKwargs(
        shop_id=shop_id,
        user_id=user_id,
        from_uid=buyer_uid,
        username=f"buyer_{buyer_uid}",
    )
    return Context(
        type=ContextType.TEXT,
        content="并发测试消息",
        channel_type=ChannelType.PINDUODUO,
        kwargs=kwargs,
    )


class _AccountTagHandler(MessageHandler):
    """记录处理到的 seller user_id，用于多账号队列隔离验证。"""

    def __init__(self, expected_user_id: str, delay_sec: float = 0.05):
        self.expected_user_id = str(expected_user_id)
        self.delay_sec = delay_sec
        self.processed_user_ids: List[str] = []
        self.peak_in_flight = 0
        self._in_flight = 0

    def can_handle(self, context: Context) -> bool:
        return True

    async def handle(self, context: Context, metadata: dict) -> bool:
        self._in_flight += 1
        self.peak_in_flight = max(self.peak_in_flight, self._in_flight)
        try:
            uid = str(
                metadata.get("user_id")
                or getattr(getattr(context, "kwargs", None), "user_id", "")
                or ""
            )
            self.processed_user_ids.append(uid)
            await asyncio.sleep(self.delay_sec)
            return True
        finally:
            self._in_flight -= 1


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

    patches = [
        patch(
            "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "utils.inbound_transfer_gate.should_block_handler_until_transfer",
            return_value=False,
        ),
        patch(
            "Agent.CustomerAgent.conversation_memory.prime_session_stage_on_context",
        ),
        patch("utils.intent_stage_reset.try_intent_stage_reset", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
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
    finally:
        for p in patches:
            p.stop()

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
    assert CONFIGURED_LIMITS["message_consumer_max_concurrent"] == 16
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


def _consumer_patch_stack():
    return [
        patch(
            "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "utils.inbound_transfer_gate.should_block_handler_until_transfer",
            return_value=False,
        ),
        patch(
            "Agent.CustomerAgent.conversation_memory.prime_session_stage_on_context",
        ),
        patch("utils.intent_stage_reset.try_intent_stage_reset", return_value=False),
        patch("database.session_store.prime_metadata_session"),
    ]


@pytest.mark.asyncio
async def test_same_shop_multi_account_queues_isolated():
    """
    同店两账号：各自独立队列与消费者，消息不串线。
    """
    shop_id = "570414651"
    accounts = ("184046586", "184046587")
    handlers = {}
    consumers = {}
    queues = {}
    patches = _consumer_patch_stack()
    for p in patches:
        p.start()
    try:
        for uid in accounts:
            qname = queue_name_for_account(shop_id, uid)
            queue_manager.recreate_queue(qname, QueueConfig(max_size=40))
            handler = _AccountTagHandler(expected_user_id=uid)
            consumer = MessageConsumer(qname, max_concurrent=8)
            consumer.handlers = [handler]
            handlers[uid] = handler
            consumers[uid] = consumer
            queues[uid] = queue_manager.get_or_create_queue(qname)
            await consumer.start()

        message_count = 10
        for uid in accounts:
            for i in range(message_count):
                await queues[uid].put(
                    _make_context(f"buyer_{uid}_{i}", shop_id=shop_id, user_id=uid)
                )

        deadline = time.perf_counter() + 25.0
        while time.perf_counter() < deadline:
            done = all(
                len(handlers[uid].processed_user_ids) >= message_count for uid in accounts
            )
            if done:
                break
            await asyncio.sleep(0.02)

        for uid in accounts:
            processed = handlers[uid].processed_user_ids
            assert len(processed) == message_count, (uid, processed)
            assert all(p == uid for p in processed), (uid, processed)
            assert handlers[uid].peak_in_flight >= 2, uid
    finally:
        for uid in accounts:
            await consumers[uid].stop()
        for p in patches:
            p.stop()


@pytest.mark.perf
@pytest.mark.asyncio
async def test_perf_same_shop_multi_account_parallel(capsys):
    """同店双账号并发压测（informational，写入 perf_baseline.json 扩展字段）。"""
    shop_id = "570414651"
    accounts = ("acc_a", "acc_b")
    handlers = {}
    consumers = {}
    queues = {}
    message_count = 16
    patches = _consumer_patch_stack()
    for p in patches:
        p.start()
    try:
        t0 = time.perf_counter()
        for uid in accounts:
            qname = queue_name_for_account(shop_id, uid)
            queue_manager.recreate_queue(qname, QueueConfig(max_size=50))
            handler = _AccountTagHandler(expected_user_id=uid, delay_sec=0.06)
            consumer = MessageConsumer(qname, max_concurrent=8)
            consumer.handlers = [handler]
            handlers[uid] = handler
            consumers[uid] = consumer
            queues[uid] = queue_manager.get_or_create_queue(qname)
            await consumer.start()

        for uid in accounts:
            for i in range(message_count):
                await queues[uid].put(
                    _make_context(f"m_{uid}_{i}", shop_id=shop_id, user_id=uid)
                )

        deadline = time.perf_counter() + 30.0
        while time.perf_counter() < deadline:
            if all(
                len(handlers[uid].processed_user_ids) >= message_count for uid in accounts
            ):
                break
            await asyncio.sleep(0.02)
        elapsed = time.perf_counter() - t0
        peaks = {uid: handlers[uid].peak_in_flight for uid in accounts}
        payload = {
            "multi_account_shop_id": shop_id,
            "accounts": list(accounts),
            "messages_per_account": message_count,
            "elapsed_sec": round(elapsed, 3),
            "peak_parallel_per_account": peaks,
        }
        print(
            f"\nPERF_MULTI_ACCOUNT_ELAPSED_SEC={payload['elapsed_sec']} "
            f"peaks={peaks}"
        )
        try:
            import json
            from pathlib import Path

            out = Path("logs/perf_baseline.json")
            out.parent.mkdir(parents=True, exist_ok=True)
            existing = {}
            if out.is_file():
                existing = json.loads(out.read_text(encoding="utf-8"))
            existing["multi_account"] = payload
            out.write_text(json.dumps(existing, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"PERF_MULTI_ACCOUNT_WRITE_SKIP={exc}")

        for uid in accounts:
            assert len(handlers[uid].processed_user_ids) == message_count
    finally:
        for uid in accounts:
            await consumers[uid].stop()
        for p in patches:
            p.stop()


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


@pytest.mark.perf
@pytest.mark.asyncio
async def test_perf_consumer_latency_p95(capsys):
    """
    可重复运行的性能探针：记录单条消息处理耗时的 P95（毫秒）。
    不作为 CI 门禁，仅输出 PERF_CONSUMER_P95_MS 供基线对比。
    """
    samples_ms: List[float] = []
    n = 24
    handler_delay = 0.04

    class _TimingHandler(_SleepHandler):
        async def handle(self, context, metadata: dict) -> bool:
            t0 = time.perf_counter()
            try:
                return await super().handle(context, metadata)
            finally:
                samples_ms.append((time.perf_counter() - t0) * 1000.0)

    queue_name = f"perf_p95_{int(time.time() * 1000)}"
    queue_manager.recreate_queue(queue_name, QueueConfig(max_size=n + 4))
    handler = _TimingHandler(delay_sec=handler_delay)
    consumer = MessageConsumer(queue_name, max_concurrent=8)
    consumer.handlers = [handler]
    queue = queue_manager.get_or_create_queue(queue_name)
    for i in range(n):
        await queue.put(_make_context(f"perf_buyer_{i}"))

    patches = [
        patch(
            "Message.handlers.ai_reply_watchdog.start_inbound_watchdog",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "utils.inbound_transfer_gate.should_block_handler_until_transfer",
            return_value=False,
        ),
        patch(
            "Agent.CustomerAgent.conversation_memory.prime_session_stage_on_context",
        ),
        patch("utils.intent_stage_reset.try_intent_stage_reset", return_value=False),
    ]
    for p in patches:
        p.start()
    try:
        await consumer.start()
        deadline = time.perf_counter() + 20.0
        while handler.processed_count < n and time.perf_counter() < deadline:
            await asyncio.sleep(0.02)
        await consumer.stop()
    finally:
        for p in patches:
            p.stop()

    assert len(samples_ms) >= n - 1
    p95 = statistics.quantiles(samples_ms, n=20)[18] if len(samples_ms) >= 2 else samples_ms[0]
    p50 = statistics.median(samples_ms)
    payload = {
        "p50_ms": round(float(p50), 2),
        "p95_ms": round(float(p95), 2),
        "samples": len(samples_ms),
        "handler_delay_sec": handler_delay,
        "message_count": n,
    }
    print(
        f"\nPERF_CONSUMER_P50_MS={payload['p50_ms']:.2f} "
        f"PERF_CONSUMER_P95_MS={payload['p95_ms']:.2f} "
        f"samples={payload['samples']}"
    )
    try:
        import json
        from pathlib import Path

        out = Path("logs/perf_baseline.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"PERF_BASELINE_WRITE_SKIP={exc}")


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
        "  · 消息队列消费者：最多同时处理 16 条（不同买家；chat.message_consumer_max_concurrent）"
    )
    print("  · 同一买家多条消息：串行（per-buyer asyncio.Lock）")
    print(f"  · 队列积压上限：{CONFIGURED_LIMITS['queue_max_size']} 条/账号队列（pdd_{{shop}}_{{user}}）")
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
