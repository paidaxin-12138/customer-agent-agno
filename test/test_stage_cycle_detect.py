"""stage_history 短周期环检测。"""
import time

from Agent.CustomerAgent.conversation_memory import (
    TaskState,
    _detect_stage_cycle,
    update_session_state,
)


def test_detect_stage_cycle_true(monkeypatch):
    monkeypatch.setattr(
        "Agent.CustomerAgent.conversation_memory.get_config",
        lambda k, d=None: {
            "chat.stage_cycle_detect_enabled": True,
            "chat.stage_cycle_window_sec": 120,
            "chat.stage_cycle_repeat_threshold": 3,
        }.get(k, d),
    )
    now = time.time()
    fp = '[["order_sn", "123"]]'
    task = TaskState(
        stage="address_change",
        slots={"order_sn": "123"},
        stage_history=[
            {"stage": "address_change", "at": now - 10, "slots_fp": fp},
            {"stage": "address_change", "at": now - 5, "slots_fp": fp},
        ],
    )
    assert _detect_stage_cycle(task, "address_change") is True


def test_update_session_state_breaks_cycle(monkeypatch):
    monkeypatch.setattr(
        "Agent.CustomerAgent.conversation_memory.get_config",
        lambda k, d=None: {
            "chat.stage_cycle_detect_enabled": True,
            "chat.stage_cycle_window_sec": 120,
            "chat.stage_cycle_repeat_threshold": 2,
        }.get(k, d),
    )
    now = time.time()
    task = TaskState(
        stage="address_change",
        stage_history=[
            {"stage": "address_change", "at": now - 5, "slots_fp": ""},
        ],
    )

    def fake_get_memory(sid):
        return {"task_state_json": __import__("json").dumps(task.to_dict())}

    def fake_update(sid, **kwargs):
        return True

    from database.db_manager import db_manager

    monkeypatch.setattr(db_manager, "get_session_memory", fake_get_memory)
    monkeypatch.setattr(db_manager, "update_session_memory", fake_update)
    result = update_session_state(
        1,
        stage="address_change",
        source_handler="TestHandler",
    )
    assert result.stage == "idle"
