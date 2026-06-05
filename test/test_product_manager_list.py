"""ProductManager 商品列表双通道解析。"""

from Channel.pinduoduo.utils.API.product_manager import ProductManager


def test_parse_chat_recommend_goods():
    pm = ProductManager()
    raw = {
        "result": {
            "onSaleGoods": [
                {
                    "goodsId": 1,
                    "goodsName": "测试",
                    "thumbUrl": "http://x/a.jpg",
                    "minOnSaleGroupPrice": 200,
                    "maxOnSaleGroupPrice": 200,
                    "soldQuantity": 3,
                    "quantity": 10,
                }
            ],
            "total": 1,
        }
    }
    out = pm._parse_product_list(raw)
    assert len(out["products"]) == 1
    assert out["products"][0]["goods_id"] == 1
    assert out["products"][0]["price"] == "2.00"


def test_parse_mall_goods_list():
    pm = ProductManager()
    raw = {
        "result": {
            "goods_list": [
                {
                    "goods_id": 2,
                    "goods_name": "全店商品",
                    "thumb_url": "http://x/b.jpg",
                    "min_on_sale_group_price": 990,
                    "quantity": 5,
                }
            ],
            "total": 1,
        }
    }
    out = pm._parse_mall_goods_list(raw)
    assert len(out["products"]) == 1
    assert out["products"][0]["goods_name"] == "全店商品"
    assert out["products"][0]["price"] == "9.90"


def test_parse_mall_goods_list_list_field():
    """浏览器 goodsList 响应使用 result.list 字段。"""
    pm = ProductManager()
    raw = {
        "success": True,
        "result": {
            "total": 2,
            "list": [
                {
                    "goods_id": 10,
                    "goods_name": "浏览器商品",
                    "min_on_sale_group_price": 1990,
                }
            ],
        },
    }
    out = pm._parse_mall_goods_list(raw)
    assert out["total"] == 2
    assert len(out["products"]) == 1
    assert out["products"][0]["goods_id"] == 10
