#!/usr/bin/env python3
"""
现场测试：订单查询 → 购买天数策略 →（可选）真实发送退换货卡片。

用法:
  uv run python scripts/test_after_sales_card_live.py
  uv run python scripts/test_after_sales_card_live.py --send
  uv run python scripts/test_after_sales_card_live.py --buyer <买家UID> --send
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from Channel.pinduoduo.utils.API.chat_orders import (  # noqa: E402
    ChatOrdersAPI,
    build_ask_refund_apply_params,
    days_since_purchase,
    find_order_by_sn,
    order_purchase_unix_ts,
)
from Channel.pinduoduo.utils.API.send_message import SendMessage  # noqa: E402
from utils.after_sales_policy import (  # noqa: E402
    AfterSalesAction,
    decide_after_sales,
    detect_after_sales_intent,
)


def _db():
    from database.db_manager import get_db_manager

    return get_db_manager()


def _api_with_cookies(shop_id: str, user_id: str):
    """从 SQLite 加载 Cookie（脚本环境无 DI 容器）。"""
    acc = _db().get_account("pinduoduo", shop_id, user_id)
    if not acc or not acc.get("cookies"):
        raise RuntimeError("账号不存在或 Cookie 为空，请在用户管理里验证登录")
    api = ChatOrdersAPI(shop_id, user_id)
    api.update_cookies(acc["cookies"])
    api.account_name = acc.get("username") or user_id
    return api


def _default_account():
    db_manager = _db()
    shops = db_manager.get_shops_by_channel("pinduoduo") or []
    for shop in shops:
        sid = str(shop.get("shop_id") or "")
        accounts = db_manager.get_accounts_by_shop("pinduoduo", sid) or []
        for acc in accounts:
            if acc.get("status") == 1 and acc.get("cookies"):
                return sid, str(acc.get("user_id") or "")
    return None, None


def main() -> int:
    parser = argparse.ArgumentParser(description="退换货卡片 MMS 联调测试")
    parser.add_argument("--shop", help="平台店铺 ID")
    parser.add_argument("--user", help="客服 user_id")
    parser.add_argument("--buyer", help="买家 UID")
    parser.add_argument(
        "--text", default="我想退货", help="模拟买家话术（用于意图/策略）"
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="真实调用 ask_refund_apply/send（会发给买家）",
    )
    args = parser.parse_args()

    shop_id = args.shop or ""
    user_id = args.user or ""
    if not shop_id or not user_id:
        shop_id, user_id = _default_account()
    if not shop_id or not user_id:
        print("FAIL: 未找到已验证且带 Cookie 的拼多多账号")
        return 1

    buyer_uid = args.buyer
    if not buyer_uid:
        db_manager = _db()
        sessions = db_manager.get_recent_chat_sessions(limit=1)  # may not exist
        if hasattr(db_manager, "list_chat_sessions"):
            rows = db_manager.list_chat_sessions(limit=1)
            if rows:
                buyer_uid = str(rows[0].get("buyer_uid") or "")
        if not buyer_uid:
            import sqlite3

            db_path = ROOT / "temp" / "customer.db"
            conn = sqlite3.connect(db_path)
            row = conn.execute(
                "SELECT buyer_uid FROM chat_sessions ORDER BY last_message_time DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if row:
                buyer_uid = str(row[0])

    if not buyer_uid:
        print("FAIL: 请用 --buyer 指定买家 UID")
        return 1

    print(f"账号 shop={shop_id} user={user_id}")
    print(f"买家 uid={buyer_uid}")
    print(f"模拟话术: {args.text!r}")
    print("-" * 50)

    try:
        api = _api_with_cookies(shop_id, user_id)
    except RuntimeError as e:
        print(f"FAIL: {e}")
        return 1

    status, order_sn, orders = api.resolve_order_for_buyer(buyer_uid)
    print(f"[1] 订单查询 status={status} order_sn={order_sn} count={len(orders)}")

    if status == "api_error":
        print("FAIL: MMS 订单接口失败（Cookie 过期或网络）")
        return 2
    if status == "no_orders":
        print("FAIL: 该买家 UID 下无订单")
        return 3
    if status == "no_eligible":
        print("SKIP: 有订单但均不可代申请（已退款/售后中），请用一笔未退款订单测试")
        for o in orders[:3]:
            print(
                f"  - {o.get('orderSn')} {o.get('orderStatusStr')} "
                f"payStatus={o.get('payStatus')}"
            )
        return 0
    if not order_sn:
        print("FAIL: 无订单号")
        return 3

    order_rec = find_order_by_sn(orders, order_sn)
    ts = order_purchase_unix_ts(order_rec) if order_rec else None
    days = days_since_purchase(order_rec) if order_rec else None
    print(f"[2] 购买时间 ts={ts} days={days}")
    if order_rec:
        time_keys = sorted(
            k
            for k in order_rec.keys()
            if "time" in k.lower() or "date" in k.lower()
        )
        if time_keys:
            print(f"    订单时间字段: {time_keys}")

    intent = detect_after_sales_intent(args.text)
    from config import config

    decision = decide_after_sales(
        days,
        intent,
        return_refund_days=float(
            config.get("chat.after_sales_apply_return_refund_days", 7) or 7
        ),
        exchange_max_days=float(
            config.get("chat.after_sales_apply_exchange_max_days", 90) or 90
        ),
    )
    print(
        f"[3] 策略 intent={intent.value} action={decision.action.value} "
        f"type={decision.after_sales_type} reason={decision.reason}"
    )

    if decision.action != AfterSalesAction.SEND_CARD:
        print("SKIP 发卡: 当前策略为转人工，未执行 --send")
        return 0

    amount_fen = api.pick_refund_amount_fen(buyer_uid, order_sn, orders)
    print(f"[4] 退款金额(分)={amount_fen}")
    if not amount_fen or amount_fen <= 0:
        print("FAIL: 无法获取订单金额，发卡会失败")
        return 4

    pickup = api.get_order_pickup_info(order_sn)
    print(f"[5] reposeInfo keys={list(pickup.keys())[:8] if pickup else []}")

    if not args.send:
        print("OK(预检): 可发卡；加 --send 将真实发送给买家")
        return 0

    try:
        acc = _db().get_account("pinduoduo", shop_id, user_id)
        sender = SendMessage(shop_id, user_id)
        sender.update_cookies(acc["cookies"])
        sender.account_name = acc.get("username") or user_id
    except Exception as e:
        print(f"FAIL: 初始化发送器: {e}")
        return 1

    card_params = build_ask_refund_apply_params(
        order_rec,
        int(decision.after_sales_type or 3),
        int(amount_fen),
        default_shipped_question_type=int(
            config.get("chat.after_sales_apply_question_type", 1) or 1
        ),
        default_unshipped_question_type=int(
            config.get("chat.after_sales_apply_question_type_unshipped", 0) or 0
        ),
        card_message=config.get("chat.after_sales_apply_card_message"),
    )
    print(
        f"[5b] 发卡参数 type={card_params.after_sales_type} "
        f"question_type={card_params.question_type} "
        f"amount_fen={card_params.refund_amount} ship={card_params.user_ship_status}"
    )
    result = sender.send_ask_refund_apply(
        order_sn,
        after_sales_type=card_params.after_sales_type,
        question_type=card_params.question_type,
        refund_amount=card_params.refund_amount,
        message=card_params.message or None,
        user_ship_status=card_params.user_ship_status,
    )
    ok = isinstance(result, dict) and result.get("success") is True
    err = None
    if isinstance(result, dict):
        err = result.get("errorMsg") or result.get("error_msg")
    print(f"[6] 发卡 success={ok} error={err}")
    if ok:
        print("OK: 退换货卡片已发送")
        return 0
    print("FAIL: 发卡失败")
    if result:
        print(json.dumps(result, ensure_ascii=False, indent=2)[:800])
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
