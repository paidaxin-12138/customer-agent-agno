from ..base_request import BaseRequest


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

    def get_product_list(self, page=1, size=10):
        """
        获取店铺商品列表

        Args:
            page (int): 页码，默认1
            size (int): 每页数量，默认10

        Returns:
            dict: 商品列表结果，格式如下：
                {
                    "success": True/False,
                    "products": [
                        {
                            "goods_id": int,
                            "goods_name": str,
                            "thumb_url": str,       # 商品缩略图
                            "price": float,         # 价格
                            "sold_quantity": int,   # 已售数量
                            "goods_type": int,      # 商品类型
                            "tag": str,             # 商品标签
                        },
                        ...
                    ],
                    "total": int,  # 总数量
                    "page": int,   # 当前页码
                    "error_msg": str  # 仅在失败时包含
                }
        """
        # 构建请求URL
        url = "https://mms.pinduoduo.com/latitude/goods/recommendGoods"

        # 构建请求数据
        data = {
            "uid": "",
            "pageNum": page,
            "pageSize": size
        }

        headers = self._mms_browser_headers("https://mms.pinduoduo.com/chat-merchant/index.html")
        headers["priority"] = "u=1, i"
        headers["sec-ch-ua"] = '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"'
        headers["sec-ch-ua-mobile"] = "?0"
        headers["sec-ch-ua-platform"] = '"Windows"'

        # 发起请求
        result = self.post(url, json_data=data, headers=headers)

        if result and result.get("success") == True:
            # 解析商品列表
            products_data = self._parse_product_list(result)
            return {
                "success": True,
                "products": products_data.get("products", []),
                "total": products_data.get("total", 0),
                "page": page
            }
        else:
            error_msg = (
                (result.get("errorMsg") or result.get("error_msg")) if result else None
            ) or "获取商品列表失败"
            self.logger.error(f"获取商品列表失败: {error_msg}")
            return {
                "success": False,
                "error_msg": error_msg,
                "products": [],
                "total": 0,
                "page": page
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
                "product_info": product_info
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
            # 新接口数据在 onSaleGoods 字段中
            goods_list = result_data.get('onSaleGoods', [])

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

            return product_info

        except Exception as e:
            self.logger.error(f"解析商品详情失败: {str(e)}")
            return {
                "goods_id": None,
                "goods_name": "解析失败",
                "specifications": []
            }