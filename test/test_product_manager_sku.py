"""ProductManager SKU 解析单元测试（不请求网络）。"""

from Channel.pinduoduo.utils.API.product_manager import ProductManager


def test_parse_sku_entries_name_price_quantity():
    pm = ProductManager()
    skus = [
        {
            "sku_id": 9001,
            "quantity": 12,
            "group_price": 1990,
            "spec": [
                {"parent_name": "颜色", "spec_name": "粉色"},
                {"parent_name": "功率", "spec_name": "48W"},
            ],
        },
        {
            "skuId": 9002,
            "stock": 0,
            "multiPrice": 2490,
            "spec": [{"parentName": "颜色", "specName": "白色"}],
        },
    ]
    rows = pm._parse_sku_entries(skus)
    assert len(rows) == 2
    assert rows[0]["sku_name"] == "颜色: 粉色 | 功率: 48W"
    assert rows[0]["sku_id"] == 9001
    assert rows[0]["quantity"] == 12
    assert rows[0]["price"] == 19.9
    assert rows[1]["sku_name"] == "颜色: 白色"
    assert rows[1]["quantity"] == 0
    assert rows[1]["price"] == 24.9


def test_parse_product_detail_includes_sku_list():
    pm = ProductManager()
    raw = {
        "result": {
            "goodsId": 123,
            "goodsName": "测试灯",
            "skus": [
                {
                    "sku_id": 1,
                    "quantity": 5,
                    "group_price": 1000,
                    "spec": [{"parent_name": "款", "spec_name": "标准"}],
                }
            ],
        }
    }
    info = pm._parse_product_detail(raw)
    assert info["goods_id"] == 123
    assert len(info["sku_list"]) == 1
    assert info["sku_list"][0]["sku_name"] == "款: 标准"
    assert info["sku_list"][0]["price"] == 10.0
