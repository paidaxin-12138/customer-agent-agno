"""
弱监督模式：多店多账号下 AI 优先自动接待，减少人工截流与转接前等待。

开启后：
- 关闭「接待专用号须收到 TRANSFER 才走责任链」；
- 新建会话默认 ai_mode=True；
- 仍保留关键词/情绪/改址等业务 Handler 与人工协助弹窗。
"""
from __future__ import annotations

from config import get_config


def weak_supervision_enabled() -> bool:
    return bool(get_config("chat.weak_supervision_enabled", False))


def effective_inbound_transfer_gate() -> bool:
    """弱监督下不阻塞责任链，所有在线账号直接 AI/规则处理。"""
    if weak_supervision_enabled():
        return False
    from utils.inbound_transfer_gate import gate_until_transfer_enabled

    return gate_until_transfer_enabled()


def default_ai_mode_for_account(account_id: int) -> bool:
    """新建会话默认是否 AI 接待。"""
    if weak_supervision_enabled():
        return True
    from utils.inbound_transfer_gate import default_ai_mode_for_new_session

    return default_ai_mode_for_new_session(int(account_id))
