# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""按需 RAG 判定测试。"""

from utils.need_retrieval import need_retrieval, resolve_retrieval_intent


def test_handler_processed_forbids_rag():
    assert (
        need_retrieval(
            intent="price",
            stage="product_qa",
            handler_already_processed=True,
            last_intent=None,
            current_text="多少钱",
        )
        is False
    )


def test_greeting_no_rag():
    assert (
        need_retrieval(
            intent="greeting",
            stage="idle",
            handler_already_processed=False,
            last_intent=None,
            current_text="你好",
        )
        is False
    )


def test_product_intent_rag():
    assert (
        need_retrieval(
            intent="price",
            stage="idle",
            handler_already_processed=False,
            last_intent=None,
            current_text="多少钱",
        )
        is True
    )


def test_follow_up_price_rag():
    assert (
        need_retrieval(
            intent="general",
            stage="idle",
            handler_already_processed=False,
            last_intent="price",
            current_text="那运费呢",
        )
        is True
    )


def test_logistics_stage_no_rag():
    assert (
        need_retrieval(
            intent="general",
            stage="logistics",
            handler_already_processed=False,
            last_intent=None,
            current_text="查一下",
        )
        is False
    )


def test_idle_general_no_rag():
    assert (
        need_retrieval(
            intent="general",
            stage="idle",
            handler_already_processed=False,
            last_intent=None,
            current_text="好的",
        )
        is False
    )


def test_follow_up_blocked_by_refund_keyword():
    assert (
        need_retrieval(
            intent="general",
            stage="idle",
            handler_already_processed=False,
            last_intent="price",
            current_text="价格不合适要退款",
        )
        is False
    )


def test_resolve_retrieval_intent_uses_persisted_product():
    assert (
        resolve_retrieval_intent(
            guessed_intent="general",
            task_intent="product_spec",
        )
        == "product_spec"
    )
    assert (
        resolve_retrieval_intent(
            guessed_intent="price",
            task_intent="product_spec",
        )
        == "price"
    )

