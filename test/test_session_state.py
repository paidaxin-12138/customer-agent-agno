# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""SessionMemory 统一写入测试。"""

import json
from unittest.mock import MagicMock, patch

from Agent.CustomerAgent.conversation_memory import (
    TaskState,
    update_session_state,
    _format_current_flow,
)


def test_task_state_stage_migration():
    st = TaskState.from_dict({"flow_node": "logistics", "intent": "logistics"})
    assert st.stage == "logistics"


def test_format_current_flow_block():
    st = TaskState(stage="product_qa", slots={"color": "黑"})
    block = _format_current_flow(st)
    assert "【当前流程】" in block
    assert "product_qa" in block
    assert "黑" in block


def test_update_session_state_merges_slots():
    mem = {"task_state_json": json.dumps({"intent": "general", "slots": {"a": "1"}})}
    mock_db = MagicMock()
    mock_db.get_session_memory.return_value = mem

    with patch("database.db_manager.db_manager", mock_db):
        task = update_session_state(42, slots={"b": "2"}, stage="after_sales", source_handler="T")
    assert task.slots == {"a": "1", "b": "2"}
    assert task.stage == "after_sales"
    mock_db.update_session_memory.assert_called_once()
