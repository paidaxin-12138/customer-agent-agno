import os
import json
from datetime import datetime
from pathlib import Path
from sqlalchemy import create_engine, func, or_, desc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional, Tuple, Union
from utils.chat_time import now_for_db
from utils.logger_loguru import get_logger
from database.models import (
    Base,
    Channel,
    Shop,
    Account,
    Keyword,
    ChatSession,
    ChatMessage,
    QuickReply,
    MerchantRefundApplyLog,
    MerchantAddressChangeLog,
)
from database.chat_store import ChatStoreMixin

# 与 config.json / config_base 默认一致
DEFAULT_DB_PATH = "data/customer_agent.db"


class DatabaseManager(ChatStoreMixin):
    """数据库管理类，提供数据库操作的封装"""
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        """初始化数据库连接
        
        Args:
            db_path: 数据库文件路径
        """
        if self._initialized:
            return
            
        db_file = Path(db_path)
        from utils.private_paths import ensure_private_dir, ensure_private_file

        if db_file.parent and str(db_file.parent) not in (".", ""):
            ensure_private_dir(db_file.parent)

        # 创建数据库引擎（WAL + 多线程 asyncio.to_thread 安全）
        self.engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False, "timeout": 10.0},
        )
        with self.engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA synchronous=NORMAL")
        self.Session = sessionmaker(bind=self.engine)
        
        self.logger = get_logger()

        # 创建表结构 + 遗留增量补丁（与 alembic revision 0001 共用）
        Base.metadata.create_all(self.engine)
        from database.schema_migrations import apply_legacy_migrations

        apply_legacy_migrations(self.engine, self.logger)

        if db_file.exists():
            ensure_private_file(db_file)

        self._initialized = True
        # 初始化数据库
        self.init_db()

    def init_db(self):
        """初始化渠道信息"""
        channel_name = "pinduoduo"
        description = "拼多多"
        self.add_channel(channel_name, description)
        self._seed_default_quick_replies()

    def _seed_default_quick_replies(self) -> None:
        session = self.get_session()
        try:
            n = session.query(QuickReply).filter(QuickReply.account_id.is_(None)).count()
            if n > 0:
                return
            defaults = [
                ("问候", "欢迎", "亲，欢迎光临本店，有什么可以帮您的吗？"),
                ("物流", "发货", "您好，我们会尽快为您安排发货，请您耐心等待。"),
                ("售后", "退换", "您好，如需退换货请在订单页发起售后，我们会尽快处理。"),
            ]
            for cat, title, content in defaults:
                session.add(
                    QuickReply(
                        account_id=None,
                        category=cat,
                        title=title,
                        content=content,
                    )
                )
            session.commit()
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.warning(f"初始化快捷回复: {e}")
        finally:
            session.close()


    def get_session(self):
        """获取数据库会话"""
        return self.Session()
    
    # 渠道相关操作
    def add_channel(self, channel_name: str, description: str = None) -> bool:
        """添加渠道
        
        Args:
            channel_name: 渠道名称
            description: 渠道描述
            
        Returns:
            bool: 是否添加成功
        """
        session = self.get_session()
        try:
            # 检查渠道是否已存在
            existing = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if existing:
                return True
                
            # 创建新渠道
            channel = Channel(channel_name=channel_name, description=description)
            session.add(channel)
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"添加渠道失败: {str(e)}")
            return False
        finally:
            session.close()
    
    def get_channel(self, channel_name: str) -> Optional[Dict[str, Any]]:
        """获取渠道信息
        
        Args:
            channel_name: 渠道名称
            
        Returns:
            Optional[Dict]: 渠道信息或None
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return None
                
            return {
                'id': channel.id,
                'channel_name': channel.channel_name,
                'description': channel.description
            }
        except SQLAlchemyError as e:
            self.logger.error(f"获取渠道失败: {str(e)}")
            return None
        finally:
            session.close()
    
    def get_all_channels(self) -> List[Dict[str, Any]]:
        """获取所有渠道
        
        Returns:
            List[Dict]: 渠道列表
        """
        session = self.get_session()
        try:
            channels = session.query(Channel).all()
            return [
                {
                    'id': channel.id,
                    'channel_name': channel.channel_name,
                    'description': channel.description
                }
                for channel in channels
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"获取渠道列表失败: {str(e)}")
            return []
        finally:
            session.close()
    
    def delete_channel(self, channel_name: str) -> bool:
        """删除渠道
        
        Args:
            channel_name: 渠道名称
            
        Returns:
            bool: 是否删除成功
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                self.logger.warning(f"渠道 {channel_name} 不存在")
                return False
                
            session.delete(channel)
            session.commit()
            self.logger.info(f"成功删除渠道: {channel_name}")
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"删除渠道失败: {str(e)}")
            return False
        finally:
            session.close()
    
    # 店铺相关操作
    def add_shop(self, channel_name: str, shop_id: str, shop_name: str, shop_logo: str, description: str = None) -> bool:
        """添加店铺
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            shop_name: 店铺名称
            shop_logo: 店铺logo
            description: 店铺描述
            
        Returns:
            bool: 是否添加成功
        """
        session = self.get_session()
        try:
            # 获取对应渠道
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                self.logger.error(f"添加店铺失败: 渠道 {channel_name} 不存在")
                return False
            
            # 检查店铺是否已存在
            existing = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if existing:
                self.logger.warning(f"店铺 {shop_id} 已存在于渠道 {channel_name}")
                return False
            
            # 创建新店铺
            shop = Shop(
                channel_id=channel.id,
                shop_id=shop_id,
                shop_name=shop_name,
                shop_logo=shop_logo,
                description=description
            )
            
            session.add(shop)
            session.commit()
            self.logger.info(f"成功添加店铺: {shop_name}({shop_id}) 到渠道 {channel_name}")
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"添加店铺失败: {str(e)}")
            return False
        finally:
            session.close()
    
    def get_shop(self, channel_name: str, shop_id: str) -> Optional[Dict[str, Any]]:
        """获取店铺信息
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            
        Returns:
            Optional[Dict]: 店铺信息或None
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return None
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                return None
                
            return {
                'id': shop.id,
                'channel_id': shop.channel_id,
                'channel_name': channel_name,
                'shop_id': shop.shop_id,
                'shop_name': shop.shop_name,
                'shop_logo': shop.shop_logo,
                'description': shop.description,
            }
        except SQLAlchemyError as e:
            self.logger.error(f"获取店铺失败: {str(e)}")
            return None
        finally:
            session.close()
    
    def get_shops_by_channel(self, channel_name: str) -> List[Dict[str, Any]]:
        """获取指定渠道下的所有店铺
        
        Args:
            channel_name: 渠道名称
            
        Returns:
            List[Dict]: 店铺列表
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return []
                
            shops = session.query(Shop).filter(Shop.channel_id == channel.id).all()
            return [
                {
                    'id': shop.id,
                    'channel_id': shop.channel_id,
                    'channel_name': channel_name,
                    'shop_id': shop.shop_id,
                    'shop_name': shop.shop_name,
                    'shop_logo': shop.shop_logo,
                    'description': shop.description
                }
                for shop in shops
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"获取店铺列表失败: {str(e)}")
            return []
        finally:
            session.close()
    
    def update_shop_info(self, channel_name: str, shop_id: str, shop_name: str = None, shop_logo: str = None, description: str = None) -> bool:
        """更新店铺信息
        
        Args:
            channel_name: 渠道名称
            shop_id: 新的店铺ID
            shop_name: 新的店铺名称
            shop_logo: 新的店铺logo
            description: 新的店铺描述
            
        Returns:
            bool: 是否更新成功
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return False
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                return False
            
            if shop_id is not None:
                shop.shop_id = shop_id
            if shop_name is not None:
                shop.shop_name = shop_name
            if shop_logo is not None:
                shop.shop_logo = shop_logo
            if description is not None:
                shop.description = description
                
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"更新店铺信息失败: {str(e)}")
            return False
        finally:
            session.close()
    
    def delete_shop(self, channel_name: str, shop_id: str) -> bool:
        """删除店铺
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
        Returns:
            bool: 是否删除成功
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return False
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                return False
                
            session.delete(shop)
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"删除店铺失败: {str(e)}")
            return False
        finally:
            session.close()

    # 账号相关操作
    def add_account(self, channel_name: str, shop_id: str, user_id: str, username: str, password: str, cookies: str = None) -> bool:
        """添加账号
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            user_id: 用户ID
            username: 登录用户名
            password: 登录密码
            cookies: cookies JSON字符串
            
        Returns:
            bool: 是否添加成功
        """
        session = self.get_session()
        try:
            # 获取对应店铺
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                self.logger.error(f"添加账号失败: 渠道 {channel_name} 不存在")
                return False
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                self.logger.error(f"添加账号失败: 店铺 {shop_id} 不存在")
                return False
            
            # 检查账号是否已存在
            existing = session.query(Account).filter(
                Account.shop_id == shop.id,
                Account.username == username
            ).first()
            
            if existing:
                self.logger.warning(f"账号 {username} 已存在于店铺 {shop_id}")
                return False
            
            from utils.credential_crypto import maybe_encrypt_for_storage

            # 创建新账号
            account = Account(
                shop_id=shop.id,
                user_id=user_id,
                username=username,
                password=maybe_encrypt_for_storage(password),
                cookies=maybe_encrypt_for_storage(cookies) if cookies else cookies,
                status=None
            )
            
            session.add(account)
            session.commit()
            self.logger.info(f"成功添加账号: {username} 到店铺 {shop_id}")
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"添加账号失败: {str(e)}")
            return False
        finally:
            session.close()
    
    def get_account(
        self,
        channel_name: str,
        shop_id: str,
        user_id: str,
        *,
        include_secrets: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """获取账号信息
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            user_id: 用户ID
            include_secrets: 是否解密并返回 password/cookies（登录与 HTTP 需要 True）
        Returns:
            Optional[Dict]: 账号信息或None
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                self.logger.warning(f"未找到渠道: {channel_name}")
                return None
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                self.logger.warning(f"未找到店铺: {shop_id} (渠道: {channel_name})")
                return None
                
            account = session.query(Account).filter(
                Account.shop_id == shop.id,
                Account.user_id == user_id
            ).first()
            
            if not account:
                self.logger.warning(f"未找到账户: {user_id} (店铺 ID: {shop_id})")
                return None

            from utils.credential_crypto import (
                is_encrypted,
                maybe_decrypt_from_storage,
                maybe_encrypt_for_storage,
            )

            pwd = account.password
            ck = account.cookies
            if include_secrets:
                plain_pwd = maybe_decrypt_from_storage(pwd)
                plain_ck = maybe_decrypt_from_storage(ck)
                migrated = False
                if plain_pwd and not is_encrypted(pwd):
                    account.password = maybe_encrypt_for_storage(plain_pwd)
                    migrated = True
                if plain_ck and not is_encrypted(ck):
                    account.cookies = maybe_encrypt_for_storage(plain_ck)
                    migrated = True
                if migrated:
                    session.commit()
                pwd = plain_pwd
                ck = plain_ck
            else:
                pwd = None
                ck = None

            return {
                'id': account.id,
                'shop_id': account.shop_id,
                'user_id': account.user_id,
                'username': account.username,
                'password': pwd,
                'cookies': ck,
                'status': account.status
            }
        except SQLAlchemyError as e:
            self.logger.error(f"获取账号失败: {str(e)}")
            return None
        finally:
            session.close()
    
    def update_account_info(self, channel_name: str, shop_id: str, user_id: str, username: Optional[str] = None, password: Optional[str] = None, cookies: Optional[str] = None, status: Optional[int] = None) -> bool:
        """更新账号信息
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            user_id: 用户ID
            username: 登录用户名
            password: 登录密码
            cookies: cookies JSON字符串
            status: 账号状态
        Returns:
            bool: 是否更新成功
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                self.logger.error(f"更新账号失败: 渠道 {channel_name} 不存在")
                return False
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                self.logger.error(f"更新账号失败: 店铺 {shop_id} 不存在于渠道 {channel_name}")
                return False
                
            account = session.query(Account).filter(
                Account.shop_id == shop.id,
                Account.user_id == user_id
            ).first()
            
            if not account:
                self.logger.error(f"更新账号失败: 账号 {user_id} 不存在于店铺 {shop_id}")
                return False
                
            from utils.credential_crypto import maybe_encrypt_for_storage

            # 更新账号信息
            if username is not None:
                account.username = username
            if password is not None:
                account.password = maybe_encrypt_for_storage(password)
            if cookies is not None:
                account.cookies = maybe_encrypt_for_storage(cookies)
            if status is not None:
                account.status = status

            session.commit()
            self.logger.info(f"成功更新账号信息: {username} (用户ID: {user_id})")
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"更新账号信息失败: {str(e)}")
            return False
        finally:
            session.close()
                

    def get_accounts_by_shop(self, channel_name: str, shop_id: str) -> List[Dict[str, Any]]:
        """获取指定店铺下的所有账号
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            
        Returns:
            List[Dict]: 账号列表
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return []
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                return []
                
            accounts = session.query(Account).filter(Account.shop_id == shop.id).all()
            return [
                {
                    'id': account.id,
                    'shop_id': account.shop_id,
                    'user_id': account.user_id,
                    'username': account.username,
                    'password': None,
                    'cookies': None,
                    'status': account.status,
                    'has_password': bool(account.password),
                    'has_cookies': bool(account.cookies),
                }
                for account in accounts
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"获取账号列表失败: {str(e)}")
            return []
        finally:
            session.close()
    
    def update_account_status(self, channel_name: str, shop_id: str, user_id: str, status: int) -> bool:
        """更新账号状态
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            user_id: 用户ID
            status: 状态值 (0-未验证, 1-正常, 2-异常)
            
        Returns:
            bool: 是否更新成功
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return False
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                return False
                
            account = session.query(Account).filter(
                Account.shop_id == shop.id,
                Account.user_id == user_id
            ).first()
            
            if not account:
                return False
                
            account.status = status
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"更新账号状态失败: {str(e)}")
            return False
        finally:
            session.close()
    
    def update_account_cookies(self, channel_name: str, shop_id: str, user_id: str, cookies: str) -> bool:
        """更新账号cookies
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            user_id: 用户ID
            cookies: cookies JSON字符串
            
        Returns:
            bool: 是否更新成功
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return False
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                return False
                
            account = session.query(Account).filter(
                Account.shop_id == shop.id,
                Account.user_id == user_id
            ).first()
            
            if not account:
                return False

            from utils.credential_crypto import maybe_encrypt_for_storage

            account.cookies = maybe_encrypt_for_storage(cookies)
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"更新账号cookies失败: {str(e)}")
            return False
        finally:
            session.close()
    
    def delete_account(self, channel_name: str, shop_id: str, user_id: str) -> bool:
        """删除账号
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            user_id: 用户ID
            
        Returns:
            bool: 是否删除成功
        """
        session = self.get_session()
        try:
            channel = session.query(Channel).filter(Channel.channel_name == channel_name).first()
            if not channel:
                return False
                
            shop = session.query(Shop).filter(
                Shop.channel_id == channel.id,
                Shop.shop_id == shop_id
            ).first()
            
            if not shop:
                return False
                
            account = session.query(Account).filter(
                Account.shop_id == shop.id,
                Account.user_id == user_id
            ).first()
            
            if not account:
                return False
                
            session.delete(account)
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"删除账号失败: {str(e)}")
            return False
        finally:
            session.close()

    # 关键词相关操作
    def add_keyword(self, keyword: str) -> bool:
        """添加关键词
        
        Args:
            keyword: 关键词
            
        Returns:
            bool: 是否添加成功
        """
        session = self.get_session()
        try:
            # 检查关键词是否已存在
            existing = session.query(Keyword).filter(Keyword.keyword == keyword).first()
            if existing:
                self.logger.warning(f"关键词 {keyword} 已存在")
                return False
                
            # 创建新关键词
            keyword_obj = Keyword(keyword=keyword)
            session.add(keyword_obj)
            session.commit()
            self.logger.info(f"成功添加关键词: {keyword}")
            try:
                from utils.audit_log import audit_keyword_change

                audit_keyword_change("keyword_add", keyword)
            except Exception:
                pass
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"添加关键词失败: {str(e)}")
            return False
        finally:
            session.close()
    
    def get_keyword(self, keyword: str) -> Optional[Dict[str, Any]]:
        """获取关键词信息
        
        Args:
            keyword: 关键词
            
        Returns:
            Optional[Dict]: 关键词信息或None
        """
        session = self.get_session()
        try:
            keyword_obj = session.query(Keyword).filter(Keyword.keyword == keyword).first()
            if not keyword_obj:
                return None
                
            return {
                'id': keyword_obj.id,
                'keyword': keyword_obj.keyword
            }
        except SQLAlchemyError as e:
            self.logger.error(f"获取关键词失败: {str(e)}")
            return None
        finally:
            session.close()
    
    def get_all_keywords(self) -> List[Dict[str, Any]]:
        """获取所有关键词
        
        Returns:
            List[Dict]: 关键词列表
        """
        session = self.get_session()
        try:
            keywords = session.query(Keyword).all()
            return [
                {
                    'id': keyword.id,
                    'keyword': keyword.keyword
                }
                for keyword in keywords
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"获取关键词列表失败: {str(e)}")
            return []
        finally:
            session.close()
    
    def update_keyword(self, old_keyword: str, new_keyword: str) -> bool:
        """更新关键词
        
        Args:
            old_keyword: 原关键词
            new_keyword: 新关键词
            
        Returns:
            bool: 是否更新成功
        """
        session = self.get_session()
        try:
            # 检查原关键词是否存在
            keyword_obj = session.query(Keyword).filter(Keyword.keyword == old_keyword).first()
            if not keyword_obj:
                self.logger.warning(f"关键词 {old_keyword} 不存在")
                return False
            
            # 检查新关键词是否已存在（如果不是同一个关键词）
            if old_keyword != new_keyword:
                existing = session.query(Keyword).filter(Keyword.keyword == new_keyword).first()
                if existing:
                    self.logger.warning(f"关键词 {new_keyword} 已存在")
                    return False
                    
            # 更新关键词
            keyword_obj.keyword = new_keyword
            session.commit()
            self.logger.info(f"成功更新关键词: {old_keyword} -> {new_keyword}")
            try:
                from utils.audit_log import audit_keyword_change

                audit_keyword_change(
                    "keyword_update",
                    new_keyword,
                    operator="ui",
                )
            except Exception:
                pass
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"更新关键词失败: {str(e)}")
            return False
        finally:
            session.close()

    def delete_keyword(self, keyword: str) -> bool:
        """删除关键词
        
        Args:
            keyword: 关键词
            
        Returns:
            bool: 是否删除成功
        """
        session = self.get_session()
        try:
            keyword_obj = session.query(Keyword).filter(Keyword.keyword == keyword).first()
            if not keyword_obj:
                self.logger.warning(f"关键词 {keyword} 不存在")
                return False
                
            session.delete(keyword_obj)
            session.commit()
            self.logger.info(f"成功删除关键词: {keyword}")
            try:
                from utils.audit_log import audit_keyword_change

                audit_keyword_change("keyword_delete", keyword)
            except Exception:
                pass
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"删除关键词失败: {str(e)}")
            return False
        finally:
            session.close()

    # -------------------------------------------------------------------------
    def bump_quick_reply_usage(self, quick_reply_id: int) -> None:
        session = self.get_session()
        try:
            r = session.query(QuickReply).filter(QuickReply.id == quick_reply_id).first()
            if r:
                r.usage_count = (r.usage_count or 0) + 1
                session.commit()
        except SQLAlchemyError:
            session.rollback()
        finally:
            session.close()

    def _today_date_str(self) -> str:
        from utils.chat_time import shanghai_naive_now

        return shanghai_naive_now().strftime("%Y-%m-%d")

    def _row_to_refund_apply_dict(self, row: MerchantRefundApplyLog) -> Dict[str, Any]:
        return {
            "id": int(row.id),
            "shop_id": row.shop_id,
            "buyer_uid": row.buyer_uid,
            "order_sn": row.order_sn,
            "card_msg_id": row.card_msg_id,
            "api_success": bool(row.api_success),
            "card_expired": row.card_expired,
            "status": row.status,
            "valid_time_unix": row.valid_time_unix,
            "created_at": row.created_at,
        }

    def get_refund_apply_by_card_msg_id(
        self, shop_id: str, card_msg_id: str
    ) -> Optional[Dict[str, Any]]:
        session = self.get_session()
        try:
            row = (
                session.query(MerchantRefundApplyLog)
                .filter(
                    MerchantRefundApplyLog.shop_id == str(shop_id),
                    MerchantRefundApplyLog.card_msg_id == str(card_msg_id),
                )
                .order_by(desc(MerchantRefundApplyLog.id))
                .first()
            )
            return self._row_to_refund_apply_dict(row) if row else None
        except SQLAlchemyError as e:
            self.logger.error(f"get_refund_apply_by_card_msg_id 失败: {e}")
            return None
        finally:
            session.close()

    def get_latest_refund_apply_for_order(
        self, shop_id: str, order_sn: str
    ) -> Optional[Dict[str, Any]]:
        """按订单号取最近一条代申请记录。"""
        session = self.get_session()
        try:
            row = (
                session.query(MerchantRefundApplyLog)
                .filter(
                    MerchantRefundApplyLog.shop_id == str(shop_id),
                    MerchantRefundApplyLog.order_sn == str(order_sn).strip(),
                )
                .order_by(desc(MerchantRefundApplyLog.id))
                .first()
            )
            return self._row_to_refund_apply_dict(row) if row else None
        except SQLAlchemyError as e:
            self.logger.error(f"get_latest_refund_apply_for_order 失败: {e}")
            return None
        finally:
            session.close()

    def record_merchant_refund_apply(
        self,
        shop_id: str,
        buyer_uid: str,
        order_sn: str,
        *,
        api_success: bool,
        status: Optional[str] = None,
        valid_time_unix: Optional[int] = None,
        card_msg_id: Optional[str] = None,
        after_sales_type: Optional[int] = None,
        refund_amount_fen: Optional[int] = None,
        error_msg: Optional[str] = None,
    ) -> int:
        """写入代申请记录，返回 id。"""
        session = self.get_session()
        try:
            if api_success and status is None:
                status = "pending"
            if not api_success and status is None:
                status = "failed"
            row = MerchantRefundApplyLog(
                shop_id=str(shop_id),
                buyer_uid=str(buyer_uid),
                order_sn=str(order_sn).strip(),
                card_msg_id=str(card_msg_id) if card_msg_id else None,
                api_success=bool(api_success),
                status=status,
                valid_time_unix=int(valid_time_unix) if valid_time_unix else None,
                after_sales_type=after_sales_type,
                refund_amount_fen=refund_amount_fen,
                error_msg=(str(error_msg)[:512] if error_msg else None),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            try:
                from utils.audit_log import audit_refund_card

                audit_refund_card(
                    str(order_sn).strip(),
                    shop_id=str(shop_id),
                    buyer_uid=str(buyer_uid),
                    success=bool(api_success),
                    detail=error_msg or ("pending" if api_success else "failed"),
                )
            except Exception:
                pass
            return int(row.id)
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"record_merchant_refund_apply 失败: {e}")
            return 0
        finally:
            session.close()

    def update_refund_apply_from_card_push(
        self,
        shop_id: str,
        buyer_uid: str,
        order_sn: str,
        *,
        card_msg_id: Optional[str],
        valid_time_unix: Optional[int],
        card_expired: bool,
    ) -> bool:
        """type=19 下行：补全 card_msg_id / valid_time；过期则 status=expired。"""
        session = self.get_session()
        try:
            row = (
                session.query(MerchantRefundApplyLog)
                .filter(
                    MerchantRefundApplyLog.shop_id == str(shop_id),
                    MerchantRefundApplyLog.order_sn == str(order_sn).strip(),
                    MerchantRefundApplyLog.api_success.is_(True),
                )
                .order_by(desc(MerchantRefundApplyLog.id))
                .first()
            )
            if not row:
                row = MerchantRefundApplyLog(
                    shop_id=str(shop_id),
                    buyer_uid=str(buyer_uid),
                    order_sn=str(order_sn).strip(),
                    api_success=True,
                    status="expired" if card_expired else "pending",
                )
                session.add(row)
            if card_msg_id:
                row.card_msg_id = str(card_msg_id)
            if valid_time_unix:
                row.valid_time_unix = int(valid_time_unix)
            row.card_expired = bool(card_expired)
            row.status = "expired" if card_expired else "pending"
            row.outcome_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"update_refund_apply_from_card_push 失败: {e}")
            return False
        finally:
            session.close()

    def mark_refund_apply_expired(
        self,
        shop_id: str,
        order_sn: str,
        *,
        buyer_uid: Optional[str] = None,
        card_msg_id: Optional[str] = None,
    ) -> bool:
        """type=19/90：将订单代申请记录标为 expired。"""
        session = self.get_session()
        try:
            q = session.query(MerchantRefundApplyLog).filter(
                MerchantRefundApplyLog.shop_id == str(shop_id),
            )
            if card_msg_id:
                q = q.filter(MerchantRefundApplyLog.card_msg_id == str(card_msg_id))
            elif order_sn and str(order_sn).strip():
                q = q.filter(MerchantRefundApplyLog.order_sn == str(order_sn).strip())
            else:
                return False
            if buyer_uid:
                q = q.filter(MerchantRefundApplyLog.buyer_uid == str(buyer_uid))
            row = q.order_by(desc(MerchantRefundApplyLog.id)).first()
            if not row:
                return False
            row.status = "expired"
            row.card_expired = True
            row.outcome_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"mark_refund_apply_expired 失败: {e}")
            return False
        finally:
            session.close()

    def update_merchant_refund_apply_outcome(
        self,
        shop_id: str,
        buyer_uid: str,
        order_sn: str,
        *,
        card_expired: bool,
        card_msg_id: Optional[str] = None,
        valid_time_unix: Optional[int] = None,
    ) -> bool:
        """兼容旧调用：转 update_refund_apply_from_card_push。"""
        return self.update_refund_apply_from_card_push(
            shop_id,
            buyer_uid,
            order_sn,
            card_msg_id=card_msg_id,
            valid_time_unix=valid_time_unix,
            card_expired=card_expired,
        )

    def merchant_refund_apply_counts(
        self,
        shop_id: str,
        buyer_uid: str,
        order_sn: str,
        *,
        success_only: bool = True,
    ) -> Dict[str, int]:
        """统计代申请次数：本单累计、今日该买家、今日全店。"""
        session = self.get_session()
        try:
            day = self._today_date_str()
            base = session.query(MerchantRefundApplyLog).filter(
                MerchantRefundApplyLog.shop_id == str(shop_id),
            )
            if success_only:
                base = base.filter(MerchantRefundApplyLog.api_success.is_(True))

            def _day_filter(q):
                return q.filter(
                    func.strftime("%Y-%m-%d", MerchantRefundApplyLog.created_at) == day
                )

            order_cnt = base.filter(
                MerchantRefundApplyLog.order_sn == str(order_sn).strip()
            ).count()
            buyer_today = _day_filter(
                base.filter(MerchantRefundApplyLog.buyer_uid == str(buyer_uid))
            ).count()
            shop_today = _day_filter(base).count()
            return {
                "order_total": int(order_cnt),
                "buyer_today": int(buyer_today),
                "shop_today": int(shop_today),
            }
        except SQLAlchemyError as e:
            self.logger.error(f"merchant_refund_apply_counts 失败: {e}")
            return {"order_total": 0, "buyer_today": 0, "shop_today": 0}
        finally:
            session.close()

    def record_merchant_address_change(
        self,
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
        session = self.get_session()
        try:
            row = MerchantAddressChangeLog(
                shop_id=str(shop_id),
                seller_user_id=str(seller_user_id),
                operator_username=str(operator_username or "")[:128],
                buyer_uid=str(buyer_uid),
                order_sn=str(order_sn).strip(),
                shipping_status=int(shipping_status),
                address_before_summary=(address_before_summary or "")[:512],
                address_after_summary=(address_after_summary or "")[:512],
                parsed_from_message=(parsed_from_message or "")[:4000],
                action=str(action),
                api_success=api_success,
                api_error_msg=(str(api_error_msg)[:512] if api_error_msg else None),
                shipped_override=bool(shipped_override),
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            return int(row.id)
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"record_merchant_address_change 失败: {e}")
            return 0
        finally:
            session.close()

_db_instance = None

def get_db_manager() -> "DatabaseManager":
    global _db_instance
    if _db_instance is None:
        try:
            from config import get_config

            db_path = get_config("db_path", DEFAULT_DB_PATH) or DEFAULT_DB_PATH
        except Exception:
            db_path = DEFAULT_DB_PATH
        _db_instance = DatabaseManager(db_path=db_path)
    return _db_instance

class _LazyDBProxy:
    """与 database.__init__ 的 DI 代理一致，优先使用容器内 DatabaseManager。"""

    def _get_instance(self) -> "DatabaseManager":
        try:
            from core.di_container import container

            if container.is_registered(DatabaseManager):
                return container.get(DatabaseManager)
        except Exception:
            pass
        return get_db_manager()

    def __getattr__(self, name):
        return getattr(self._get_instance(), name)


db_manager = _LazyDBProxy()
