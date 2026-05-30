from typing import Optional

from ..base_request import BaseRequest
from utils.product_image_urls import collect_product_images


class ProductManager(BaseRequest):
    """
    拼多多商品管理API
    提供商品列表查询和商品详情获取功能
    """

    @staticmethod
    def _pick(d: dict, *keys, default=None):
        for k in keys:
            if k in d and d.get(k) is not None:
                return d.get(k)
        return default

    def _mms_browser_headers(self, referer: str) -> dict:
        """与商家后台 MMS 接口一致的 JSON 请求头（含 Cookie 中的 anti-content）。"""
        anti_content = self.cookies.get("anti_content") or self.cookies.get("anti-content", "")
        ua = self.default_headers.get(
            "User-Agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36",
        )
        return {
            "accept": "application/json, text/plain, */*",
            "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
            "anti-content": anti_content or "",
            "content-type": "application/json;charset=UTF-8",
            "origin": "https://mms.pinduoduo.com",
            "referer": referer,
            "user-agent": ua,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }

    def _resolve_mms_uid(self) -> str:
        """商家后台 recommendGoods 需要的客服 uid（seller user_id）。"""
        if self.user_id:
            return str(self.user_id).strip()
        for key in ("uid", "USER_ID", "user_id", "api_uid", "PASS_ID"):
            val = (self.cookies or {}).get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        return ""

    def __init__(self, shop_id: str = None, user_id: str = None, cookies=None):
        """
        初始化商品管理器

        Args:
            shop_id: 店铺ID，用于从数据库获取cookies
            user_id: 用户ID，用于从数据库获取cookies
            cookies: 登录cookies，如果直接传入则不需要从数据库获取
        """
        super().__init__(shop_id=shop_id, user_id=user_id)
        if cookies:
            self.update_cookies(cookies)

    def _resolve_mms_uid(self) -> str:
        """商家后台 recommendGoods 需要的 uid（聊天场景为**买家** UID，非客服账号）。"""
        for key in ("uid", "USER_ID", "user_id", "api_uid"):
            val = (self.cookies or {}).get(key)
            if val is not None and str(val).strip():
                return str(val).strip()
        if self.user_id:
            return str(self.user_id).strip()
        return ""

    def _mall_goods_list_headers(self) -> dict:
        headers = self._mms_browser_headers("https://mms.pinduoduo.com/goods/goods_list")
        headers["priority"] = "u=1, i"
        return headers

    def _fetch_mall_goods_list(self, page: int = 1, size: int = 10) -> Optional[dict]:
        """商家后台「商品列表」全店在售（用于知识库同步，无需买家 UID）。"""
        url = "https://mms.pinduoduo.com/vodka/v2/mms/query/display/mall/goodsList"
        data = {
            "page": int(page),
            "page_size": int(size),
            "pre_sale_type": 0,
            "out_goods_sn_gray_flag": True,
            "shipment_time_type": 3,
            "is_onsale": 1,
            "sold_out": 0,
            "order_by": "created_at:desc,id:desc",
        }
        return self.post(url, json_data=data, headers=self._mall_goods_list_headers())

    def _fetch_chat_recommend_goods(
        self, buyer_uid: str, page: int = 1, size: int = 10
    ) -> Optional[dict]:
        """聊天工作台 recommendGoods（uid=买家 UID，需 showType=1）。"""
        url = "https://mms.pinduoduo.com/latitude/goods/recommendGoods"
        data = {
            "uid": str(buyer_uid).strip(),
            "pageNum": int(page),
            "pageSize": int(size),
            "showType": 1,
        }
        headers = self._mms_browser_headers(
            "https://mms.pinduoduo.com/chat-merchant/index.html"
        )
        headers["priority"] = "u=1, i"
        return self.post(url, json_data=data, headers=headers)

    def get_product_list(self, page=1, size=10, buyer_uid: Optional[str] = None):
        """
        获取店铺商品列表。

        Args:
            page: 页码
            size: 每页数量
            buyer_uid: 聊天场景传入**买家 UID** 时走 recommendGoods；
                       未传时走商家后台全店 goodsList（知识库同步用）。

        Returns:
            dict: success / products / total / page / error_msg
        """
        page = int(page)
        size = int(size)
        buyer = (buyer_uid or "").strip()

        if buyer:
            result = self._fetch_chat_recommend_goods(buyer, page=page, size=size)
            source = "chat_recommend"
        else:
            result = self._fetch_mall_goods_list(page=page, size=size)
            source = "mall_goods_list"

        if result and result.get("success") is True:
            if source == "mall_goods_list":
                products_data = self._parse_mall_goods_list(result)
            else:
                products_data = self._parse_product_list(result)
            return {
                "success": True,
                "products": products_data.get("products", []),
                "total": products_data.get("total", 0),
                "page": page,
                "source": source,
            }

        error_msg = (
            (result.get("errorMsg") or result.get("error_msg")) if result else None
        ) or "获取商品列表失败"
        if not buyer and "频繁" in str(error_msg):
            error_msg = (
                f"{error_msg}（商家后台商品列表接口限流，请稍后再试「同步商品」）"
            )
        elif not buyer and "bad params" in str(error_msg).lower():
            error_msg = (
                "商品列表接口参数无效。全店同步请稍后重试；"
                "若在对话中查商品，需有买家会话上下文。"
            )
        self.logger.error(f"获取商品列表失败 [{source}]: {error_msg}")
        return {
            "success": False,
            "error_msg": error_msg,
            "products": [],
            "total": 0,
            "page": page,
            "source": source,
        }

    def get_product_detail(self, goods_id):
        """
        根据商品ID获取商品详细信息

        Args:
            goods_id (int): 商品ID

        Returns:
            dict: 商品详情结果，格式如下：
                {
                    "success": True/False,
                    "product_info": {
                        "goods_id": int,
                        "goods_name": str,
                        "thumb_url": str,
                        "hd_thumb_url": str,
                        "specifications": list,
                        "sku_list": list,
                        "description": str,
                        "brief": str,
                        "quantity": int | None,
                        "sku_count": int,
                        "price_min_fen": int | None,
                        "price_max_fen": int | None,
                    },
                    "error_msg": str  # 仅在失败时包含
                }
        """
        if not goods_id:
            self.logger.error("商品ID不能为空")
            return {"success": False, "error_msg": "商品ID不能为空"}

        # 构建请求URL
        url = "https://mms.pinduoduo.com/glide/v2/mms/query/commit/on_shop/detail"

        # 构建请求数据
        data = {"goods_id": goods_id}

        headers = self._mms_browser_headers("https://mms.pinduoduo.com/chat-merchant/index.html")

        # 发起请求
        result = self.post(url, json_data=data, headers=headers)

        if result and result.get("success") == True:
            # 解析商品详细信息
            product_info = self._parse_product_detail(result)
            return {
                "success": True,
                "product_info": product_info,
                "api_result": result,
            }
        else:
            error_msg = result.get('errorMsg') if result else "获取商品详情失败"
            self.logger.error(f"获取商品详情失败 (goods_id={goods_id}): {error_msg}")
            return {
                "success": False,
                "error_msg": error_msg
            }

    def _parse_product_list(self, response_data):
        """
        解析商品列表响应数据

        Args:
            response_data (dict): API响应数据

        Returns:
            dict: 解析后的商品列表数据
        """
        try:
            result_data = response_data.get('result', {})
            # 聊天推荐接口：recommendGoods；部分环境仍返回 onSaleGoods
            goods_list = (
                result_data.get('onSaleGoods')
                or result_data.get('recommendGoods')
                or []
            )

            products = []
            for goods in goods_list:
                # 价格：使用区间价格，最低价-最高价
                min_price = goods.get('minOnSaleGroupPrice')
                max_price = goods.get('maxOnSaleGroupPrice')
                if min_price and max_price and min_price != max_price:
                    price_str = f"{min_price/100:.2f}-{max_price/100:.2f}"
                elif min_price:
                    price_str = f"{min_price/100:.2f}"
                else:
                    price_str = None

                # 提取商品标签
                goods_tag = goods.get('goodsTag', {})
                marketing_tags = goods_tag.get('marketingTags', [])
                tag_str = ', '.join(marketing_tags) if marketing_tags else ''

                product = {
                    "goods_id": goods.get('goodsId'),
                    "goods_name": goods.get('goodsName', ''),
                    "thumb_url": goods.get('thumbUrl', ''),
                    "price": price_str,
                    "price_min": min_price,
                    "price_max": max_price,
                    "sold_quantity": goods.get('soldQuantity', 0),
                    "sold_quantity_30d": goods.get('soldQuantity30d', 0),
                    "quantity": goods.get('quantity', 0),  # 库存
                    "goods_type": goods.get('goodsType', ''),
                    "is_spike": goods.get('isSpike', False),  # 是否秒杀
                    "support_customize": goods.get('supportCustomize', False),  # 是否支持定制
                    "goods_url": goods.get('goodsUrl', ''),  # 商品链接
                    "tag": tag_str,
                }
                products.append(product)

            return {
                "products": products,
                "total": result_data.get('total', len(products))
            }

        except Exception as e:
            self.logger.error(f"解析商品列表失败: {str(e)}")
            return {
                "products": [],
                "total": 0
            }

    def _parse_mall_goods_list(self, response_data: dict) -> dict:
        """解析商家后台 goodsList 接口（全店在售）。"""
        try:
            result_data = response_data.get("result", {}) or {}
            goods_list = (
                result_data.get("goods_list")
                or result_data.get("goodsList")
                or []
            )
            products = []
            for goods in goods_list:
                if not isinstance(goods, dict):
                    continue
                min_price = self._pick(
                    goods,
                    "min_on_sale_group_price",
                    "minOnSaleGroupPrice",
                    "min_group_price",
                    "minGroupPrice",
                )
                max_price = self._pick(
                    goods,
                    "max_on_sale_group_price",
                    "maxOnSaleGroupPrice",
                    "max_group_price",
                    "maxGroupPrice",
                )
                if min_price and max_price and min_price != max_price:
                    price_str = f"{min_price/100:.2f}-{max_price/100:.2f}"
                elif min_price:
                    price_str = f"{min_price/100:.2f}"
                else:
                    price_str = None
                products.append(
                    {
                        "goods_id": self._pick(goods, "goods_id", "goodsId", "id"),
                        "goods_name": self._pick(goods, "goods_name", "goodsName", default=""),
                        "thumb_url": self._pick(
                            goods, "thumb_url", "thumbUrl", "image_url", default=""
                        ),
                        "price": price_str,
                        "price_min": min_price,
                        "price_max": max_price,
                        "sold_quantity": goods.get("sold_quantity")
                        or goods.get("soldQuantity")
                        or 0,
                        "sold_quantity_30d": goods.get("sold_quantity_30d")
                        or goods.get("soldQuantity30d")
                        or 0,
                        "quantity": goods.get("quantity", 0),
                        "goods_type": goods.get("goods_type") or goods.get("goodsType", ""),
                        "is_spike": goods.get("is_spike") or goods.get("isSpike", False),
                        "support_customize": goods.get("support_customize")
                        or goods.get("supportCustomize", False),
                        "goods_url": goods.get("goods_url") or goods.get("goodsUrl", ""),
                        "tag": "",
                    }
                )
            total = (
                result_data.get("total")
                or result_data.get("total_count")
                or result_data.get("totalCount")
                or len(products)
            )
            return {"products": products, "total": total}
        except Exception as e:
            self.logger.error(f"解析商家商品列表失败: {e}")
            return {"products": [], "total": 0}

    @classmethod
    def _sku_display_name(cls, sku: dict) -> str:
        """从 SKU 的 spec 列表拼出规格名称（如 颜色:红 | 功率:48W）。"""
        specs = sku.get("spec") or sku.get("specs") or []
        if not isinstance(specs, list):
            return ""
        parts: list[str] = []
        for spec_item in specs:
            if not isinstance(spec_item, dict):
                continue
            parent_name = cls._pick(spec_item, "parent_name", "parentName", default="") or ""
            spec_name = cls._pick(spec_item, "spec_name", "specName", default="") or ""
            if parent_name and spec_name:
                parts.append(f"{parent_name}: {spec_name}")
            elif spec_name:
                parts.append(str(spec_name))
        return " | ".join(parts)

    def _parse_sku_entries(self, skus: list) -> list:
        """
        解析每个 SKU 的名称、库存、价格（单位：价格字段为分，输出含 price 元字符串）。
        """
        rows: list = []
        if not isinstance(skus, list):
            return rows
        for sku in skus:
            if not isinstance(sku, dict):
                continue
            sku_name = self._sku_display_name(sku) or "默认规格"
            sku_id = self._pick(sku, "sku_id", "skuId", "id")
            qty = self._pick(
                sku,
                "quantity",
                "stock",
                "sku_quantity",
                "skuQuantity",
                "goods_quantity",
                "goodsQuantity",
            )
            price_fen = self._pick(
                sku,
                "group_price",
                "groupPrice",
                "multi_price",
                "multiPrice",
                "price",
                "normal_price",
                "normalPrice",
                "sku_price",
                "skuPrice",
                "activity_group_price",
                "activityGroupPrice",
            )
            price_yuan = None
            if price_fen is not None:
                try:
                    price_yuan = round(float(price_fen) / 100.0, 2)
                except (TypeError, ValueError):
                    price_yuan = None
            rows.append(
                {
                    "sku_id": sku_id,
                    "sku_name": sku_name,
                    "quantity": qty,
                    "price_fen": int(price_fen) if price_fen is not None else None,
                    "price": price_yuan,
                }
            )
        return rows

    def _parse_product_detail(self, response_data):
        """
        解析商品详情响应数据

        Args:
            response_data (dict): API响应数据

        Returns:
            dict: 解析后的商品详情
        """
        try:
            result_data = response_data.get('result', {})

            skus = result_data.get('skus', []) or []
            sku_list = self._parse_sku_entries(skus)

            # 兼容旧字段：规格文案列表
            specifications = [s["sku_name"] for s in sku_list if s.get("sku_name")]

            # 提取分类信息作为规格补充
            cats = result_data.get('cats', [])
            if cats and isinstance(cats, list):
                # 过滤掉空值并组合分类信息
                valid_cats = [cat for cat in cats if cat]
                if valid_cats:
                    specifications.append(f"商品分类: {' > '.join(valid_cats)}")

            gid = self._pick(result_data, "goods_id", "goodsId")
            gname = self._pick(result_data, "goods_name", "goodsName") or ""
            thumb = (
                self._pick(result_data, "thumb_url", "thumbUrl", default="")
                or self._pick(result_data, "hd_thumb_url", "hdThumbUrl", default="")
                or ""
            )
            hd_thumb = self._pick(result_data, "hd_thumb_url", "hdThumbUrl", default="") or ""
            desc = (
                self._pick(result_data, "goods_desc", "goodsDesc", "description", "detail", default="")
                or ""
            )
            brief = self._pick(result_data, "brief", "share_desc", "shareDesc", "sub_title", "subTitle", default="") or ""
            qty = self._pick(result_data, "quantity", "goods_quantity", "goodsQuantity", "stock")
            min_fen = self._pick(
                result_data,
                "min_on_sale_group_price",
                "minOnSaleGroupPrice",
                "min_group_price",
                "minGroupPrice",
            )
            max_fen = self._pick(
                result_data,
                "max_on_sale_group_price",
                "maxOnSaleGroupPrice",
                "max_group_price",
                "maxGroupPrice",
            )

            product_info = {
                "goods_id": gid,
                "goods_name": gname,
                "thumb_url": thumb,
                "hd_thumb_url": hd_thumb,
                "specifications": specifications[:50],
                "sku_list": sku_list[:50],
                "description": desc if isinstance(desc, str) else "",
                "brief": brief if isinstance(brief, str) else "",
                "quantity": int(qty) if isinstance(qty, (int, float)) and qty == int(qty) else qty,
                "sku_count": len(sku_list),
                "price_min_fen": int(min_fen) if min_fen is not None else None,
                "price_max_fen": int(max_fen) if max_fen is not None else None,
            }

            img_groups = collect_product_images(
                product_info, raw_api_result=result_data
            )
            product_info["main_image_urls"] = img_groups.get("main_images") or []
            product_info["detail_image_urls"] = img_groups.get("detail_images") or []
            product_info["image_urls"] = img_groups.get("all_images") or []

            return product_info

        except Exception as e:
            self.logger.error(f"解析商品详情失败: {str(e)}")
            return {
                "goods_id": None,
                "goods_name": "解析失败",
                "specifications": []
            }