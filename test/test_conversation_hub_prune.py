# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""ConversationHub 内存索引裁剪。"""
from ui.conversation_hub import ConversationHub, _ConvState


def test_hub_prunes_overflow_buyers(monkeypatch):
    monkeypatch.setattr("ui.conversation_hub._MAX_BUYERS_PER_ACCOUNT", 3)
    hub = ConversationHub()
    with hub._lock:
        acc = hub._by_account.setdefault("pinduoduo_s1_u1", {})
        for i in range(5):
            acc[f"buyer_{i}"] = _ConvState(updated_at=float(i))
        hub._prune_memory_cache()
        assert len(acc) == 3
        assert "buyer_0" not in acc
        assert "buyer_4" in acc


def test_hub_prunes_overflow_accounts(monkeypatch):
    monkeypatch.setattr("ui.conversation_hub._MAX_HUB_ACCOUNTS", 2)
    hub = ConversationHub()
    with hub._lock:
        hub._by_account["acc_old"] = {
            "b1": _ConvState(updated_at=1.0),
        }
        hub._by_account["acc_new"] = {
            "b1": _ConvState(updated_at=99.0),
        }
        hub._by_account["acc_mid"] = {
            "b1": _ConvState(updated_at=50.0),
        }
        hub._prune_memory_cache()
        assert "acc_old" not in hub._by_account
        assert len(hub._by_account) == 2
