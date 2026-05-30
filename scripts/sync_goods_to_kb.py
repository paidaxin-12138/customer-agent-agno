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
import json
import sys
from typing import Optional, List, Dict, Any, Callable
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger_loguru import get_logger
from database.db_manager import db_manager
from Channel.pinduoduo.utils.API.product_manager import ProductManager
from Agent.CustomerAgent.agent_knowledge import NailLampKnowledgeManager
from config import get_config
from scripts.ocr_utils import OcrRunConfig, build_product_ocr_knowledge_section

logger = get_logger("GoodsSync")

_SESSION_EXPIRED_HINT = (
    "拼多多商家后台登录已过期。请先在「用户管理」对该店铺重新登录"
    "（或确认自动回复已连接成功）后，再点「同步商品」。"
)


def resolve_sync_shop_credentials() -> tuple[str, str]:
    """
    解析同步用的 shop_id / user_id。
    优先 config.json，否则取数据库中第一个拼多多账号。
    """
    shop_id = str(get_config("pinduoduo.shop_id", "") or "").strip()
    user_id = str(get_config("pinduoduo.user_id", "") or "").strip()
    if shop_id and user_id:
        return shop_id, user_id

    for acc in db_manager.list_all_accounts_for_chat():
        if acc.get("channel_name") != "pinduoduo":
            continue
        ps = str(acc.get("platform_shop_id") or "").strip()
        su = str(acc.get("seller_user_id") or "").strip()
        if ps and su:
            return ps, su
    return shop_id, user_id


def _normalize_sync_error_message(error: str) -> str:
    msg = (error or "").strip()
    if "会话已过期" in msg or "43001" in msg:
        return _SESSION_EXPIRED_HINT
    lower = msg.lower()
    if "bad params" in lower or "bad param" in lower:
        return (
            "商品列表接口暂时不可用（可能为接口限流或登录态异常）。"
            "请在「用户管理」点「验证」后稍后再试「同步商品」。"
        )
    if "缺少客服 uid" in msg:
        return (
            "未找到客服账号 ID。请在「用户管理」完成验证，"
            "并确认账号 ID（如 pdd57041465173）已写入数据库。"
        )
    return msg or "同步失败"

_PROGRESS_MARKER = "@@GOODS_SYNC_PROGRESS@@"
_emit_progress_stdout = False


