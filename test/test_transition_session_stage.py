"""transition_session_stage 统一入口。"""
from unittest.mock import patch

from Agent.CustomerAgent.conversation_memory import transition_session_stage


def test_transition_delegates_with_source_handler():
    with patch(
        "Agent.CustomerAgent.conversation_memory.update_session_state",
        return_value="task",
    ) as mock_update:
        result = transition_session_stage(
            7,
            stage="after_sales",
            source_handler="TestHandler",
            metadata={"k": 1},
        )
    assert result == "task"
    mock_update.assert_called_once()
    kwargs = mock_update.call_args.kwargs
    assert kwargs["stage"] == "after_sales"
    assert kwargs["source_handler"] == "TestHandler"
    assert kwargs["metadata"] == {"k": 1}
