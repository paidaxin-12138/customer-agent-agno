"""地址解析与改址意图检测。"""

from utils.address_parse import (
    AddressParseLevel,
    address_parse_level,
    is_address_change_intent,
    parse_address_from_text,
)


def test_is_address_change_intent():
    assert is_address_change_intent("我想改地址")
    assert is_address_change_intent("修改收货地址")
    assert not is_address_change_intent("物流到哪了")


def test_parse_complete_address():
    text = "改地址 广东省深圳市南山区科技园南路1号 张三 13800138000"
    parsed = parse_address_from_text(text)
    assert parsed.mobile == "13800138000"
    assert parsed.name == "张三"
    assert parsed.district == "南山区"
    assert address_parse_level(parsed) == AddressParseLevel.COMPLETE


def test_parse_partial_address():
    parsed = parse_address_from_text("改地址 科技园南路1号")
    assert address_parse_level(parsed) == AddressParseLevel.PARTIAL


def test_parse_none_intent_only():
    parsed = parse_address_from_text("改地址")
    assert address_parse_level(parsed) == AddressParseLevel.NONE
