# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from agno.run import RunContext
from agno.tools import tool
from Channel.pinduoduo.utils.API.send_message import SendMessage
from utils.agent_tool_guard import allow_transfer_tool_call, bind_tool_session_params
from utils.logger_loguru import get_logger

logger = get_logger("TransferConversationTool")


def _select_best_cs_uid(cs_list: dict, my_cs_uid: str) -> str | None:
    """按可用性与负载选择最优客服。"""
    candidates = []
    for uid, info in (cs_list or {}).items():
        if uid == my_cs_uid:
            continue
        info = info or {}
        # 常见在线字段兼容
        online = info.get("online", info.get("is_online", True))
        if online is False:
            continue
        # 常见负载字段兼容：越小越优
        load = (
            info.get("current_sessions")
            or info.get("session_count")
            or info.get("load")
            or 0
        )
        try:
            load = int(load)
        except Exception:
            load = 0
        candidates.append((load, uid))

    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][1]

@tool(name="transfer_conversation", description="将当前会话转接给人工客服。")
def transfer_conversation(
    run_context: RunContext,
    shop_id: str,
    user_id: str,
    recipient_uid: str,
) -> str:
    """
    将当前会话转接给人工客服。
    """
    try:
        deps = getattr(run_context, "dependencies", None) or {}
        allowed, deny_reason = allow_transfer_tool_call(deps)
        if not allowed:
            logger.info("transfer_conversation 被拒绝: {}", deny_reason)
            return deny_reason

        shop_id, user_id, recipient_uid, bind_err = bind_tool_session_params(
            deps, shop_id=shop_id, user_id=user_id, recipient_uid=recipient_uid
        )
        if bind_err:
            logger.info("transfer_conversation 会话绑定失败: {}", bind_err)
            return bind_err

        try:
            from core.ops_telemetry import record_tool_call

            record_tool_call(
                "transfer_conversation",
                f"shop_id={shop_id} user_id={user_id} recipient={recipient_uid}",
            )
        except Exception:
            pass

        sender = SendMessage(shop_id, user_id)
        cs_list = sender.getAssignCsList()
        my_cs_uid = f"cs_{shop_id}_{user_id}"
        if cs_list and isinstance(cs_list, dict):
            cs_uid = _select_best_cs_uid(cs_list, my_cs_uid)
            if cs_uid:
                # 转移会话
                transfer_result = sender.move_conversation(recipient_uid, cs_uid)
                if transfer_result and transfer_result.get('success'):
                    return True
                else:
                    return False
            else:
                return False
       
    except Exception as e:
        return f"转接过程中发生错误: {str(e)}"
