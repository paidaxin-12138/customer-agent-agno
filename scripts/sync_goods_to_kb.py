# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
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
from Agent.CustomerAgent.agent_knowledge import get_knowledge_manager
from config import get_config
from scripts.ocr_utils import OcrRunConfig, build_product_ocr_knowledge_section

logger = get_logger("GoodsSync")

# 拼多多 MMS goodsList 实际每页条数（常忽略请求里的 page_size）
MMS_GOODS_LIST_PAGE_SIZE = 10

_SESSION_EXPIRED_HINT = (
    "拼多多商家后台登录已过期。请先在「用户管理」对该店铺重新登录"
    "（或确认自动回复已连接成功）后，再点「同步商品」。"
)


def _should_fetch_next_goods_page(
    *,
    product_list: list,
    page_size: int,
    total_api: int,
    catalog_count: int,
) -> bool:
    """判断是否继续拉取下一页商品列表。

    拼多多 MMS goodsList 常忽略 page_size，每页只返回约 10 条；
    不能用 ``len(product_list) < page_size`` 作为结束条件。
    """
    if not product_list:
        return False
    if total_api > 0:
        return catalog_count < total_api
    # total 缺失时：MMS 末页通常少于 10 条；满页则继续翻页
    return len(product_list) >= MMS_GOODS_LIST_PAGE_SIZE


def list_pinduoduo_accounts_for_sync() -> List[Dict[str, Any]]:
    """用户管理中的拼多多账号列表（供同步商品选择）。"""
    out: List[Dict[str, Any]] = []
    for acc in db_manager.list_all_accounts_for_chat():
        if acc.get("channel_name") != "pinduoduo":
            continue
        shop_id = str(acc.get("platform_shop_id") or "").strip()
        user_id = str(acc.get("seller_user_id") or "").strip()
        if not shop_id or not user_id:
            continue
        out.append(
            {
                "id": acc.get("id"),
                "shop_id": shop_id,
                "user_id": user_id,
                "shop_name": str(acc.get("shop_name") or shop_id),
                "username": str(acc.get("username") or user_id),
            }
        )
    return out


def resolve_sync_shop_credentials() -> tuple[str, str]:
    """
    解析同步用的 shop_id / user_id。
    优先 config.json，否则取数据库中第一个拼多多账号。
    """
    shop_id = str(get_config("pinduoduo.shop_id", "") or "").strip()
    user_id = str(get_config("pinduoduo.user_id", "") or "").strip()
    if shop_id and user_id:
        return shop_id, user_id

    accounts = [
        acc
        for acc in db_manager.list_all_accounts_for_chat()
        if acc.get("channel_name") == "pinduoduo"
    ]
    if shop_id and not user_id:
        for acc in accounts:
            ps = str(acc.get("platform_shop_id") or "").strip()
            su = str(acc.get("seller_user_id") or "").strip()
            if ps == shop_id and su:
                return ps, su
    if user_id and not shop_id:
        for acc in accounts:
            ps = str(acc.get("platform_shop_id") or "").strip()
            su = str(acc.get("seller_user_id") or "").strip()
            if su == user_id and ps:
                return ps, su

    for acc in accounts:
        ps = str(acc.get("platform_shop_id") or "").strip()
        su = str(acc.get("seller_user_id") or "").strip()
        if ps and su:
            return ps, su
    return shop_id, user_id


