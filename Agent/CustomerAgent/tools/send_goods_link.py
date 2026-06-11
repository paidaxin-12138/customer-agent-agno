# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from agno.run import RunContext
from agno.tools import tool
from Channel.pinduoduo.utils.API.send_message import SendMessage
from utils.agent_tool_guard import bind_tool_session_params, validate_shop_goods_id
from utils.agno_tool_offload import offload_tool
from utils.logger_loguru import get_logger

logger = get_logger("SendGoodsLinkTool")


@tool(name="send_goods_link", description="向用户发送商品卡片链接，用于客服主动推荐商品。")
@offload_tool
def send_goods_link(
    run_context: RunContext,
    recipient_uid: str,
    goods_id: int,
    shop_id: str,
    user_id: str,
) -> str:
    """
    向用户发送商品卡片链接。

    Args:
        recipient_uid: 接收消息的用户UID
        goods_id: 商品ID
        shop_id: 店铺ID
        user_id: 用户ID（账号ID）

    Returns:
        str: 发送结果，成功返回 True，失败返回错误信息
    """
    try:
        deps = getattr(run_context, "dependencies", None) or {}
        shop_id, user_id, recipient_uid, bind_err = bind_tool_session_params(
            deps, shop_id=shop_id, user_id=user_id, recipient_uid=recipient_uid
        )
        if bind_err:
            logger.info("send_goods_link 会话绑定失败: {}", bind_err)
            return f"发送失败：{bind_err}"

        try:
            from core.ops_telemetry import record_tool_call

            record_tool_call(
                "send_goods_link",
                f"goods_id={goods_id} to={recipient_uid}",
            )
        except Exception:
            pass
        if not goods_id:
            return "发送失败：缺少 goods_id"

        valid, verify_msg = validate_shop_goods_id(shop_id, user_id, goods_id)
        if not valid:
            logger.info("send_goods_link 商品校验未通过 goods_id={}: {}", goods_id, verify_msg)
            return f"发送失败：{verify_msg}"

        from core.turn_abort import check_turn_abort

        check_turn_abort()

        sender = SendMessage(shop_id, user_id)
        result = sender.send_mallGoodsCard(recipient_uid, goods_id, biz_type=2)

        if result and result.get("success"):
            logger.info(f"商品卡片发送成功: goods_id={goods_id}, to={recipient_uid}")
            return "商品卡片发送成功"
        else:
            error_msg = result.get('error_msg', '发送失败') if result else '发送失败'
            logger.error(f"商品卡片发送失败: {error_msg}, goods_id={goods_id}")
            return f"商品卡片发送失败: {error_msg}"

    except Exception as e:
        logger.error(f"发送商品卡片异常: {str(e)}")
        return f"发送商品卡片异常: {str(e)}"
