from utils.best_effort import run_best_effort


def test_run_best_effort_returns_value_on_success():
    assert run_best_effort("ok", lambda: 42) == 42


def test_run_best_effort_swallows_exception():
    def boom():
        raise RuntimeError("fail")

    assert run_best_effort("boom", boom) is None
