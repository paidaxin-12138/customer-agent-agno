# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""WebSocket 连接层可恢复 / 不可恢复错误。"""


class WsCredentialError(Exception):
    """Cookie / Token 无效，需人工重新登录，不应无限重连。"""
