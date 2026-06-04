"""按需 RAG 判定测试。"""

from utils.need_retrieval import need_retrieval


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

