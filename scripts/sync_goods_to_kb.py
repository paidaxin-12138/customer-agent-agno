#!/usr/bin/env python3
"""
商品同步到知识库脚本（含 OCR 图片文字识别）
定时或手动将店铺商品同步到知识库，让 AI 可以检索回答

用法:
    python -m scripts.sync_goods_to_kb
    python -m scripts.sync_goods_to_kb --shop-id=xxx --user-id=xxx
    python -m scripts.sync_goods_to_kb --with-ocr  # 启用 OCR 识别图片文字
"""

import asyncio
import argparse
import sys
from typing import Optional, List, Dict, Any
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger_loguru import get_logger
from database.db_manager import db_manager
from Channel.pinduoduo.utils.API.product_manager import ProductManager
from Agent.CustomerAgent.agent_knowledge import NailLampKnowledgeManager
from config import get_config
from scripts.ocr_utils import ocr_product_images

logger = get_logger("GoodsSync")

# OCR 引擎（延迟导入）
_ocr_engine = None


def get_ocr_engine():
    """获取 OCR 引擎（单例）"""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from paddleocr import PaddleOCR
            _ocr_engine = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False)
            logger.info("PaddleOCR 初始化成功")
        except Exception as e:
            logger.error(f"PaddleOCR 初始化失败：{e}，请运行：pip install paddlepaddle paddleocr")
            raise
    return _ocr_engine


def validate_pinduoduo_account(shop_id: str, user_id: str) -> Optional[str]:
    """校验店铺已在本地登录；未登录则返回错误说明。"""
    acc = db_manager.get_account("pinduoduo", str(shop_id), str(user_id))
    if not acc:
        return (
            f"未找到已登录的拼多多账号（店铺 {shop_id} / 用户 {user_id}）。"
            "请先在「用户管理」完成商家后台登录后再同步商品。"
        )
    return None


