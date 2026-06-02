"""显式转人工意图识别。"""
from utils.human_transfer_intent import has_explicit_transfer_intent


def test_explicit_transfer_human():
    assert has_explicit_transfer_intent("我要转人工")
    assert has_explicit_transfer_intent("找经理")


def test_not_transfer():
    assert not has_explicit_transfer_intent("这款多少钱")
    assert not has_explicit_transfer_intent("纯手工制作")
