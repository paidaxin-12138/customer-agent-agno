"""会话阶段常量（中性包，供 Agent / Message / utils 共享，避免循环依赖）。"""
from __future__ import annotations

from typing import FrozenSet

BUSINESS_FLOW_STAGES: FrozenSet[str] = frozenset(
    {"address_change", "logistics", "after_sales", "await_confirm"}
)

ALL_HANDLER_STAGES: FrozenSet[str] = frozenset(
    {
        "idle",
        "address_change",
        "after_sales",
        "logistics",
        "product_qa",
        "recommend",
        "await_confirm",
    }
)

VALID_SESSION_STAGES: FrozenSet[str] = ALL_HANDLER_STAGES
