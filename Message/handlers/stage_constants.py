"""Stage 门禁共享常量（业务 Handler + 全阶段 Handler）。"""

from __future__ import annotations

from typing import FrozenSet

# 业务流阶段（超时 / 意图重置目标）
BUSINESS_FLOW_STAGES: FrozenSet[str] = frozenset(
    {"address_change", "logistics", "after_sales", "await_confirm"}
)

# 关键词 / 情绪 / 图片等应可在任意业务阶段触发
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

# 持久化 task_state.stage 合法值（含业务流 + 商品问答）
VALID_SESSION_STAGES: FrozenSet[str] = ALL_HANDLER_STAGES
