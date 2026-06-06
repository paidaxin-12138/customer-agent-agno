"""WebSocket 连接层可恢复 / 不可恢复错误。"""


class WsCredentialError(Exception):
    """Cookie / Token 无效，需人工重新登录，不应无限重连。"""
