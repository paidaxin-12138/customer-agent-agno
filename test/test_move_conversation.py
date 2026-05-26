from Agent.CustomerAgent.tools.move_conversation import _select_best_cs_uid


def test_select_best_cs_uid_skips_self_and_offline():
    cs_list = {
        "cs_1_1": {"online": True, "current_sessions": 3},
        "cs_1_2": {"online": False, "current_sessions": 0},
        "cs_1_3": {"online": True, "current_sessions": 1},
    }
    assert _select_best_cs_uid(cs_list, "cs_1_1") == "cs_1_3"


def test_select_best_cs_uid_fallback_when_missing_fields():
    cs_list = {
        "cs_1_1": {},
        "cs_1_2": {"load": "2"},
        "cs_1_3": {"session_count": 1},
    }
    assert _select_best_cs_uid(cs_list, "cs_1_1") == "cs_1_3"
