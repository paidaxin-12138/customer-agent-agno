"""
全局消息抽象类
"""
class ChatMessage(object):
    """全局消息抽象基类"""
    msg_id = None         # 消息ID
    from_user = None       # 发送者ID
    to_user = None          # 接收者ID
    nickname = None         # 发送者昵称
    content = None         # 消息内容
    msg_type = None  # 消息类型，使用ContentType
    user_msg_type = None  # 用户消息类型
    timestamp = None  # 消息时间戳
    raw_data = None  # 原始数据

    def __init__(self, raw_data):
        self.raw_data = raw_data

    def __str__(self):
        return f"ChatMessage(msg_id={self.msg_id}, from_user={self.from_user}, to_user={self.to_user}, nickname={self.nickname}, content={self.content}, msg_type={self.msg_type}, timestamp={self.timestamp}, raw_data={self.raw_data},user_msg_type={self.user_msg_type})"
        

