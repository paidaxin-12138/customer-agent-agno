#!/usr/bin/env python3
"""
探测 config.json 中 llm（OpenAI 兼容）的最大可持续并发与吞吐。

用法:
  uv run python scripts/benchmark_llm_api.py
  uv run python scripts/benchmark_llm_api.py --levels 1,5,10,15,20
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# 项目根
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import get_config  # noqa: E402


@dataclass
class ReqResult:
    ok: bool
    status: Optional[int] = None
    latency_sec: float = 0.0
    error: str = ""
    rate_limited: bool = False


@dataclass
class LevelReport:
    concurrency: int
    total: int
    ok: int
    rate_limited: int
    other_fail: int
    latencies_ok: List[float] = field(default_factory=list)
    throughput_rps: float = 0.0
    wall_sec: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.ok / self.total if self.total else 0.0

    def p50(self) -> float:
        return statistics.median(self.latencies_ok) if self.latencies_ok else 0.0

    def p95(self) -> float:
        if not self.latencies_ok:
            return 0.0
        xs = sorted(self.latencies_ok)
        i = min(len(xs) - 1, int(len(xs) * 0.95))
        return xs[i]

    def as_dict(self) -> Dict[str, Any]:
        return {
            "concurrency": self.concurrency,
            "total": self.total,
            "ok": self.ok,
            "rate_limited": self.rate_limited,
            "other_fail": self.other_fail,
            "success_rate": round(self.success_rate, 4),
            "wall_sec": round(self.wall_sec, 3),
            "throughput_rps": round(self.throughput_rps, 3),
            "latency_p50_sec": round(self.p50(), 3),
            "latency_p95_sec": round(self.p95(), 3),
        }


def _mask_key(key: str) -> str:
    if not key:
        return "(empty)"
    if len(key) <= 8:
        return "***"
    return key[:4] + "..." + key[-4:]


async def _one_chat(
    client: Any,
    model: str,
    max_tokens: int,
    temperature: float,
    req_id: int,
) -> ReqResult:
    t0 = time.perf_counter()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": f"压测#{req_id}：只回复一个字「好」，不要其它内容。"},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        _ = resp.choices[0].message.content
        return ReqResult(ok=True, latency_sec=time.perf_counter() - t0)
    except Exception as e:
        lat = time.perf_counter() - t0
        err = str(e)
        status = getattr(e, "status_code", None)
        if status is None and hasattr(e, "response"):
            try:
                status = e.response.status_code
            except Exception:
                pass
        rl = status == 429 or "429" in err or "rate" in err.lower() or "limit" in err.lower()
        return ReqResult(
            ok=False,
            status=status,
            latency_sec=lat,
            error=err[:200],
            rate_limited=rl,
        )


async def run_level(
    client: Any,
    model: str,
    concurrency: int,
    requests_per_level: int,
    max_tokens: int,
    temperature: float,
) -> LevelReport:
    sem = asyncio.Semaphore(concurrency)
    results: List[ReqResult] = []

    async def worker(i: int):
        async with sem:
            results.append(
                await _one_chat(client, model, max_tokens, temperature, i)
            )

    t0 = time.perf_counter()
    await asyncio.gather(*[worker(i) for i in range(requests_per_level)])
    wall = time.perf_counter() - t0

    ok = [r for r in results if r.ok]
    rl = sum(1 for r in results if r.rate_limited)
    other = len(results) - len(ok) - rl
    rep = LevelReport(
        concurrency=concurrency,
        total=len(results),
        ok=len(ok),
        rate_limited=rl,
        other_fail=other,
        latencies_ok=[r.latency_sec for r in ok],
        wall_sec=wall,
        throughput_rps=len(ok) / wall if wall > 0 else 0.0,
    )
    return rep


async def sustained_probe(
    client: Any,
    model: str,
    concurrency: int,
    duration_sec: float,
    max_tokens: int,
    temperature: float,
) -> Dict[str, Any]:
    """在固定并发下持续打满 duration_sec 秒。"""
    end = time.perf_counter() + duration_sec
    counter = 0
    ok = rl = fail = 0
    lats: List[float] = []
    lock = asyncio.Lock()

    async def loop_worker():
        nonlocal counter, ok, rl, fail
        while time.perf_counter() < end:
            async with lock:
                counter += 1
                rid = counter
            r = await _one_chat(client, model, max_tokens, temperature, rid)
            async with lock:
                if r.ok:
                    ok += 1
                    lats.append(r.latency_sec)
                elif r.rate_limited:
                    rl += 1
                else:
                    fail += 1

    t0 = time.perf_counter()
    await asyncio.gather(*[loop_worker() for _ in range(concurrency)])
    wall = time.perf_counter() - t0
    return {
        "concurrency": concurrency,
        "duration_target_sec": duration_sec,
        "wall_sec": round(wall, 3),
        "completed": ok + rl + fail,
        "ok": ok,
        "rate_limited": rl,
        "other_fail": fail,
        "throughput_rps": round(ok / wall, 3) if wall else 0,
        "latency_p50_sec": round(statistics.median(lats), 3) if lats else 0,
    }


def _recommend_max(levels: List[LevelReport]) -> Dict[str, Any]:
    """成功率>=95% 且无限流的最高并发；并给出首个出现限流的并发。"""
    best = 0
    first_rl = None
    for r in levels:
        if r.rate_limited > 0 and first_rl is None:
            first_rl = r.concurrency
        if r.success_rate >= 0.95 and r.rate_limited == 0:
            best = max(best, r.concurrency)
    return {"max_stable_concurrency_95pct": best, "first_rate_limit_at": first_rl}


async def main_async(args: argparse.Namespace) -> int:
    try:
        from openai import AsyncOpenAI
    except ImportError:
        print("需要 openai 包: uv add openai")
        return 1

    api_key = get_config("llm.api_key", "")
    api_base = get_config("llm.api_base", "")
    model = get_config("llm.model_name", "")
    max_tokens = min(int(get_config("llm.max_tokens", 64) or 64), 32)
    temperature = float(get_config("llm.temperature", 0.3) or 0.3)

    if not api_key or not api_base or not model:
        print("config.json 中 llm.api_key / api_base / model_name 未配置完整")
        return 1

    levels = [int(x) for x in args.levels.split(",") if x.strip()]
    client = AsyncOpenAI(api_key=api_key, base_url=api_base.rstrip("/"))

    print("=" * 60)
    print("LLM API 并发压测（直连 Chat Completions）")
    print(f"  base_url : {api_base}")
    print(f"  model    : {model}")
    print(f"  api_key  : {_mask_key(api_key)}")
    print(f"  max_tokens(压测): {max_tokens}")
    print(f"  每档请求数: {args.requests_per_level}")
    print(f"  并发档位: {levels}")
    print("=" * 60)

    reports: List[LevelReport] = []
    for c in levels:
        print(f"\n>>> 并发 {c} ...", flush=True)
        rep = await run_level(
            client, model, c, args.requests_per_level, max_tokens, temperature
        )
        reports.append(rep)
        d = rep.as_dict()
        print(
            f"    成功 {d['ok']}/{d['total']} "
            f"限流 {d['rate_limited']} 其它失败 {d['other_fail']} "
            f"吞吐 {d['throughput_rps']} req/s "
            f"P50 {d['latency_p50_sec']}s P95 {d['latency_p95_sec']}s"
        )
        if rep.other_fail and args.verbose:
            for r in [x for x in []]:  # placeholder
                pass
        await asyncio.sleep(args.pause_between_levels)

    rec = _recommend_max(reports)
    max_stable = rec["max_stable_concurrency_95pct"]
    print("\n" + "=" * 60)
    print("阶段结论（阶梯并发）")
    print(f"  建议稳定并发上限（成功率≥95% 且无限流）: {max_stable or '未测出（可能首档就限流）'}")
    if rec["first_rate_limit_at"]:
        print(f"  首次出现限流(429等)的并发档位: {rec['first_rate_limit_at']}")

    sustained_result = None
    if max_stable > 0 and args.sustained_sec > 0:
        probe_c = max_stable
        print(f"\n>>> 持续压测 {args.sustained_sec}s @ 并发 {probe_c} ...", flush=True)
        sustained_result = await sustained_probe(
            client, model, probe_c, args.sustained_sec, max_tokens, temperature
        )
        print(f"    完成 {sustained_result['completed']} 成功 {sustained_result['ok']} "
              f"限流 {sustained_result['rate_limited']} "
              f"吞吐 {sustained_result['throughput_rps']} req/s")

    out = {
        "provider_hint": "dashscope_compatible" if "dashscope" in api_base else "openai_compatible",
        "model": model,
        "api_base": api_base,
        "levels": [r.as_dict() for r in reports],
        "recommendation": rec,
        "sustained": sustained_result,
        "note": "压测使用极短回复；实际客服含知识库检索+长 prompt，单条耗时会更高。",
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完整 JSON 已写入: {out_path}")

    desktop = Path.home() / "Desktop" / "LLM-API并发压测结果.md"
    _write_markdown_report(desktop, out)
    print(f"桌面报告: {desktop}")
    return 0


def _write_markdown_report(path: Path, data: Dict[str, Any]) -> None:
    lines = [
        "# LLM API 最大并发压测报告",
        "",
        f"- **模型**: `{data.get('model')}`",
        f"- **接口**: `{data.get('api_base')}`",
        f"- **说明**: 直连 Chat Completions，极短回复；不代表含知识库/工具调用的全链路耗时。",
        "",
        "## 阶梯并发",
        "",
        "| 并发 | 成功/总数 | 限流 | 其它失败 | 成功率 | 吞吐(req/s) | P50(s) | P95(s) |",
        "|------|-----------|------|----------|--------|-------------|--------|--------|",
    ]
    for row in data.get("levels", []):
        lines.append(
            f"| {row['concurrency']} | {row['ok']}/{row['total']} | {row['rate_limited']} | "
            f"{row['other_fail']} | {row['success_rate']*100:.1f}% | {row['throughput_rps']} | "
            f"{row['latency_p50_sec']} | {row['latency_p95_sec']} |"
        )
    rec = data.get("recommendation") or {}
    lines.extend(
        [
            "",
            "## 结论",
            "",
            f"- **建议稳定并发上限**（≥95% 成功且无限流）: **{rec.get('max_stable_concurrency_95pct', 0)}**",
            f"- **首次出现限流的并发档位**: {rec.get('first_rate_limit_at') or '本次未观察到'}",
            "",
        ]
    )
    sus = data.get("sustained")
    if sus:
        lines.extend(
            [
                "## 持续压测",
                "",
                f"- 并发 {sus['concurrency']}，目标 {sus['duration_target_sec']}s",
                f"- 成功 {sus['ok']}，限流 {sus['rate_limited']}，吞吐 **{sus['throughput_rps']} req/s**",
                "",
            ]
        )
    lines.append(
        "应用内 `MessageConsumer` 默认最多 **10** 路同时调 LLM；若 API 稳定并发低于 10，"
        "高峰会出现排队；若高于 10，程序侧可先改 `max_concurrent` 才能吃满 API 能力。"
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--levels", default="1,2,5,8,10,12,15,20,25,30")
    p.add_argument("--requests-per-level", type=int, default=24)
    p.add_argument("--pause-between-levels", type=float, default=1.0)
    p.add_argument("--sustained-sec", type=float, default=30.0)
    p.add_argument("--verbose", action="store_true")
    p.add_argument(
        "--output",
        default=str(ROOT / "temp" / "llm_api_benchmark.json"),
    )
    args = p.parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