def _emit_progress_event(payload: Dict[str, Any]) -> None:
    if not _emit_progress_stdout:
        return
    try:
        print(
            f"{_PROGRESS_MARKER}{json.dumps(payload, ensure_ascii=False)}",
            flush=True,
        )
    except Exception:
        pass


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

    def __init__(
        self,
        shop_id: str,
        user_id: str,
        use_ocr: Optional[bool] = None,
        *,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ):
        self.shop_id = str(shop_id)
        self.user_id = str(user_id)
        # 仅从数据库读取该账号最新 Cookie（勿用 config 里可能过期的 pinduoduo.cookies）
        self.product_manager = ProductManager(
            shop_id=self.shop_id,
            user_id=self.user_id,
        )
        self.knowledge_manager = NailLampKnowledgeManager()
        self.synced_count = 0
        self.failed_count = 0
        self.use_ocr = use_ocr
        self._ocr_cfg = self._build_ocr_config()
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check
        self._pending_rows: List[Dict[str, Any]] = []
        self._total_planned = 0

    def _is_cancelled(self) -> bool:
        try:
            return bool(self._cancel_check and self._cancel_check())
        except Exception:
            return False

    def _report_progress(self, message: str, current: int = 0, total: int = 0) -> None:
        _emit_progress_event({"msg": message, "cur": current, "total": total})
        if not self._progress_callback:
            return
        try:
            self._progress_callback(message, current, total)
        except Exception:
            pass

    def _build_ocr_config(self) -> OcrRunConfig:
        cfg = OcrRunConfig.from_config()
        if self.use_ocr is not None:
            cfg.enabled = bool(self.use_ocr)
        return cfg

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
            self._report_progress("正在清理旧商品知识…", 0, 0)
            removed = await asyncio.to_thread(
                self.knowledge_manager.delete_goods_sync_documents,
                self.shop_id,
            )
            if removed:
                logger.info(f"已清理本店旧商品知识 {removed} 条")

            if self._ocr_cfg.enabled:
                await asyncio.to_thread(self._warmup_ocr_engine)

            page = 1
            page_size = 50
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
                if total_api > 0:
                    self._total_planned = max(self._total_planned, total_api)

                for product in product_list:
                    if self._is_cancelled():
                        logger.info("用户取消商品同步")
                        break
                    try:
                        await self._sync_single_product(product)
                    except Exception as e:
                        logger.error(
                            f"同步商品失败 {product.get('goods_id')}: {e}"
                        )
                        self.failed_count += 1
                    await asyncio.sleep(0)

                if self._is_cancelled():
                    break

                if len(product_list) < page_size:
                    break

                page += 1
                await asyncio.sleep(0.3)

            if not api_ok:
                return self._failure(last_error or "未能从拼多多获取商品列表")

            flushed = await asyncio.to_thread(self._flush_pending_rows)
            if flushed:
                logger.info(f"批量写入知识库 {flushed} 条")

            if self._is_cancelled():
                return {
                    "success": flushed > 0,
                    "synced_count": self.synced_count,
                    "failed_count": self.failed_count,
                    "total": total_api,
                    "cancelled": True,
                }

            logger.info(
                f"商品同步完成：成功 {self.synced_count} 个，失败 {self.failed_count} 个"
            )

            if self.synced_count == 0:
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
                "synced_count": self.synced_count,
                "failed_count": self.failed_count,
                "total": total_api,
            }

        except Exception as e:
            logger.error(f"同步过程中出错：{e}")
            return self._failure(str(e))

    def _failure(self, error: str) -> Dict[str, Any]:
        return {
            "success": False,
            "error": _normalize_sync_error_message(error),
            "synced_count": self.synced_count,
            "failed_count": self.failed_count,
        }

    @staticmethod
    def _warmup_ocr_engine() -> None:
        try:
            from scripts.ocr_utils import get_ocr_engine, limit_ocr_cpu_usage

            limit_ocr_cpu_usage()
            get_ocr_engine()
        except Exception as e:
            logger.warning(f"OCR 预热失败（将跳过或延后 OCR）: {e}")

    def _flush_pending_rows(self) -> int:
        if not self._pending_rows:
            return 0
        self._report_progress("正在写入知识库与向量索引…", self.synced_count, self._total_planned)
        count = self.knowledge_manager.bulk_upsert_goods_sync_documents(self._pending_rows)
        self._pending_rows.clear()
        return count

    async def _sync_single_product(self, product: Dict[str, Any]) -> None:
        goods_id = product.get("goods_id")
        goods_name = product.get("goods_name", "未知商品")

        if not goods_id:
            logger.warning("商品 ID 为空，跳过")
            return

        cur = self.synced_count + self.failed_count + 1
        total = self._total_planned or cur
        self._report_progress(
            f"正在处理 ({cur}/{total})：{str(goods_name)[:28]}…",
            cur,
            total,
        )

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
        raw_result = detail.get("api_result") if isinstance(detail, dict) else None

        # OCR + 拼文档在独立线程执行，避免阻塞 asyncio/Qt 事件循环
        content = await asyncio.to_thread(
            self._build_product_document,
            product,
            detail_info,
            raw_result,
        )
        title = f"商品-{goods_id}-{goods_name[:50]}"

        row = await asyncio.to_thread(
            self.knowledge_manager._build_goods_sync_row,
            platform_shop_id=self.shop_id,
            goods_id=str(goods_id),
            title=title,
            content=content,
        )

        if row:
            self._pending_rows.append(row)
            self.synced_count += 1
            logger.debug(f"商品 {goods_id} 已准备写入")
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

    @staticmethod
    def _format_list_price(price: Any) -> str:
        """列表接口 price 可能为分(int)、元(float)或区间字符串。"""
        if price is None or price == "":
            return ""
        if isinstance(price, str):
            s = price.strip()
            if "-" in s or "～" in s or "~" in s:
                return s if "¥" in s else f"¥{s}"
            try:
                v = float(s)
                return f"¥{v/100:.2f}" if v > 1000 else f"¥{v:.2f}"
            except ValueError:
                return s
        try:
            v = float(price)
            return f"¥{v/100:.2f}" if v > 1000 else f"¥{v:.2f}"
        except (TypeError, ValueError):
            return str(price)

    def _build_authoritative_commerce_section(
        self,
        product: Dict[str, Any],
        detail: Dict[str, Any],
    ) -> List[str]:
        """接口价格/SKU/库存 — 知识库与客服报价的权威来源。"""
        price = product.get("price", "")
        sales_tip = product.get("sales_tip", "")
        stock = product.get("stock", 0)

        lines = [
            "## 在售价格与库存（拼多多接口，客服报价以此为准）",
            "",
            "> 本节来自商家后台接口，**优先于**详情图 OCR 与图文摘要；回答价格/库存问题时只引用本节。",
            "",
        ]

        price_min_fen = detail.get("price_min_fen")
        price_max_fen = detail.get("price_max_fen")
        if price_min_fen is not None and price_max_fen is not None:
            lo = float(price_min_fen) / 100.0
            hi = float(price_max_fen) / 100.0
            if lo == hi:
                lines.append(f"- **拼单价**: ¥{lo:.2f}")
            else:
                lines.append(f"- **拼单价区间**: ¥{lo:.2f} - ¥{hi:.2f}")
        elif price:
            formatted = self._format_list_price(price)
            if formatted:
                lines.append(f"- **价格**: {formatted}")

        if sales_tip:
            lines.append(f"- **销量**: {sales_tip}")
        goods_qty = detail.get("quantity")
        if goods_qty is not None and goods_qty != "":
            lines.append(f"- **商品总库存**: {goods_qty}件")
        elif stock:
            lines.append(f"- **库存**: {stock}件")

        lines.extend(["", "### SKU 规格（接口：名称 / 价格 / 库存）", ""])
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
                lines.append("- 暂无 SKU 规格信息")
        lines.append("")
        return lines

    def _build_product_document(
        self,
        product: Dict[str, Any],
        detail: Dict[str, Any],
        raw_api_result: Optional[Dict[str, Any]] = None,
    ) -> str:
        goods_id = product.get("goods_id", "未知 ID")
        goods_name = product.get("goods_name", "未知商品")

        lines = [
            f"# {goods_name}",
            "",
            f"**商品 ID**: {goods_id}",
            "",
        ]
        lines.extend(self._build_authoritative_commerce_section(product, detail))

        lines.extend(["## 商品详情（文字）", ""])

        description = detail.get("description", "") or product.get("description", "")
        if description:
            import re
            clean_desc = re.sub(r"<[^>]+>", "", description)
            lines.append(clean_desc[:2000])
        else:
            lines.append("暂无详情描述")

        if self._ocr_cfg.enabled:
            sku_hints = [
                str(s.get("sku_name") or "")
                for s in (detail.get("sku_list") or [])
                if s.get("sku_name")
            ]
            try:
                n_img = len(detail.get("image_urls") or []) + len(
                    detail.get("detail_image_urls") or []
                )
                if n_img:
                    logger.info(f"商品 {goods_id}：OCR 识别约 {n_img} 张图...")
                api_note = "\n".join(
                    self._build_authoritative_commerce_section(product, detail)
                )
                ocr_block = build_product_ocr_knowledge_section(
                    detail,
                    product,
                    raw_api_result=raw_api_result,
                    cfg=self._ocr_cfg,
                    goods_name=str(goods_name),
                    goods_id=str(goods_id),
                    sku_hints=sku_hints,
                    api_commerce_note=api_note,
                )
                if ocr_block.strip():
                    lines.append(ocr_block)
            except Exception as e:
                logger.warning(f"商品 {goods_id} OCR 失败：{e}")

        lines.extend(["", "---", f"*最后更新*: {self._get_current_date()}*"])
        return "\n".join(lines)

    def _get_current_date(self) -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def _run_single_shop(
    shop_id: str,
    user_id: str,
    use_ocr: Optional[bool],
    *,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> Dict[str, Any]:
    syncer = GoodsKnowledgeSyncer(
        shop_id,
        user_id,
        use_ocr=use_ocr,
        progress_callback=progress_callback,
        cancel_check=cancel_check,
    )
    return await syncer.sync_all_products()


async def main():
    global _emit_progress_stdout

    parser = argparse.ArgumentParser(description="商品同步到知识库")
    parser.add_argument("--shop-id", type=str, help="店铺 ID")
    parser.add_argument("--user-id", type=str, help="用户 ID")
    parser.add_argument("--all", action="store_true", help="同步所有已登录店铺")
    parser.add_argument(
        "--emit-progress",
        action="store_true",
        help="向 stdout 输出 @@GOODS_SYNC_PROGRESS@@ 行供 UI 子进程解析",
    )
    parser.add_argument(
        "--with-ocr",
        action="store_true",
        help="启用 OCR（识别主图/详情图并整理参数写入知识库）",
    )
    parser.add_argument(
        "--no-ocr",
        action="store_true",
        help="本次同步禁用 OCR（忽略配置中的 goods_sync_ocr_enabled）",
    )
    args = parser.parse_args()
    _emit_progress_stdout = bool(args.emit_progress)

    use_ocr: Optional[bool] = None
    if args.with_ocr:
        use_ocr = True
    elif args.no_ocr:
        use_ocr = False

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
            syncer = GoodsKnowledgeSyncer(shop_id, user_id, use_ocr=use_ocr)
            result = await syncer.sync_all_products()
            if not result.get("success"):
                failed += 1
                logger.error(f"店铺 {shop_id} 同步失败：{result.get('error')}")
        sys.exit(1 if failed else 0)
    else:
        if args.shop_id and args.user_id:
            shop_id, user_id = args.shop_id, args.user_id
        else:
            shop_id, user_id = resolve_sync_shop_credentials()
            if not shop_id or not user_id:
                logger.error(
                    "请提供 shop-id 和 user-id，或在用户管理验证拼多多账号，"
                    "或在 config.json 设置 pinduoduo.shop_id / user_id"
                )
                sys.exit(1)

        result = await _run_single_shop(shop_id, user_id, use_ocr)
        _emit_progress_event({"done": True, **result})

        if result.get("success"):
            logger.info(f"同步完成：成功 {result['synced_count']} 个商品")
            sys.exit(0)
        logger.error(f"同步失败：{result.get('error')}")
        sys.exit(1)


if __name__ == "__main__":
    # 子进程未走 app.py，须初始化 DI，否则 BaseRequest 读不到库内 Cookie
    from config import config as _app_config
    from core.di_container import configure_standard_services

    configure_standard_services(_app_config)
    asyncio.run(main())
