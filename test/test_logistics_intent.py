"""物流意图检测。"""
from utils.logistics_intent import is_logistics_intent


def test_logistics_strong_keywords():
    assert is_logistics_intent("帮我查一下物流")
    assert is_logistics_intent("快递到哪了")


def test_logistics_negative():
    assert not is_logistics_intent("")
    assert not is_logistics_intent("你好")


def test_logistics_tracking_number():
    assert is_logistics_intent("SF1234567890123")
