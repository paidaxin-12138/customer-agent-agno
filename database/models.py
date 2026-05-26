from sqlalchemy import Column, Integer, String, Text, ForeignKey, DateTime, Boolean, Index, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Channel(Base):
    """渠道表，存储电商渠道基本信息"""
    __tablename__ = 'channels'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_name = Column(String(50), unique=True, nullable=False, comment='渠道名称')
    description = Column(String(255), comment='渠道描述')
    
    # 关联关系 - 一个渠道可以有多个店铺
    shops = relationship('Shop', back_populates='channel', cascade='all, delete-orphan')
    
    def __repr__(self):
        return f"<Channel(channel_name='{self.channel_name}')>"


class Shop(Base):
    """店铺表，存储店铺基本信息"""
    __tablename__ = 'shops'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    channel_id = Column(Integer, ForeignKey('channels.id'), nullable=False)
    shop_id = Column(String(100), nullable=False, comment='店铺ID')
    shop_name = Column(String(100), nullable=False, comment='店铺名称')
    shop_logo = Column(String(255), nullable=True, comment='店铺logo')
    description = Column(String(255), comment='店铺描述')
    
    # 关联关系 - 多个店铺属于一个渠道，一个店铺可以有多个账号
    channel = relationship('Channel', back_populates='shops')
    accounts = relationship('Account', back_populates='shop', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<Shop(shop_id='{self.shop_id}', shop_name='{self.shop_name}', channel='{self.channel.channel_name if self.channel else None}')>" 


class Account(Base):
    """账号表，存储店铺账号信息"""
    __tablename__ = 'accounts'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    shop_id = Column(Integer, ForeignKey('shops.id'), nullable=False)
    user_id = Column(String(100), nullable=False, comment='用户ID')
    username = Column(String(100), nullable=False, comment='登录用户名')
    password = Column(String(255), nullable=False, comment='登录密码')
    cookies = Column(Text, comment='存储登录cookies信息的JSON字符串')
    status = Column(Integer, default=None, comment='账号状态: None-未验证, 0-休息,1-在线, 3-离线')
    
    # 关联关系 - 多个账号属于一个店铺
    shop = relationship('Shop', back_populates='accounts')
    chat_sessions = relationship('ChatSession', back_populates='account', cascade='all, delete-orphan')
    
    def __repr__(self):
        # 不显示密码，保证安全
        return f"<Account(username='{self.username}', shop='{self.shop.shop_name if self.shop else None}')>"


class ChatSession(Base):
    """买家会话表（与拼多多买家 UID 一对一对应到接待账号下）"""
    __tablename__ = 'chat_sessions'
    __table_args__ = (
        UniqueConstraint('account_id', 'buyer_uid', name='uq_chat_session_account_buyer'),
        Index('idx_chat_sessions_account', 'account_id'),
        Index('idx_chat_sessions_buyer', 'buyer_uid'),
        Index('idx_chat_sessions_status', 'status'),
        Index('idx_chat_sessions_updated', 'updated_at'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    account_name = Column(String(100), nullable=True, comment='接待登录名')
    platform_shop_id = Column(String(100), nullable=False, comment='平台店铺ID')
    buyer_uid = Column(String(100), nullable=False, comment='拼多多买家UID')
    buyer_nickname = Column(String(100), nullable=True)
    avatar_url = Column(String(255), nullable=True)
    status = Column(String(20), default='active', comment='active/closed/transferred')
    ai_mode = Column(Boolean, default=True)
    last_message = Column(Text, nullable=True)
    last_message_time = Column(DateTime, nullable=True)
    unread_count = Column(Integer, default=0)
    # 三层记忆：任务状态 JSON、长期摘要 JSON、已纳入摘要的最后消息 id
    task_state_json = Column(Text, nullable=True)
    long_term_summary = Column(Text, nullable=True)
    memory_summary_through_id = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship('Account', back_populates='chat_sessions')
    messages = relationship('ChatMessage', back_populates='session', cascade='all, delete-orphan')

    def __repr__(self):
        return f"<ChatSession(buyer_uid={self.buyer_uid}, account_id={self.account_id})>"


class ChatMessage(Base):
    """聊天消息表"""
    __tablename__ = 'chat_messages'
    __table_args__ = (
        Index('idx_chat_messages_session', 'session_id'),
        Index('idx_chat_messages_account', 'account_id'),
        Index('idx_chat_messages_created', 'created_at'),
        Index('idx_chat_messages_msgid', 'message_id'),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(Integer, ForeignKey('chat_sessions.id'), nullable=False)
    message_id = Column(String(100), nullable=True, comment='拼多多消息ID去重')
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=False)
    sender_type = Column(String(20), nullable=False, comment='customer/ai/human/system')
    content = Column(Text, nullable=False)
    content_type = Column(String(20), default='text')
    image_url = Column(String(500), nullable=True)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    session = relationship('ChatSession', back_populates='messages')

    def __repr__(self):
        return f"<ChatMessage(sender={self.sender_type}, id={self.id})>"


class QuickReply(Base):
    """快捷回复"""
    __tablename__ = 'quick_replies'
    __table_args__ = (Index('idx_quick_replies_account', 'account_id'),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, ForeignKey('accounts.id'), nullable=True, comment='NULL=全局')
    category = Column(String(50), nullable=True)
    title = Column(String(100), nullable=True)
    content = Column(Text, nullable=False)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    
class Keyword(Base):
    """关键词表，存储关键词信息"""
    __tablename__ = 'keywords'

    id = Column(Integer, primary_key=True, autoincrement=True)
    keyword = Column(String(100), nullable=False, comment='关键词')

    def __repr__(self):
        return f"<Keyword(keyword='{self.keyword}')>"




