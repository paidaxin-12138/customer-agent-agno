from agno.tools import tool
from Channel.pinduoduo.utils.API.send_message import SendMessage
from utils.logger_loguru import get_logger

logger = get_logger("SendGoodsLinkTool")


@tool(name="send_goods_link", description="向用户发送商品卡片链接，用于客服主动推荐商品。")
def send_goods_link(recipient_uid: str, goods_id: int, shop_id: str, user_id: str) -> str:
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
        try:
            from core.ops_telemetry import record_tool_call

            record_tool_call(
                "send_goods_link",
                f"goods_id={goods_id} to={recipient_uid}",
            )
        except Exception:
            pass
        if not all([recipient_uid, goods_id, shop_id, user_id]):
            return f"发送失败：缺少必要的参数 (recipient_uid={recipient_uid}, goods_id={goods_id}, shop_id={shop_id}, user_id={user_id})"

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
