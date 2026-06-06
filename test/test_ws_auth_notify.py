"""ws_auth_notify：AUTH 成功/失败通知。"""
from unittest.mock import MagicMock

from Channel.pinduoduo.ws_auth_notify import (
    AUTH_FAIL_FATAL_THRESHOLD,
    clear_auth_callbacks,
    notify_auth_success,
    pop_fatal_auth_message,
    record_auth_failure,
    register_auth_stop_callback,
    register_auth_success_callback,
)


def test_notify_auth_success_once():
    cb = MagicMock()
    register_auth_success_callback("shop_u", cb)
    notify_auth_success("shop_u")
    notify_auth_success("shop_u")
    cb.assert_called_once()
    clear_auth_callbacks("shop_u")


def test_clear_auth_callbacks():
    cb = MagicMock()
    register_auth_success_callback("k", cb)
    clear_auth_callbacks("k")
    notify_auth_success("k")
    cb.assert_not_called()


def test_record_auth_failure_triggers_stop_and_fatal():
    stop_cb = MagicMock()
    register_auth_stop_callback("shop_u", stop_cb)
    fatal = False
    for _ in range(AUTH_FAIL_FATAL_THRESHOLD):
        fatal = record_auth_failure("shop_u", username="测试店")
    assert fatal is True
    stop_cb.assert_called_once()
    msg = pop_fatal_auth_message("shop_u")
    assert msg is not None
    assert "用户管理" in msg
    clear_auth_callbacks("shop_u")


def test_notify_auth_success_clears_fail_streak():
    register_auth_stop_callback("shop_u", MagicMock())
    record_auth_failure("shop_u", username="a")
    record_auth_failure("shop_u", username="a")
    cb = MagicMock()
    register_auth_success_callback("shop_u", cb)
    notify_auth_success("shop_u")
    assert pop_fatal_auth_message("shop_u") is None
    fatal = record_auth_failure("shop_u", username="a")
    assert fatal is False
    clear_auth_callbacks("shop_u")
