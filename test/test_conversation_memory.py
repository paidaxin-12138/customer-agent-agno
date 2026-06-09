# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""三层记忆切分与组装测试。"""

from Agent.CustomerAgent.conversation_memory import (
    TaskState,
    _split_rounds,
    _update_task_state,
    LongTermSummary,
)


def test_split_rounds_keeps_last_n_buyer_rounds():
    msgs = []
    for i in range(5):
        msgs.append({"id": i * 2, "sender_type": "customer", "content": f"买{i}"})
        msgs.append({"id": i * 2 + 1, "sender_type": "ai", "content": f"答{i}"})
    short, old = _split_rounds(msgs, max_rounds=2)
    assert len(old) == 6
    assert len(short) == 4
    assert short[-1]["content"] == "答4"


def test_task_state_slots():
    st = TaskState()
    _update_task_state(st, "订单号1234567890 要黑色的", "好的亲", intent="product_spec")
    assert st.intent == "product_spec"
    assert "color" in st.slots


def test_long_term_merge():
    a = LongTermSummary(user_requests=["a"])
    b = LongTermSummary(user_requests=["b"])
    a.merge(b)
    assert a.user_requests == ["a", "b"]
