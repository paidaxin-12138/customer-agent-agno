# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""显式转人工意图识别。"""
from utils.human_transfer_intent import has_explicit_transfer_intent


def test_explicit_transfer_human():
    assert has_explicit_transfer_intent("我要转人工")
    assert has_explicit_transfer_intent("找经理")


def test_not_transfer():
    assert not has_explicit_transfer_intent("这款多少钱")
    assert not has_explicit_transfer_intent("纯手工制作")