def _normalize_sync_error_message(error: str) -> str:
    msg = (error or "").strip()
    if "会话已过期" in msg or "43001" in msg:
        return _SESSION_EXPIRED_HINT
    if "54001" in msg or "风控" in msg or "verifyAuth" in msg:
        return (
            "拼多多商品列表触发后台风控校验（提示「频繁」多为误导）。"
            "请在「用户管理」重新验证登录；仍失败时用浏览器打开 mms.pinduoduo.com "
            "「商品管理」完成一次验证后再同步。"
        )
    lower = msg.lower()
    if "bad params" in lower or "bad param" in lower:
        return (
            "商品列表接口暂时不可用（登录态或参数异常）。"
            "请在「用户管理」点「验证」后再试「同步商品」。"
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
        self.knowledge_manager = get_knowledge_manager()
        self.synced_count = 0
        self.failed_count = 0
        self.use_ocr = use_ocr
        self._ocr_cfg = self._build_ocr_config()
        self._progress_callback = progress_callback
        self._cancel_check = cancel_check
        self._total_planned = 0
        self._processing_seq = 0
        self._browser_session: Any = None
        self._skipped_existing = 0
        self._catalog_goods_ids: set[str] = set()
        self._existing_goods_ids: set[str] = set()
        self._catalog_fetch_complete = False

    def _is_cancelled(self) -> bool:
        try:
            return bool(self._cancel_check and self._cancel_check())
        except Exception:
            return False

    def _report_progress(
        self,
        message: str,
        current: int = 0,
        total: int = 0,
        **extra: Any,
    ) -> None:
        payload = {"msg": message, "cur": current, "total": total, **extra}
        _emit_progress_event(payload)
        if not self._progress_callback:
            return
        try:
            self._progress_callback(message, current, total)
        except Exception:
            pass

    async def _progress_wait_ticker(
        self,
        message_prefix: str,
        *,
        interval_sec: float = 5.0,
    ) -> None:
        """长耗时等待时定期上报已等待秒数。"""
        waited = 0.0
        try:
            while True:
                await asyncio.sleep(interval_sec)
                waited += interval_sec
                self._report_progress(
                    f"{message_prefix}（已等待 {int(waited)} 秒）…",
                    self.synced_count,
                    self._total_planned or 0,
                )
        except asyncio.CancelledError:
            pass

    async def _fetch_product_list_page(
        self, page: int, page_size: int
    ) -> Dict[str, Any]:
        if self._browser_session is not None:
            raw = await self._browser_session.fetch_goods_list_raw(page, page_size)
            if raw.get("success") is True:
                parsed = self.product_manager._parse_mall_goods_list(raw)
                return {
                    "success": True,
                    "products": parsed.get("products", []),
                    "total": int(parsed.get("total") or 0),
                    "page": page,
                    "source": "mall_goods_list",
                }
            from Channel.pinduoduo.utils.mms_goods_browser import (
                is_risk_blocked_response,
                normalize_risk_error_message,
            )

            error_msg = (
                raw.get("errorMsg") or raw.get("error_msg") or "获取商品列表失败"
            )
            if is_risk_blocked_response(raw):
                error_msg = normalize_risk_error_message(raw)
            return {
                "success": False,
                "error_msg": str(error_msg),
                "products": [],
                "total": 0,
                "page": page,
                "source": "mall_goods_list",
            }

        return await asyncio.to_thread(
            self.product_manager.get_product_list,
            page=page,
            size=page_size,
        )

    async def _fetch_product_detail(self, goods_id: Any) -> Dict[str, Any]:
        if self._browser_session is not None:
            try:
                result = await self._browser_session.fetch_product_detail_raw(goods_id)
            except Exception as e:
                logger.warning(f"浏览器拉取商品详情失败 {goods_id}: {e}")
                result = None
            if result and result.get("success") is True:
                product_info = self.product_manager._parse_product_detail(result)
                return {
                    "success": True,
                    "product_info": product_info,
                    "api_result": result,
                }
            if result:
                return {
                    "success": False,
                    "error_msg": result.get("errorMsg")
                    or result.get("error_msg")
                    or "获取商品详情失败",
                }
        return await asyncio.to_thread(
            self.product_manager.get_product_detail,
            goods_id,
        )

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

        browser_session = None
        try:
            self._existing_goods_ids = await asyncio.to_thread(
                self._load_existing_goods_ids_for_shop
            )
            if self._existing_goods_ids:
                logger.info(
                    f"本店已有 {len(self._existing_goods_ids)} 条商品知识，将跳过并续传"
                )
                self._report_progress(
                    f"检测到已有 {len(self._existing_goods_ids)} 个商品，将续传同步…",
                    0,
                    0,
                )

            if self._ocr_cfg.enabled:
                logger.info("商品同步 OCR：已开启")
                await asyncio.to_thread(self._warmup_ocr_engine)

            if bool(get_config("knowledge_base.goods_sync_use_browser", True)):
                browser_session = await self._open_browser_session()
                self._report_progress("浏览器已就绪，正在获取商品列表…", 0, 0)

            page = 1
            page_size = 50
            total_api = 0
            last_error = ""
            api_ok = False
            self._catalog_fetch_complete = False

            while True:
                logger.info(f"正在获取第 {page} 页商品...")
                self._report_progress(
                    f"正在拉取商品列表（第 {page} 页）…",
                    self.synced_count,
                    self._total_planned or 0,
                )
                ticker = asyncio.create_task(
                    self._progress_wait_ticker(f"正在拉取商品列表（第 {page} 页）")
                )
                try:
                    result = await self._fetch_product_list_page(page, page_size)
                finally:
                    ticker.cancel()
                    try:
                        await ticker
                    except asyncio.CancelledError:
                        pass

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
                if total_api > 0:
                    self._report_progress(
                        f"共 {total_api} 个在售商品，开始逐个同步…",
                        self.synced_count,
                        total_api,
                        list_ready=True,
                        total_planned=total_api,
                    )

                for product in product_list:
                    gid = str(product.get("goods_id") or "").strip()
                    if gid:
                        self._catalog_goods_ids.add(gid)
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

                if not _should_fetch_next_goods_page(
                    product_list=product_list,
                    page_size=page_size,
                    total_api=total_api,
                    catalog_count=len(self._catalog_goods_ids),
                ):
                    self._catalog_fetch_complete = True
                    break

                page += 1
                await asyncio.sleep(0.3)

            if not api_ok:
                return self._failure(last_error or "未能从拼多多获取商品列表")

            if self._catalog_goods_ids and self._catalog_fetch_complete:
                pruned = await asyncio.to_thread(
                    self._prune_stale_goods_sync,
                    self._catalog_goods_ids,
                )
                if pruned:
                    logger.info(f"已清理下架商品知识 {pruned} 条")

            if self._is_cancelled():
                done = self._completed_count()
                return {
                    "success": done > 0,
                    "synced_count": done,
                    "failed_count": self.failed_count,
                    "total": total_api,
                    "cancelled": True,
                }

            done = self._completed_count()
            logger.info(
                f"商品同步完成：完成 {done} 个（新写入 {self.synced_count}，跳过 {self._skipped_existing}），"
                f"失败 {self.failed_count} 个"
            )

            if done == 0:
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
                "synced_count": done,
                "failed_count": self.failed_count,
                "total": total_api,
            }

        except Exception as e:
            logger.error(f"同步过程中出错：{e}")
            return self._failure(str(e))
        finally:
            self._browser_session = None
            if browser_session is not None:
                try:
                    self.product_manager.detach_browser_session()
                    await browser_session.close()
                except Exception as close_err:
                    logger.debug(f"关闭商品浏览器会话: {close_err}")

    def _failure(self, error: str) -> Dict[str, Any]:
        return {
            "success": False,
            "error": _normalize_sync_error_message(error),
            "synced_count": self.synced_count,
            "failed_count": self.failed_count,
        }

    def _load_existing_goods_ids_for_shop(self) -> set[str]:
        ids: set[str] = set()
        sid = str(self.shop_id or "").strip()
        for doc in self.knowledge_manager.documents:
            if (doc.get("source") or "").strip() != "goods_sync":
                continue
            if str(doc.get("platform_shop_id") or "").strip() != sid:
                continue
            ik = str(doc.get("inherit_key") or "")
            if ik.startswith("goods:"):
                ids.add(ik.split(":", 1)[1].strip())
        return ids

    def _prune_stale_goods_sync(self, active_goods_ids: set[str]) -> int:
        """删除接口列表中已不存在的商品知识（下架清理）。"""
        sid = str(self.shop_id or "").strip()
        active = {str(g).strip() for g in active_goods_ids if str(g).strip()}
        remove_ids: List[str] = []
        kept: List[Dict[str, Any]] = []
        for doc in self.knowledge_manager.documents:
            if (doc.get("source") or "").strip() != "goods_sync":
                kept.append(doc)
                continue
            if str(doc.get("platform_shop_id") or "").strip() != sid:
                kept.append(doc)
                continue
            ik = str(doc.get("inherit_key") or "")
            gid = ik.split(":", 1)[1].strip() if ik.startswith("goods:") else ""
            if gid and gid not in active:
                remove_ids.append(str(doc.get("id") or ""))
            else:
                kept.append(doc)
        if not remove_ids:
            return 0
        self.knowledge_manager.documents = kept
        if self.knowledge_manager._knowledge_table:
            for doc_id in remove_ids:
                if not doc_id:
                    continue
                try:
                    self.knowledge_manager._knowledge_table.delete(f"id = '{doc_id}'")
                except Exception:
                    pass
        self.knowledge_manager._save_documents()
        return len(remove_ids)

    async def _open_browser_session(self) -> Any:
        from Channel.pinduoduo.utils.mms_goods_browser import MmsGoodsBrowserSession

        self._report_progress("正在启动浏览器（约 10 秒）…", 0, 0)
        browser_session = MmsGoodsBrowserSession.from_product_manager(
            self.product_manager
        )
        await browser_session.open()
        self._browser_session = browser_session
        self.product_manager.attach_browser_session(browser_session)
        logger.info("商品同步已启用 Playwright 浏览器会话")
        return browser_session

    def _browser_recycle_interval(self) -> int:
        """0 表示不回收；>0 表示每成功写入 N 个商品后做一次轻量页面重置。"""
        try:
            return max(0, int(get_config("knowledge_base.goods_sync_browser_recycle_every", 0) or 0))
        except (TypeError, ValueError):
            return 0

    async def _maybe_recycle_browser_session(self) -> None:
        """每成功写入若干商品后重置浏览器页面，降低长时间同步内存上涨。"""
        interval = self._browser_recycle_interval()
        if interval <= 0:
            return
        if self.synced_count <= 0 or self.synced_count % interval != 0:
            return
        if self._browser_session is None:
            return
        if not bool(get_config("knowledge_base.goods_sync_use_browser", True)):
            return

        done = self._completed_count()
        total = self._total_planned or 0
        hard_recycle = bool(get_config("knowledge_base.goods_sync_browser_hard_recycle", False))

        try:
            if hard_recycle:
                import gc

                logger.info("商品同步：完整重启浏览器会话（释放内存）")
                self._report_progress(
                    f"已写入 {self.synced_count} 个，正在重启浏览器…",
                    done,
                    total,
                )
                try:
                    self.product_manager.detach_browser_session()
                    await self._browser_session.close()
                except Exception as e:
                    logger.warning(f"关闭旧浏览器会话: {e}")
                self._browser_session = None
                gc.collect()
                await asyncio.sleep(2.0)
                await self._open_browser_session()
            else:
                logger.info("商品同步：轻量重置浏览器页面")
                self._report_progress(
                    f"已写入 {self.synced_count} 个，正在重置浏览器页面…",
                    done,
                    total,
                )
                await self._browser_session.soft_recycle()
        except Exception as e:
            logger.error(f"浏览器回收失败，将继续同步: {e}")

    def _completed_count(self) -> int:
        return self.synced_count + self._skipped_existing

    @staticmethod
    def _warmup_ocr_engine() -> None:
        try:
            from scripts.ocr_utils import get_ocr_engine, limit_ocr_cpu_usage

            limit_ocr_cpu_usage()
            get_ocr_engine()
        except Exception as e:
            logger.warning(f"OCR 预热失败（将跳过或延后 OCR）: {e}")

    async def _sync_single_product(self, product: Dict[str, Any]) -> None:
        goods_id = product.get("goods_id")
        goods_name = product.get("goods_name", "未知商品")

        if not goods_id:
            logger.warning("商品 ID 为空，跳过")
            return

        self._processing_seq += 1
        cur = self._processing_seq
        total = self._total_planned or cur
        short_name = str(goods_name)[:24]

        gid_str = str(goods_id).strip()
        if gid_str and gid_str in self._existing_goods_ids:
            self._skipped_existing += 1
            done = self._completed_count()
            logger.debug(f"商品 {goods_id} 已存在，跳过")
            self._report_progress(
                f"第 {cur}/{total} 个：已存在，跳过（{done}/{total}）",
                done,
                total,
                processing_index=cur,
            )
            return

        self._report_progress(
            f"正在同步第 {cur}/{total} 个：{short_name}…",
            self._completed_count(),
            total,
            processing_index=cur,
        )

        logger.debug(f"正在同步商品：{goods_id} - {goods_name}")

        try:
            self._report_progress(
                f"第 {cur}/{total} 个：拉取详情…",
                self._completed_count(),
                total,
                processing_index=cur,
            )
            detail = await self._fetch_product_detail(goods_id)
        except Exception as e:
            logger.warning(f"获取商品详情失败 {goods_id}: {e}")
            detail = {}

        detail_info = self._normalize_product_detail(detail)
        raw_result = detail.get("api_result") if isinstance(detail, dict) else None

        self._report_progress(
            f"第 {cur}/{total} 个：整理知识{'（含 OCR）' if self._ocr_cfg.enabled else ''}…",
            self._completed_count(),
            total,
            processing_index=cur,
        )
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
            self._report_progress(
                f"第 {cur}/{total} 个：写入知识库…",
                self._completed_count(),
                total,
                processing_index=cur,
            )
            ok = await asyncio.to_thread(
                self.knowledge_manager.upsert_goods_sync_row,
                row,
            )
            if ok:
                self.synced_count += 1
                self._existing_goods_ids.add(gid_str)
                done = self._completed_count()
                logger.info(f"商品 {goods_id} 已写入知识库 ({done}/{total})")
                self._report_progress(
                    f"已完成 {done}/{total}：{short_name}",
                    done,
                    total,
                    item_synced=True,
                    goods_id=str(goods_id),
                    title=title,
                    processing_index=cur,
                )
                await self._maybe_recycle_browser_session()
            else:
                self.failed_count += 1
                logger.error(f"商品 {goods_id} 写入知识库失败")
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
        accounts = list_pinduoduo_accounts_for_sync()
        if not accounts:
            err = "没有可用的拼多多账号，请先在「用户管理」添加并验证"
            _emit_progress_event({"done": True, "success": False, "error": err, "synced_count": 0})
            logger.error(err)
            sys.exit(1)
        total_synced = 0
        total_failed = 0
        shop_failures: List[str] = []
        n = len(accounts)
        for idx, acc in enumerate(accounts, start=1):
            shop_id = str(acc["shop_id"])
            user_id = str(acc["user_id"])
            shop_label = str(acc.get("shop_name") or shop_id)
            _emit_progress_event(
                {
                    "msg": f"正在同步店铺 ({idx}/{n})：{shop_label}…",
                    "cur": total_synced,
                    "total": 0,
                    "shop_index": idx,
                    "shop_total": n,
                }
            )
            logger.info(f"开始同步店铺 ({idx}/{n})：{shop_id}")
            result = await _run_single_shop(shop_id, user_id, use_ocr)
            synced = int(result.get("synced_count") or 0)
            total_synced += synced
            if not result.get("success"):
                total_failed += 1
                shop_failures.append(f"{shop_label}: {result.get('error') or '失败'}")
                logger.error(f"店铺 {shop_id} 同步失败：{result.get('error')}")
        overall_ok = total_synced > 0 and total_failed < n
        payload: Dict[str, Any] = {
            "done": True,
            "success": overall_ok,
            "synced_count": total_synced,
            "failed_count": total_failed,
            "shop_total": n,
        }
        if not overall_ok:
            payload["error"] = (
                "；".join(shop_failures[:3])
                if shop_failures
                else "全部店铺同步失败"
            )
        _emit_progress_event(payload)
        if overall_ok:
            logger.info(f"全部店铺同步完成：共 {total_synced} 个商品")
            sys.exit(0)
        logger.error(payload.get("error"))
        sys.exit(1)
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
