"""改址审计写入。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from database.db_manager import db_manager
from utils.address_change_policy import mask_address_summary


def record_address_change(
    *,
    shop_id: str,
    seller_user_id: str,
    operator_username: str,
    buyer_uid: str,
    order_sn: str,
    shipping_status: int,
    action: str,
    address_before_summary: str = "",
    address_after_summary: str = "",
    parsed_from_message: str = "",
    api_success: Optional[bool] = None,
    api_error_msg: Optional[str] = None,
    shipped_override: bool = False,
) -> int:
    return db_manager.record_merchant_address_change(
        shop_id=str(shop_id),
        seller_user_id=str(seller_user_id),
        operator_username=str(operator_username or ""),
        buyer_uid=str(buyer_uid),
        order_sn=str(order_sn),
        shipping_status=int(shipping_status),
        action=str(action),
        address_before_summary=mask_address_summary(address_before_summary),
        address_after_summary=mask_address_summary(address_after_summary),
        parsed_from_message=(parsed_from_message or "")[:2000],
        api_success=api_success,
        api_error_msg=api_error_msg,
        shipped_override=shipped_override,
    )


def execute_address_change(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    店主弹窗点「确认改址」后调用（同步，可放线程）。

    Returns:
        {success, message, api_error}
    """
    from Channel.pinduoduo.utils.API.address_change import AddressChangeAPI

    shop_id = str(payload.get("platform_shop_id") or payload.get("shop_id") or "")
    seller_user_id = str(payload.get("seller_user_id") or "")
    buyer_uid = str(payload.get("buyer_uid") or "")
    order_sn = str(payload.get("order_sn") or "")
    operator = str(payload.get("login_username") or payload.get("operator_username") or "")
    pa = payload.get("parsed_address") or {}
    shipped_override = bool(payload.get("shipped_override"))

    api = AddressChangeAPI(shop_id, seller_user_id)
    result = api.submit_address_change(
        order_sn,
        name=str(pa.get("name") or ""),
        mobile=str(pa.get("mobile") or ""),
        province=str(pa.get("province") or ""),
        city=str(pa.get("city") or ""),
        district=str(pa.get("district") or ""),
        detail=str(pa.get("detail") or pa.get("full_text") or ""),
        shipped_override=shipped_override,
    )
    ok = bool(result.get("success"))
    err = result.get("error_msg")

    after_summary = (
        f"{pa.get('province','')}{pa.get('city','')}{pa.get('district','')}"
        f"{pa.get('detail','')} {pa.get('name','')} {pa.get('mobile','')}"
    ).strip()

    record_address_change(
        shop_id=shop_id,
        seller_user_id=seller_user_id,
        operator_username=operator,
        buyer_uid=buyer_uid,
        order_sn=order_sn,
        shipping_status=int(payload.get("shipping_status") or 0),
        action="confirm",
        address_before_summary=str(payload.get("address_before_summary") or ""),
        address_after_summary=after_summary,
        parsed_from_message=str(payload.get("question") or ""),
        api_success=ok,
        api_error_msg=str(err) if err else None,
        shipped_override=shipped_override,
    )

    from config import config

    if ok:
        msg = str(
            config.get(
                "chat.address_change_success_text",
                "亲，已为您提交地址修改申请，请留意物流更新。如有问题可随时联系我们。",
            )
        )
    else:
        msg = str(
            config.get(
                "chat.address_change_fail_text",
                "亲，很抱歉，平台当前不允许修改该订单的地址。建议您联系快递公司或收货人主动沟通，也可回复「人工」由客服协助。",
            )
        )
    return {"success": ok, "message": msg, "api_error": err, "not_configured": result.get("not_configured")}
