#!/usr/bin/env python3
"""探测本仓库已知 MMS 只读接口，汇总可获取字段（不写库、不发消息）。"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Channel.pinduoduo.utils.API.chat_orders import ChatOrdersAPI
from Channel.pinduoduo.utils.API.get_shop_info import GetShopInfo
from Channel.pinduoduo.utils.API.get_token import GetToken
from Channel.pinduoduo.utils.API.get_user_info import GetUserInfo
from Channel.pinduoduo.utils.API.product_manager import ProductManager
from Channel.pinduoduo.utils.base_request import BaseRequest
from database.db_manager import db_manager


def _keys_preview(obj: Any, depth: int = 0, max_depth: int = 2) -> Any:
    if depth >= max_depth:
        if isinstance(obj, dict):
            return f"{{... {len(obj)} keys}}"
        if isinstance(obj, list):
            return f"[... {len(obj)} items]"
        return obj
    if isinstance(obj, dict):
        out = {}
        for k, v in list(obj.items())[:30]:
            out[k] = _keys_preview(v, depth + 1, max_depth)
        if len(obj) > 30:
            out["..."] = f"+{len(obj) - 30} more keys"
        return out
    if isinstance(obj, list):
        if not obj:
            return []
        return [_keys_preview(obj[0], depth + 1, max_depth), f"... total {len(obj)}"]
    if isinstance(obj, str) and len(obj) > 120:
        return obj[:120] + "..."
    return obj


def _probe(
    name: str,
    fn: Callable[[], Any],
) -> Dict[str, Any]:
    row: Dict[str, Any] = {"name": name, "ok": False}
    try:
        result = fn()
        row["ok"] = result is not None and result is not False
        row["preview"] = _keys_preview(result)
        if isinstance(result, dict):
            row["success"] = result.get("success")
            err = result.get("errorMsg") or result.get("error_msg") or result.get("error_code")
            if err:
                row["error"] = str(err)[:200]
        elif isinstance(result, tuple):
            row["tuple"] = list(result)
        elif isinstance(result, list):
            row["list_len"] = len(result)
        elif isinstance(result, str):
            row["str_preview"] = result[:80] + ("..." if len(result) > 80 else "")
    except Exception as e:
        row["error"] = str(e)[:300]
    return row


def _raw_post(api: BaseRequest, url: str, body: dict, referer: str) -> Optional[dict]:
    anti = (api.cookies or {}).get("anti_content") or (api.cookies or {}).get("anti-content", "")
    headers = {
        "accept": "application/json, text/plain, */*",
        "anti-content": anti or "",
        "content-type": "application/json;charset=UTF-8",
        "origin": "https://mms.pinduoduo.com",
        "referer": referer,
    }
    return api.post(url, json_data=body, headers=headers)


def main() -> int:
    acc = db_manager.get_account_row_by_id(1)
    if not acc or not acc.get("cookies"):
        print("NO_ACCOUNT")
        return 1

    cookies = acc.get("cookies")
    if isinstance(cookies, str):
        cookies = json.loads(cookies)

    shop_id = str(acc.get("shop_id") or "").strip()
    user_id = str(acc.get("user_id") or "").strip()

    # 若 DB 未写 shop/user，尝试从 userinfo 补全
    ui = GetUserInfo(cookies=cookies)
    user_tuple = ui.get_user_info()
    if user_tuple and user_tuple is not False:
        if not user_id and user_tuple[0] is not None:
            user_id = str(user_tuple[0])
        if not shop_id and user_tuple[2] is not None:
            shop_id = str(user_tuple[2])

    buyer_uid = "4216881609"  # 历史测试买家；无订单时接口仍返回结构

    probes: List[Dict[str, Any]] = []
    meta = {
        "probed_at": datetime.now().isoformat(timespec="seconds"),
        "username": acc.get("username"),
        "shop_id": shop_id or None,
        "user_id": user_id or None,
        "buyer_uid_sample": buyer_uid,
    }

    probes.append(_probe("janus/userinfo", lambda: {"result_keys": ui.get_user_info()}))

    gsi = GetShopInfo(cookies=cookies)
    probes.append(
        _probe(
            "earth/queryMerchantInfoByMallId",
            lambda: gsi.post(
                "https://mms.pinduoduo.com/earth/api/merchant/queryMerchantInfoByMallId",
                json_data={},
                headers={"Referer": "https://mms.pinduoduo.com/home", "Origin": "https://mms.pinduoduo.com"},
            ),
        )
    )

    if shop_id and user_id:
        gt = GetToken(shop_id, user_id)
        probes.append(_probe("chats/getToken", lambda: {"token_len": len(gt.get_token() or "")}))

        pm = ProductManager(shop_id, user_id)
        probes.append(_probe("vodka/mall/goodsList p1", lambda: pm._fetch_mall_goods_list(1, 3)))
        probes.append(
            _probe(
                "latitude/recommendGoods",
                lambda: pm._fetch_chat_recommend_goods(buyer_uid, 1, 3),
            )
        )
        gid = None
        gl = pm._fetch_mall_goods_list(1, 1)
        if gl and gl.get("success"):
            lst = (gl.get("result") or {}).get("goods_list") or (gl.get("result") or {}).get("list") or []
            if isinstance(lst, list) and lst:
                gid = lst[0].get("goods_id") or lst[0].get("goodsId")
        if not gid:
            rg = pm._fetch_chat_recommend_goods(buyer_uid, 1, 1)
            if rg and rg.get("success"):
                goods = (rg.get("result") or {}).get("recommendGoods") or (rg.get("result") or {}).get("onSaleGoods") or []
                if goods:
                    gid = goods[0].get("goodsId") or goods[0].get("goods_id")
        if gid:
            probes.append(_probe(f"glide/on_shop/detail goods_id={gid}", lambda: pm.get_product_detail(gid)))

        co = ChatOrdersAPI(shop_id, user_id)
        probes.append(
            _probe(
                f"latitude/userAllOrder buyer={buyer_uid}",
                lambda: co.fetch_orders_by_buyer_uid(buyer_uid, 5),
            )
        )
        api_ok, orders = co.fetch_orders_by_buyer_uid(buyer_uid, 5)
        order_sn = None
        if api_ok and orders:
            order_sn = orders[0].get("orderSn") or orders[0].get("order_sn")
        if order_sn:
            probes.append(
                _probe(
                    f"latitude/afterSales/getDetail order={order_sn}",
                    lambda: co.get_order_pickup_info(order_sn),
                )
            )

        from Channel.pinduoduo.utils.API.send_message import SendMessage

        sm = SendMessage(shop_id, user_id)
        probes.append(_probe("latitude/getAssignCsList", lambda: sm.getAssignCsList()))

        br = BaseRequest(shop_id, user_id)
        probes.append(
            _probe(
                "latitude/sendUserHelpLink (community, probe only)",
                lambda: _raw_post(
                    br,
                    "https://mms.pinduoduo.com/latitude/message/sendUserHelpLink",
                    {"link_type": 1, "uid": buyer_uid, "order_sn": order_sn or ""},
                    "https://mms.pinduoduo.com/chat-merchant/index.html",
                ),
            )
        )
    else:
        br = BaseRequest()
        br.update_cookies(cookies)
        probes.append(_probe("vodka/mall/goodsList (cookies only)", lambda: _raw_post(
            br,
            "https://mms.pinduoduo.com/vodka/v2/mms/query/display/mall/goodsList",
            {"page": 1, "page_size": 3, "pre_sale_type": 0, "out_goods_sn_gray_flag": True,
             "shipment_time_type": 3, "is_onsale": 1, "sold_out": 0, "order_by": "created_at:desc,id:desc"},
            "https://mms.pinduoduo.com/goods/goods_list",
        )))
        probes.append(_probe("chats/getToken (needs shop/user in DB)", lambda: None))

    out = {"meta": meta, "probes": probes}
    out_path = ROOT / "temp" / "mms_probe_result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
