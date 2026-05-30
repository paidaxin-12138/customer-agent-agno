"""转人工语义/错别字识别"""

from utils.human_transfer_intent import detect_human_transfer_intent


def test_exact_transfer():
    assert detect_human_transfer_intent("转人工")
    assert detect_human_transfer_intent("我要转人工客服")


def test_typo_zhuan():
    assert detect_human_transfer_intent("赚人工")
    assert detect_human_transfer_intent("砖人工")
    assert detect_human_transfer_intent("赚人功")
    assert detect_human_transfer_intent("专人工")


def test_semantic_variants():
    assert detect_human_transfer_intent("有没有人工")
    assert detect_human_transfer_intent("客服在吗")
    assert detect_human_transfer_intent("找真人")


def test_not_transfer():
    assert not detect_human_transfer_intent("这款多少钱")
    assert not detect_human_transfer_intent("")
    assert not detect_human_transfer_intent("人工草坪多少钱")
    assert not detect_human_transfer_intent("这个是人工做的吗")
    assert not detect_human_transfer_intent("纯手工制作吗")
    assert not detect_human_transfer_intent("是人工的吗")
