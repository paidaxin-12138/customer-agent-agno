#!/usr/bin/env python3
"""对 MMS 只读接口发请求，汇总实际可获取的全部字段与样例值。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _collect_keys(obj: Any, prefix: str = "", out: Optional[Set[str]] = None, depth: int = 0, max_depth: int = 6) -> Set[str]:
    if out is None:
        out = set()
    if depth > max_depth:
        out.add(f"{prefix}...")
        return out
    if isinstance(obj, dict):
        if not obj and prefix:
            out.add(prefix or "(empty dict)")
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            _collect_keys(v, p, out, depth + 1, max_depth)
    elif isinstance(obj, list):
        if not obj:
            out.add(f"{prefix}[]")
        else:
            _collect_keys(obj[0], f"{prefix}[0]", out, depth + 1, max_depth)
            if len(obj) > 1:
                out.add(f"{prefix}[...{len(obj)} items]")
    return out


def _sample_value(v: Any, max_len: int = 80) -> Any:
    if v is None or isinstance(v, (bool, int, float)):
        return v
    if isinstance(v, str):
        return v if len(v) <= max_len else v[: max_len - 3] + "..."
    if isinstance(v, dict):
        return {k: _sample_value(v[k], max_len) for k in list(v.keys())[:25]}
    if isinstance(v, list):
        if not v:
            return []
        s = [_sample_value(v[0], max_len)]
        if len(v) > 1:
            s.append(f"... +{len(v) - 1} more")
        return s
    return str(v)[:max_len]


def _probe(name: str, url: str, fn) -> Dict[str, Any]:
    row: Dict[str, Any] = {"name": name, "url": url, "ok": False}
    try:
        raw = fn()
        row["ok"] = raw is not None and raw is not False
        if isinstance(raw, tuple):
            row["data_type"] = "tuple"
            row["values"] = list(raw)
            row["field_paths"] = [f"[{i}]" for i in range(len(raw))]
        elif isinstance(raw, list):
            row["data_type"] = "list"
            row["count"] = len(raw)
            row["sample"] = _sample_value(raw)
            row["field_paths"] = sorted(_collect_keys(raw))
        elif isinstance(raw, dict):
            row["data_type"] = "dict"
            row["success"] = raw.get("success")
            err = raw.get("errorMsg") or raw.get("error_msg") or raw.get("error_code")
            if err:
                row["error"] = str(err)[:200]
            row["sample"] = _sample_value(raw)
            row["field_paths"] = sorted(_collect_keys(raw))
        else:
            row["data_type"] = type(raw).__name__
            row["value"] = _sample_value(raw)
        return row
    except Exception as e:
        row["error"] = str(e)[:300]
        return row


def main() -> int:
    from database.db_manager import db_manager
    from Channel.pinduoduo.utils.API.chat_orders import ChatOrdersAPI, _chat_mms_headers
    from Channel.pinduoduo.utils.API.get_shop_info import GetShopInfo
    from Channel.pinduoduo.utils.API.get_token import GetToken
    from Channel.pinduoduo.utils.API.get_user_info import GetUserInfo
    from Channel.pinduoduo.utils.API.product_manager import ProductManager
    from Channel.pinduoduo.utils.API.send_message import SendMessage
    from Channel.pinduoduo.utils.base_request import BaseRequest
    from config import config

    shop, user = "570414651", "184046586"
    acc = db_manager.get_account("pinduoduo", shop, user)
    if not acc or not acc.get("cookies"):
        print(json.dumps({"error": "无 Cookie"}, ensure_ascii=False))
        return 1

    cookies = acc["cookies"]
    buyer = "4216881609"

    probes: List[Dict[str, Any]] = []

    # 1 userinfo
    ui = GetUserInfo(cookies=cookies)
    probes.append(_probe(
        "当前登录客服",
        "POST /janus/api/new/userinfo",
        ui.get_user_info,
    ))

    # 2 shop - raw response
    gsi = GetShopInfo(cookies=cookies)
    probes.append(_probe(
        "店铺信息(完整JSON)",
        "POST /earth/api/merchant/queryMerchantInfoByMallId",
        lambda: gsi.post(
            "https://mms.pinduoduo.com/earth/api/merchant/queryMerchantInfoByMallId",
            json_data={},
            headers={"Referer": "https://mms.pinduoduo.com/home", "Origin": "https://mms.pinduoduo.com"},
        ),
    ))

    # 3 token
    gt = GetToken(shop, user)
    gt.update_cookies(cookies)
    probes.append(_probe(
        "WebSocket Token",
        "POST /chats/getToken",
        lambda: {"token_preview": (gt.get_token() or "")[:20] + "..." if gt.get_token() else None, "raw": gt.post("https://mms.pinduoduo.com/chats/getToken", data={"version": "3"})},
    ))

    # 4 assign cs
    sm = SendMessage(shop, user)
    sm.update_cookies(cookies)
    probes.append(_probe(
        "可转接客服列表",
        "POST /latitude/assign/getAssignCsList",
        sm.getAssignCsList,
    ))

    # 5 orders
    co = ChatOrdersAPI(shop, user)
    co.update_cookies(cookies)
    ok, orders = co.fetch_orders_by_buyer_uid(buyer, 10)
    probes.append(_probe(
        f"买家订单列表 uid={buyer}",
        "POST /latitude/order/userAllOrder",
        lambda: {"api_ok": ok, "orders": orders},
    ))

    order_sn = None
    goods_id = None
    if ok and orders:
        order_sn = orders[0].get("orderSn") or orders[0].get("order_sn")
        g = orders[0].get("orderGoodsList")
        if isinstance(g, dict):
            goods_id = g.get("goodsId") or g.get("goods_id")
        elif isinstance(g, list) and g:
            goods_id = g[0].get("goodsId") or g[0].get("goods_id")

    if order_sn:
        probes.append(_probe(
            f"售后收件信息 orderSn={order_sn}",
            "POST /latitude/afterSales/replenishment/getDetail",
            lambda: co.get_order_pickup_info(order_sn),
        ))

    # 6 product list mall
    pm = ProductManager(shop, user)
    pm.update_cookies(cookies)
    probes.append(_probe(
        "全店商品列表",
        "POST /vodka/v2/mms/query/display/mall/goodsList",
        lambda: pm._fetch_mall_goods_list(1, 5),
    ))

    # 7 recommend goods
    probes.append(_probe(
        f"聊天推荐商品 uid={buyer}",
        "POST /latitude/goods/recommendGoods",
        lambda: pm._fetch_chat_recommend_goods(buyer, 1, 5),
    ))

    # 8 product detail
    if goods_id:
        probes.append(_probe(
            f"商品详情 goods_id={goods_id}",
            "POST /glide/v2/mms/query/commit/on_shop/detail",
            lambda: pm.get_product_detail(str(goods_id)),
        ))

    # 9 parsed product list helper
    if goods_id:
        probes.append(_probe(
            "商品详情(本仓库解析后 product_info)",
            "(parsed)",
            lambda: pm.get_product_detail(str(goods_id)).get("product_info"),
        ))

    # 10 open platform logistics if order
    if order_sn:
        from Channel.pinduoduo.utils.API.logistics import LogisticsManager

        lm = LogisticsManager(shop, user)
        probes.append(_probe(
            f"开放平台物流 order_sn={order_sn}",
            "POST gw-api.pinduoduo.com/api/router pdd.logistics.ordertrace.get",
            lambda: lm.get_order_trace(order_sn),
        ))

    # 11 local db chat sessions sample
    sessions = db_manager.get_chat_sessions(account_id=1, status="active")[:3]
    probes.append(_probe(
        "本地 SQLite 会话(非MMS)",
        "customer.db chat_sessions",
        lambda: sessions,
    ))

    msgs = []
    if sessions:
        sid = sessions[0].get("id")
        if sid:
            msgs = db_manager.get_chat_messages(int(sid), limit=5)
    probes.append(_probe(
        "本地 SQLite 消息(非MMS)",
        "customer.db chat_messages",
        lambda: msgs,
    ))

    out = {
        "probed_at": datetime.now().isoformat(timespec="seconds"),
        "account": {"shop_id": shop, "user_id": user, "username": acc.get("username")},
        "buyer_uid": buyer,
        "order_sn_sample": order_sn,
        "goods_id_sample": goods_id,
        "open_platform_enabled": bool((config.get("pinduoduo_open") or {}).get("enabled")),
        "open_platform_has_token": bool(((config.get("pinduoduo_open") or {}).get("access_token") or "").strip()),
        "probes": probes,
    }

    out_path = ROOT / "temp" / "mms_full_probe.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