class GoodsKnowledgeSyncer:
    """商品知识库同步器"""

    def __init__(self, shop_id: str, user_id: str, use_ocr: bool = False):
        self.shop_id = str(shop_id)
        self.user_id = str(user_id)
        cookies = get_config("pinduoduo.cookies", {})
        self.product_manager = ProductManager(
            shop_id=self.shop_id, user_id=self.user_id, cookies=cookies
        )
        self.knowledge_manager = NailLampKnowledgeManager()
        self.synced_count = 0
        self.failed_count = 0
        self.use_ocr = use_ocr
        self.ocr_engine = get_ocr_engine() if use_ocr else None

    async def sync_all_products(self) -> Dict[str, Any]:
        """同步所有商品到本店子知识库。"""
        logger.info(
            f"开始同步商品到知识库：shop_id={self.shop_id}, user_id={self.user_id}"
        )

        login_err = validate_pinduoduo_account(self.shop_id, self.user_id)
        if login_err:
            logger.error(login_err)
            return {
                "success": False,
                "error": login_err,
                "synced_count": 0,
                "failed_count": 0,
            }

        try:
            removed = self.knowledge_manager.delete_goods_sync_documents(self.shop_id)
            if removed:
                logger.info(f"已清理本店旧商品知识 {removed} 条")

            page = 1
            page_size = 50
            total_synced = 0
            total_api = 0
            last_error = ""
            api_ok = False

            while True:
                logger.info(f"正在获取第 {page} 页商品...")

                result = await asyncio.to_thread(
                    self.product_manager.get_product_list,
                    page=page,
                    size=page_size,
                )

                if not result or not isinstance(result, dict):
                    last_error = "获取商品列表失败（接口无响应）"
                    logger.error(last_error)
                    if page == 1:
                        return self._failure(last_error)
                    break

                if not result.get("success"):
                    last_error = (
                        result.get("error_msg")
                        or result.get("errorMsg")
                        or "获取商品列表失败"
                    )
                    logger.error(f"获取商品列表失败: {last_error}")
                    if page == 1:
                        return self._failure(str(last_error))
                    break

                api_ok = True
                product_list = result.get("products") or result.get("product_list") or []
                total_api = int(result.get("total") or 0)

                if not product_list:
                    if page == 1:
                        logger.info("店铺当前无在售商品")
                    else:
                        logger.info("没有更多商品")
                    break

                logger.info(f"获取到 {len(product_list)} 个商品，接口总计 {total_api} 个")

                for product in product_list:
                    try:
                        await self._sync_single_product(product)
                        total_synced += 1
                    except Exception as e:
                        logger.error(
                            f"同步商品失败 {product.get('goods_id')}: {e}"
                        )
                        self.failed_count += 1

                if len(product_list) < page_size:
                    break

                page += 1
                await asyncio.sleep(1)

            if not api_ok:
                return self._failure(last_error or "未能从拼多多获取商品列表")

            logger.info(
                f"商品同步完成：成功 {total_synced} 个，失败 {self.failed_count} 个"
            )

            if total_synced == 0:
                return {
                    "success": False,
                    "error": "未同步任何商品（店铺可能暂无在售商品，或全部写入失败）",
                    "synced_count": 0,
                    "failed_count": self.failed_count,
                    "total": total_api,
                    "empty_catalog": total_api == 0,
                }

            return {
                "success": True,
                "synced_count": total_synced,
                "failed_count": self.failed_count,
                "total": total_api,
            }

        except Exception as e:
            logger.error(f"同步过程中出错：{e}")
            return self._failure(str(e))

    def _failure(self, error: str) -> Dict[str, Any]:
        return {
            "success": False,
            "error": error,
            "synced_count": self.synced_count,
            "failed_count": self.failed_count,
        }

    async def _sync_single_product(self, product: Dict[str, Any]) -> None:
        goods_id = product.get("goods_id")
        goods_name = product.get("goods_name", "未知商品")

        if not goods_id:
            logger.warning("商品 ID 为空，跳过")
            return

        logger.debug(f"正在同步商品：{goods_id} - {goods_name}")

        try:
            detail = await asyncio.to_thread(
                self.product_manager.get_product_detail,
                goods_id,
            )
        except Exception as e:
            logger.warning(f"获取商品详情失败 {goods_id}: {e}")
            detail = {}

        detail_info = self._normalize_product_detail(detail)

        content = self._build_product_document(product, detail_info)
        title = f"商品-{goods_id}-{goods_name[:50]}"

        ok = await asyncio.to_thread(
            self.knowledge_manager.upsert_goods_sync_document,
            platform_shop_id=self.shop_id,
            goods_id=str(goods_id),
            title=title,
            content=content,
        )

        if ok:
            self.synced_count += 1
            logger.debug(f"商品 {goods_id} 同步成功")
        else:
            self.failed_count += 1
            logger.error(f"商品 {goods_id} 同步失败")

    @staticmethod
    def _normalize_product_detail(raw: Any) -> Dict[str, Any]:
        """将 get_product_detail 返回值统一为 product_info 字典。"""
        if not isinstance(raw, dict):
            return {}
        if raw.get("success") is True and isinstance(raw.get("product_info"), dict):
            return raw["product_info"]
        if isinstance(raw.get("product_info"), dict):
            return raw["product_info"]
        if raw.get("success") is False:
            return {}
        return raw

    def _build_product_document(
        self, product: Dict[str, Any], detail: Dict[str, Any]
    ) -> str:
        goods_id = product.get("goods_id", "未知 ID")
        goods_name = product.get("goods_name", "未知商品")
        price = product.get("price", "0")
        min_group_price = product.get("min_group_price", price)
        sales_tip = product.get("sales_tip", "")
        stock = product.get("stock", 0)

        lines = [
            f"# {goods_name}",
            "",
            f"**商品 ID**: {goods_id}",
        ]

        price_min_fen = detail.get("price_min_fen")
        price_max_fen = detail.get("price_max_fen")
        if price_min_fen is not None and price_max_fen is not None:
            lo = float(price_min_fen) / 100.0
            hi = float(price_max_fen) / 100.0
            if lo == hi:
                lines.append(f"**拼单价**: ¥{lo:.2f}")
            else:
                lines.append(f"**拼单价区间**: ¥{lo:.2f} - ¥{hi:.2f}")
        elif price:
            try:
                lines.append(f"**价格**: ¥{float(price)/100:.2f}")
            except (TypeError, ValueError):
                lines.append(f"**价格**: {price}")

        if sales_tip:
            lines.append(f"**销量**: {sales_tip}")
        goods_qty = detail.get("quantity")
        if goods_qty is not None and goods_qty != "":
            lines.append(f"**商品总库存**: {goods_qty}件")
        elif stock:
            lines.append(f"**库存**: {stock}件")

        lines.extend(["", "## SKU 规格（名称 / 价格 / 库存）", ""])

        sku_list = detail.get("sku_list") or []
        if sku_list:
            for sku in sku_list:
                name = sku.get("sku_name") or "默认规格"
                sid = sku.get("sku_id")
                qty = sku.get("quantity")
                price_yuan = sku.get("price")
                row = f"- **{name}**"
                if price_yuan is not None:
                    row += f" | 价格: ¥{price_yuan}"
                if qty is not None and qty != "":
                    row += f" | 库存: {qty}件"
                if sid is not None:
                    row += f" | SKU ID: {sid}"
                lines.append(row)
        else:
            specs = detail.get("specifications") or product.get("specs", [])
            if specs and isinstance(specs[0], str):
                for s in specs:
                    lines.append(f"- {s}")
            elif specs:
                for spec in specs:
                    if not isinstance(spec, dict):
                        continue
                    spec_name = spec.get("spec_name", "")
                    spec_value = spec.get("spec_value", "")
                    if spec_name and spec_value:
                        lines.append(f"- **{spec_name}**: {spec_value}")
            else:
                lines.append("暂无 SKU 规格信息")

        lines.extend(["", "## 商品详情", ""])

        description = detail.get("description", "") or product.get("description", "")
        if description:
            import re
            clean_desc = re.sub(r"<[^>]+>", "", description)
            lines.append(clean_desc[:2000])
        else:
            lines.append("暂无详情描述")

        image_urls = detail.get("image_urls", []) or product.get("image_urls", [])
        if image_urls and self.use_ocr:
            try:
                logger.info(f"正在 OCR 识别 {len(image_urls)} 张图片...")
                ocr_text = ocr_product_images(image_urls)
                if ocr_text and "暂无" not in ocr_text:
                    lines.extend(["", ocr_text])
            except Exception as e:
                logger.warning(f"OCR 识别失败：{e}")

        lines.extend(["", "---", f"*最后更新*: {self._get_current_date()}*"])
        return "\n".join(lines)

    def _get_current_date(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def main():
    parser = argparse.ArgumentParser(description="商品同步到知识库")
    parser.add_argument("--shop-id", type=str, help="店铺 ID")
    parser.add_argument("--user-id", type=str, help="用户 ID")
    parser.add_argument("--all", action="store_true", help="同步所有已登录店铺")
    parser.add_argument("--with-ocr", action="store_true", help="启用 OCR 识别商品图片文字")
    args = parser.parse_args()

    if args.all:
        accounts = db_manager.list_all_accounts_for_chat()
        if not accounts:
            logger.error("没有已登录的店铺账号")
            sys.exit(1)
        failed = 0
        for acc in accounts:
            if acc.get("channel_name") != "pinduoduo":
                continue
            shop_id = str(acc.get("platform_shop_id", ""))
            user_id = str(acc.get("seller_user_id", ""))
            if not shop_id or not user_id:
                continue
            logger.info(f"开始同步店铺：{shop_id}")
            syncer = GoodsKnowledgeSyncer(shop_id, user_id, use_ocr=args.with_ocr)
            result = await syncer.sync_all_products()
            if not result.get("success"):
                failed += 1
                logger.error(f"店铺 {shop_id} 同步失败：{result.get('error')}")
        sys.exit(1 if failed else 0)
    else:
        if args.shop_id and args.user_id:
            shop_id, user_id = args.shop_id, args.user_id
        else:
            shop_id = get_config("pinduoduo.shop_id", "")
            user_id = get_config("pinduoduo.user_id", "")
            if not shop_id or not user_id:
                logger.error("请提供 shop-id 和 user-id，或在配置文件中设置")
                sys.exit(1)

        syncer = GoodsKnowledgeSyncer(shop_id, user_id, use_ocr=args.with_ocr)
        result = await syncer.sync_all_products()

        if result.get("success"):
            logger.info(f"同步完成：成功 {result['synced_count']} 个商品")
            sys.exit(0)
        logger.error(f"同步失败：{result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
