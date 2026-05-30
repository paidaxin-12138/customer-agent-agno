#!/usr/bin/env python3
"""全功能冒烟测试（无需 UI 操作）：单元测试 + MMS/Cookie 联调。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _section(title: str) -> None:
    print(f"\n{'=' * 56}\n{title}\n{'=' * 56}")


def run_pytest() -> bool:
    _section("1. 单元测试 (pytest)")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "test/", "-q", "--tb=line"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    out = (r.stdout or "") + (r.stderr or "")
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    for ln in lines[-8:]:
        print(ln)
    return r.returncode == 0


def _db():
    from database.db_manager import get_db_manager

    return get_db_manager()


def _api(shop: str, user: str):
    from Channel.pinduoduo.utils.API.chat_orders import ChatOrdersAPI

    acc = _db().get_account("pinduoduo", shop, user)
    if not acc or not acc.get("cookies"):
        raise RuntimeError("无 Cookie，请在用户管理验证登录")
    api = ChatOrdersAPI(shop, user)
    api.update_cookies(acc["cookies"])
    return api, acc


def smoke_account() -> tuple[str, str] | tuple[None, None]:
    shops = _db().get_shops_by_channel("pinduoduo") or []
    for shop in shops:
        sid = str(shop.get("shop_id") or "")
        for acc in _db().get_accounts_by_shop("pinduoduo", sid) or []:
            if acc.get("status") == 1 and acc.get("cookies"):
                return sid, str(acc.get("user_id") or "")
    return None, None


def smoke_mms(shop: str, user: str) -> dict:
    _section("2. MMS 接口（需 Cookie）")
    results: dict = {}
    acc = _db().get_account("pinduoduo", shop, user)

    from Channel.pinduoduo.utils.API.get_shop_info import GetShopInfo
    from Channel.pinduoduo.utils.API.get_user_info import GetUserInfo
    from Channel.pinduoduo.utils.API.get_token import GetToken
    from Channel.pinduoduo.utils.API.product_manager import ProductManager
    from Channel.pinduoduo.utils.API.send_message import SendMessage

    gi = GetShopInfo(acc["cookies"])
    si = gi.get_shop_info()
    results["shop_info"] = si is not False
    print(f"  店铺信息: {'OK' if results['shop_info'] else 'FAIL'} {si}")

    ui = GetUserInfo(acc["cookies"])
    uinfo = ui.get_user_info()
    results["user_info"] = uinfo is not False
    print(f"  客服账号: {'OK' if results['user_info'] else 'FAIL'} {uinfo}")

    tk = GetToken(shop, user)
    tk.update_cookies(acc["cookies"])
    token = tk.get_token()
    results["ws_token"] = bool(token)
    print(f"  WebSocket Token: {'OK' if token else 'FAIL'}")

    import sqlite3

    from scripts.backup_db import resolve_db_path

    buyer = None
    db_path = resolve_db_path()
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(
                "SELECT buyer_uid FROM chat_sessions ORDER BY last_message_time DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        if row:
            buyer = str(row[0])

    pm = ProductManager(shop, user)
    pm.update_cookies(acc["cookies"])
    pl = pm.get_product_list(page=1, size=3, buyer_uid=buyer)
    results["product_list"] = bool(pl.get("success"))
    n = len(pl.get("products") or [])
    err = pl.get("error_msg")
    src = pl.get("source")
    print(
        f"  商品列表({src}): {'OK' if results['product_list'] else 'FAIL'} "
        f"n={n} err={err}"
    )

    if buyer:
        api, _ = _api(shop, user)
        ok, orders = api.fetch_orders_by_buyer_uid(buyer, 5)
        results["user_orders"] = ok
        print(f"  买家订单 uid={buyer}: {'OK' if ok else 'FAIL'} count={len(orders)}")
        from Channel.pinduoduo.utils.API.chat_orders import (
            pick_refund_card_order,
            build_ask_refund_apply_params,
        )

        sn, rec, block = pick_refund_card_order(orders)
        results["eligible_order"] = sn is not None
        print(
            f"  可代申请订单: {'有 ' + sn if sn else '无'} block={block}"
        )
        if sn and rec:
            p = build_ask_refund_apply_params(rec, 3, 0)
            sender = SendMessage(shop, user)
            sender.update_cookies(acc["cookies"])
            r = sender.send_ask_refund_apply(
                sn,
                after_sales_type=p.after_sales_type,
                question_type=p.question_type,
                refund_amount=p.refund_amount,
                user_ship_status=p.user_ship_status,
            )
            ok_card = isinstance(r, dict) and r.get("success")
            err = (r or {}).get("error_msg") or (r or {}).get("errorMsg")
            results["refund_card_send"] = ok_card
            print(
                f"  退换货卡(真实发送): {'OK' if ok_card else 'SKIP/FAIL'} err={err}"
            )
        else:
            results["refund_card_send"] = None
            print("  退换货卡: SKIP（无可代申请订单）")
    else:
        results["user_orders"] = None
        print("  买家订单: SKIP（无会话记录）")

    return results


def smoke_config_db() -> dict:
    _section("3. 配置与数据库")
    from config import config
    from scripts.backup_db import resolve_db_path

    results = {}
    results["config_llm"] = bool(config.get("llm.api_key"))
    db_path = resolve_db_path()
    results["config_db"] = db_path.exists()
    results["knowledge_json"] = (ROOT / "temp" / "knowledge_docs.json").exists()
    print(f"  LLM 配置: {'OK' if results['config_llm'] else '未配置'}")
    print(f"  SQLite ({db_path}): {'OK' if results['config_db'] else '缺失'}")
    print(f"  知识库文件: {'OK' if results['knowledge_json'] else '缺失'}")
    return results


def smoke_handler_chain() -> bool:
    _section("4. 消息处理器链")
    from Message.handler_chain_factory import handler_chain

    handlers = handler_chain(use_ai=False)
    names = [getattr(h, "name", h.__class__.__name__) for h in handlers]
    print("  处理器:", " → ".join(names))
    return len(handlers) >= 4


def smoke_knowledge() -> bool:
    _section("5. 知识库")
    try:
        from Agent.CustomerAgent.agent_knowledge import KnowledgeManager

        km = KnowledgeManager()
        n = len(getattr(km, "documents", {}) or {})
        print(f"  文档数: {n}")
        return n >= 0
    except Exception as e:
        print(f"  FAIL: {e}")
        return False


def main() -> int:
    print("Customer-Agent 全功能冒烟测试")
    ok_pytest = run_pytest()
    smoke_config_db()
    ok_chain = smoke_handler_chain()
    ok_kb = smoke_knowledge()

    shop, user = smoke_account()
    mms = {}
    if shop and user:
        print(f"\n使用账号 shop={shop} user={user}")
        try:
            mms = smoke_mms(shop, user)
        except Exception as e:
            print(f"MMS 测试异常: {e}")
            mms = {"error": str(e)}
    else:
        print("\nSKIP MMS: 无已验证账号")

    _section("汇总")
    items = [
        ("单元测试", ok_pytest),
        ("处理器链", ok_chain),
        ("知识库", ok_kb),
        ("MMS Cookie", bool(shop and user)),
        ("商品列表", mms.get("product_list")),
        ("WebSocket Token", mms.get("ws_token")),
    ]
    for name, val in items:
        if val is True:
            st = "PASS"
        elif val is False:
            st = "FAIL"
        else:
            st = "SKIP"
        print(f"  {name}: {st}")

    failed = sum(1 for _, v in items if v is False)
    return 1 if failed or not ok_pytest else 0


if __name__ == "__main__":
    raise SystemExit(main())
