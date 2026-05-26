"""排队降级：P95 cap、预估公式、活跃计数。"""

import pytest

from Message.ai_queue_load import AIQueueLoadTracker, _percentile


def test_percentile_basic():
    assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 95) >= 4.0


def test_effective_duration_capped_by_prior_when_cold():
    t = AIQueueLoadTracker()
    assert t.effective_duration_sec() == 8.0


def test_should_degrade_when_estimate_exceeds_threshold(monkeypatch):
    def _cfg(k, d=None):
        m = {
            "chat.queue_degrade_enabled": True,
            "chat.queue_degrade_threshold_sec": 120,
            "chat.queue_p95_cap_sec": 30,
            "chat.queue_prior_duration_sec": 8,
            "chat.queue_stats_min_samples": 10,
            "chat.queue_stats_recent_size": 20,
        }
        return m.get(k, d)

    monkeypatch.setattr("Message.ai_queue_load.get_config", _cfg)
    t = AIQueueLoadTracker()
    for _ in range(12):
        t.record_success_duration(10.0)
    t._active = 14
    assert t.estimated_wait_sec() > 120
    assert t.should_queue_degrade()


def test_spike_capped_by_p95_cap(monkeypatch):
    t = AIQueueLoadTracker()
    for _ in range(11):
        t.record_success_duration(8.0)
    t.record_success_duration(60.0)
    eff = t.effective_duration_sec()
    assert eff <= 30.0
