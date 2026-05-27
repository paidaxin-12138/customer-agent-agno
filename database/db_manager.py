import os
import json
from datetime import datetime
from sqlalchemy import create_engine, func, or_, desc
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from typing import List, Dict, Any, Optional, Tuple, Union
from utils.chat_time import now_for_db
from utils.logger_loguru import get_logger
from database.models import Base, Channel, Shop, Account, Keyword, ChatSession, ChatMessage, QuickReply

class DatabaseManager:
    """数据库管理类，提供数据库操作的封装"""
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super(DatabaseManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: str = './temp/customer.db'):
        """初始化数据库连接
        
        Args:
            db_path: 数据库文件路径
        """
        if self._initialized:
            return
            
        # 确保数据库目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # 创建数据库引擎
        self.engine = create_engine(f'sqlite:///{db_path}')
        self.Session = sessionmaker(bind=self.engine)
        
        self.logger = get_logger()

        # 创建表结构
        Base.metadata.create_all(self.engine)
        self._migrate_chat_session_memory_columns()
        self._migrate_ops_schema()
        self._migrate_utc_timestamps_to_shanghai()
        
        self._initialized = True    
        # 初始化数据库
        self.init_db()

    def _migrate_chat_session_memory_columns(self) -> None:
        """为已有 SQLite 库补齐三层记忆字段。"""
        import sqlite3

        path = self.engine.url.database
        if not path:
            return
        conn = sqlite3.connect(path)
        try:
            cur = conn.execute("PRAGMA table_info(chat_sessions)")
            cols = {row[1] for row in cur.fetchall()}
            alters = []
            if "task_state_json" not in cols:
                alters.append("ALTER TABLE chat_sessions ADD COLUMN task_state_json TEXT")
            if "long_term_summary" not in cols:
                alters.append("ALTER TABLE chat_sessions ADD COLUMN long_term_summary TEXT")
            if "memory_summary_through_id" not in cols:
                alters.append(
                    "ALTER TABLE chat_sessions ADD COLUMN memory_summary_through_id INTEGER DEFAULT 0"
                )
            for sql in alters:
                conn.execute(sql)
            if alters:
                conn.commit()
                self.logger.info(f"chat_sessions 记忆字段迁移: {len(alters)} 列")
        except Exception as e:
            self.logger.warning(f"chat_sessions 记忆字段迁移失败: {e}")
        finally:
            conn.close()

    def _migrate_ops_schema(self) -> None:
        """运营看板表列补齐（旧库可能缺 session_key 等）。"""
        try:
            from database.ops_migrate import migrate_ops_schema

            path = self.engine.url.database
            if path:
                migrate_ops_schema(path)
        except Exception as e:
            if hasattr(self, "logger"):
                self.logger.warning(f"ops 表迁移跳过: {e}")

    def _migrate_utc_timestamps_to_shanghai(self) -> None:
        """历史库 naive UTC 时间 +8h 转为上海墙钟（仅执行一次）。"""
        import sqlite3

        path = self.engine.url.database
        if not path:
            return
        conn = sqlite3.connect(path)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT)"
            )
            row = conn.execute(
                "SELECT value FROM app_meta WHERE key='timestamps_shanghai_v1'"
            ).fetchone()
            if row and str(row[0]) == "1":
                return
            patches = [
                ("chat_sessions", ("updated_at", "created_at")),
                ("chat_messages", ("created_at", "read_at")),
                ("ops_sessions", ("updated_at",)),
                ("ops_traces", ("created_at",)),
                ("ops_knowledge_revisions", ("created_at",)),
                ("ops_low_confidence", ("updated_at",)),
                ("ops_tickets", ("created_at", "updated_at")),
                ("ops_eval_runs", ("created_at",)),
                ("ops_cost_logs", ("created_at",)),
                ("ops_security_audits", ("created_at",)),
            ]
            n = 0
            for table, cols in patches:
                for col in cols:
                    try:
                        cur = conn.execute(
                            f"UPDATE {table} SET {col} = datetime({col}, '+8 hours') "
                            f"WHERE {col} IS NOT NULL"
                        )
                        n += cur.rowcount
                    except sqlite3.OperationalError:
                        pass
            conn.execute(
                "INSERT OR REPLACE INTO app_meta (key, value) VALUES "
                "('timestamps_shanghai_v1', '1')"
            )
            conn.commit()
            if n > 0:
                self.logger.info(f"时间字段 UTC→上海迁移: 约 {n} 行")
        except Exception as e:
            self.logger.warning(f"时间迁移失败: {e}")
        finally:
            conn.close()

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
            
            # 创建新账号
            account = Account(
                shop_id=shop.id,
                user_id=user_id,
                username=username,
                password=password,
                cookies=cookies,
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
    
    def get_account(self, channel_name: str, shop_id: str,user_id: str) -> Optional[Dict[str, Any]]:
        """获取账号信息
        
        Args:
            channel_name: 渠道名称
            shop_id: 店铺ID
            user_id: 用户ID
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
                
            return {
                'id': account.id,
                'shop_id': account.shop_id,
                'user_id': account.user_id,
                'username': account.username,
                'password': account.password,
                'cookies': account.cookies,
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
                
            # 更新账号信息
            if username is not None:
                account.username = username
            if password is not None:
                account.password = password
            if cookies is not None:
                account.cookies = cookies
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
                    'password': account.password,
                    'cookies': account.cookies,
                    'status': account.status
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
                
            account.cookies = cookies
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
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"删除关键词失败: {str(e)}")
            return False
        finally:
            session.close()

    # -------------------------------------------------------------------------
    # 实时聊天：账号 / 会话 / 消息 / 快捷回复
    # -------------------------------------------------------------------------

    def list_all_accounts_for_chat(self) -> List[Dict[str, Any]]:
        """所有接待账号（含店铺、渠道），供实时聊天侧栏使用。"""
        session = self.get_session()
        try:
            rows = (
                session.query(Account, Shop, Channel)
                .join(Shop, Account.shop_id == Shop.id)
                .join(Channel, Shop.channel_id == Channel.id)
                .all()
            )
            out: List[Dict[str, Any]] = []
            for acc, shop, ch in rows:
                out.append(
                    {
                        "id": acc.id,
                        "channel_name": ch.channel_name,
                        "platform_shop_id": shop.shop_id,
                        "shop_name": shop.shop_name,
                        "shop_logo": shop.shop_logo,
                        "seller_user_id": acc.user_id,
                        "username": acc.username,
                        "status": acc.status,
                    }
                )
            return out
        except SQLAlchemyError as e:
            self.logger.error(f"list_all_accounts_for_chat 失败: {e}")
            return []
        finally:
            session.close()

    def get_account_row_by_id(self, account_id: int) -> Optional[Dict[str, Any]]:
        session = self.get_session()
        try:
            row = (
                session.query(Account, Shop, Channel)
                .join(Shop, Account.shop_id == Shop.id)
                .join(Channel, Shop.channel_id == Channel.id)
                .filter(Account.id == account_id)
                .first()
            )
            if not row:
                return None
            acc, shop, ch = row
            return {
                "id": acc.id,
                "channel_name": ch.channel_name,
                "platform_shop_id": shop.shop_id,
                "shop_name": shop.shop_name,
                "shop_logo": shop.shop_logo,
                "seller_user_id": acc.user_id,
                "username": acc.username,
                "status": acc.status,
                "cookies": acc.cookies,
            }
        finally:
            session.close()

    def get_chat_sessions(
        self, account_id: Optional[int] = None, status: str = "active"
    ) -> List[Dict[str, Any]]:
        session = self.get_session()
        try:
            q = session.query(ChatSession).filter(ChatSession.status == status)
            if account_id is not None:
                q = q.filter(ChatSession.account_id == account_id)
            q = q.order_by(desc(ChatSession.updated_at))
            return [
                {
                    "id": s.id,
                    "account_id": s.account_id,
                    "account_name": s.account_name,
                    "platform_shop_id": s.platform_shop_id,
                    "buyer_uid": s.buyer_uid,
                    "buyer_nickname": s.buyer_nickname,
                    "avatar_url": s.avatar_url,
                    "status": s.status,
                    "ai_mode": bool(s.ai_mode),
                    "last_message": s.last_message,
                    "last_message_time": s.last_message_time,
                    "unread_count": s.unread_count or 0,
                    "updated_at": s.updated_at,
                }
                for s in q.all()
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_sessions 失败: {e}")
            return []
        finally:
            session.close()

    def get_chat_session_by_buyer(
        self, account_id: int, buyer_uid: str, status: str = "active"
    ) -> Optional[Dict[str, Any]]:
        for s in self.get_chat_sessions(account_id, status):
            if str(s.get("buyer_uid")) == str(buyer_uid):
                return s
        return None

    def get_chat_session_by_id(self, session_id: int) -> Optional[Dict[str, Any]]:
        """按主键读取会话，避免界面树节点上缓存的 ai_mode 等字段过期。"""
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return None
            return {
                "id": s.id,
                "account_id": s.account_id,
                "account_name": s.account_name,
                "platform_shop_id": s.platform_shop_id,
                "buyer_uid": s.buyer_uid,
                "buyer_nickname": s.buyer_nickname,
                "avatar_url": s.avatar_url,
                "status": s.status,
                "ai_mode": bool(s.ai_mode),
                "last_message": s.last_message,
                "last_message_time": s.last_message_time,
                "unread_count": s.unread_count or 0,
                "updated_at": s.updated_at,
            }
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_session_by_id 失败: {e}")
            return None
        finally:
            session.close()

    def get_or_create_chat_session(
        self,
        account_id: int,
        platform_shop_id: str,
        account_name: str,
        buyer_uid: str,
        buyer_nickname: str,
        avatar_url: Optional[str] = None,
    ) -> int:
        session = self.get_session()
        try:
            s = (
                session.query(ChatSession)
                .filter(
                    ChatSession.account_id == account_id,
                    ChatSession.buyer_uid == buyer_uid,
                )
                .first()
            )
            now = now_for_db()
            if s:
                s.buyer_nickname = buyer_nickname or s.buyer_nickname
                if avatar_url:
                    s.avatar_url = avatar_url
                if s.status == "closed":
                    s.status = "active"
                s.updated_at = now
                session.commit()
                return s.id
            s = ChatSession(
                account_id=account_id,
                account_name=account_name,
                platform_shop_id=platform_shop_id,
                buyer_uid=buyer_uid,
                buyer_nickname=buyer_nickname or "买家",
                avatar_url=avatar_url,
                status="active",
                ai_mode=True,
                unread_count=0,
                created_at=now,
                updated_at=now,
            )
            session.add(s)
            session.commit()
            session.refresh(s)
            return s.id
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"get_or_create_chat_session 失败: {e}")
            raise
        finally:
            session.close()

    def update_session_last_message(
        self, session_id: int, message: str, t: Optional[datetime] = None
    ) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            s.last_message = message
            s.last_message_time = t or now_for_db()
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"update_session_last_message 失败: {e}")
            return False
        finally:
            session.close()

    def close_chat_session(self, session_id: int) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            s.status = "closed"
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"close_chat_session 失败: {e}")
            return False
        finally:
            session.close()

    def close_idle_chat_sessions(self, idle_seconds: int = 300) -> List[Tuple[int, str, str]]:
        """
        买家最后一条消息超过 idle_seconds 的 active 会话标为 closed（已解决）。

        跳过：当前在「实时聊天」中打开的会话；从未收到买家消息的会话。

        Returns:
            [(account_id, buyer_uid, account_key), ...]
        """
        from datetime import timedelta

        from database.chat_persist import is_active_chat
        from utils.chat_time import shanghai_naive_now

        now = shanghai_naive_now()
        cutoff = now - timedelta(seconds=int(idle_seconds))
        closed: List[Tuple[int, str, str]] = []
        session = self.get_session()
        try:
            rows = (
                session.query(ChatSession)
                .filter(ChatSession.status == "active")
                .all()
            )
            for cs in rows:
                if is_active_chat(int(cs.account_id), str(cs.buyer_uid)):
                    continue
                last_customer = (
                    session.query(func.max(ChatMessage.sent_at))
                    .filter(
                        ChatMessage.session_id == cs.id,
                        ChatMessage.sender_type == "customer",
                    )
                    .scalar()
                )
                if last_customer is None:
                    continue
                if last_customer > cutoff:
                    continue
                cs.status = "closed"
                cs.updated_at = now_for_db()
                acc = (
                    session.query(Account, Shop, Channel)
                    .join(Shop, Account.shop_id == Shop.id)
                    .join(Channel, Shop.channel_id == Channel.id)
                    .filter(Account.id == cs.account_id)
                    .first()
                )
                account_key = ""
                if acc:
                    _acc, _shop, _ch = acc
                    account_key = (
                        f"{_ch.channel_name}:{_shop.shop_id}:{_acc.username}"
                    )
                closed.append((int(cs.account_id), str(cs.buyer_uid), account_key))
            if closed:
                session.commit()
            return closed
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"close_idle_chat_sessions 失败: {e}")
            return []
        finally:
            session.close()

    def set_session_ai_mode(self, session_id: int, ai_mode: bool) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            s.ai_mode = ai_mode
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"set_session_ai_mode 失败: {e}")
            return False
        finally:
            session.close()

    def get_session_memory(self, session_id: int) -> Dict[str, Any]:
        """读取会话三层记忆持久化字段。"""
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return {}
            return {
                "task_state_json": s.task_state_json,
                "long_term_summary": s.long_term_summary,
                "memory_summary_through_id": int(s.memory_summary_through_id or 0),
            }
        except SQLAlchemyError as e:
            self.logger.error(f"get_session_memory 失败: {e}")
            return {}
        finally:
            session.close()

    def update_session_memory(
        self,
        session_id: int,
        *,
        task_state_json: Optional[str] = None,
        long_term_summary: Optional[str] = None,
        memory_summary_through_id: Optional[int] = None,
    ) -> bool:
        session = self.get_session()
        try:
            s = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if not s:
                return False
            if task_state_json is not None:
                s.task_state_json = task_state_json
            if long_term_summary is not None:
                s.long_term_summary = long_term_summary
            if memory_summary_through_id is not None:
                s.memory_summary_through_id = memory_summary_through_id
            s.updated_at = now_for_db()
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"update_session_memory 失败: {e}")
            return False
        finally:
            session.close()

    def add_chat_message(
        self,
        session_id: int,
        account_id: int,
        sender_type: str,
        content: str,
        message_id: Optional[str] = None,
        content_type: str = "text",
        image_url: Optional[str] = None,
        increment_unread: bool = False,
        sent_at: Optional[datetime] = None,
    ) -> Optional[int]:
        session = self.get_session()
        try:
            if message_id:
                ex = (
                    session.query(ChatMessage)
                    .filter(
                        ChatMessage.session_id == session_id,
                        ChatMessage.message_id == message_id,
                    )
                    .first()
                )
                if ex:
                    return ex.id
            now = now_for_db()
            st = sent_at or now
            msg = ChatMessage(
                session_id=session_id,
                account_id=account_id,
                message_id=message_id,
                sender_type=sender_type,
                content=content,
                content_type=content_type,
                image_url=image_url,
                is_read=sender_type != "customer",
                read_at=now if sender_type != "customer" else None,
                sent_at=st,
                created_at=now,
            )
            session.add(msg)
            cs = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if cs:
                preview = content if len(content) < 500 else content[:500] + "…"
                cs.last_message = preview
                cs.last_message_time = st
                cs.updated_at = now
                if increment_unread and sender_type == "customer":
                    cs.unread_count = (cs.unread_count or 0) + 1
            session.commit()
            session.refresh(msg)
            return msg.id
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"add_chat_message 失败: {e}")
            return None
        finally:
            session.close()

    def get_chat_messages(
        self, session_id: int, limit: int = 200, offset: int = 0
    ) -> List[Dict[str, Any]]:
        session = self.get_session()
        try:
            rows = (
                session.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
                .offset(offset)
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": m.id,
                    "session_id": m.session_id,
                    "message_id": m.message_id,
                    "account_id": m.account_id,
                    "sender_type": m.sender_type,
                    "content": m.content,
                    "content_type": m.content_type,
                    "image_url": m.image_url,
                    "is_read": bool(m.is_read),
                    "read_at": m.read_at,
                    "sent_at": m.sent_at,
                    "created_at": m.created_at,
                }
                for m in rows
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_messages 失败: {e}")
            return []
        finally:
            session.close()

    def get_chat_messages_recent(
        self, session_id: int, limit: int = 24
    ) -> List[Dict[str, Any]]:
        """最近 N 条消息（按时间正序），用于 AI 多轮上下文。"""
        session = self.get_session()
        try:
            rows = (
                session.query(ChatMessage)
                .filter(ChatMessage.session_id == session_id)
                .order_by(ChatMessage.id.desc())
                .limit(limit)
                .all()
            )
            rows = list(reversed(rows))
            return [
                {
                    "id": m.id,
                    "session_id": m.session_id,
                    "message_id": m.message_id,
                    "account_id": m.account_id,
                    "sender_type": m.sender_type,
                    "content": m.content,
                    "content_type": m.content_type,
                    "image_url": m.image_url,
                    "is_read": bool(m.is_read),
                    "read_at": m.read_at,
                    "sent_at": m.sent_at,
                    "created_at": m.created_at,
                }
                for m in rows
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_chat_messages_recent 失败: {e}")
            return []
        finally:
            session.close()

    def mark_chat_messages_read(self, session_id: int) -> bool:
        session = self.get_session()
        try:
            now = now_for_db()
            session.query(ChatMessage).filter(
                ChatMessage.session_id == session_id,
                ChatMessage.sender_type == "customer",
                ChatMessage.is_read == False,
            ).update({ChatMessage.is_read: True, ChatMessage.read_at: now}, synchronize_session=False)
            cs = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            if cs:
                cs.unread_count = 0
                cs.updated_at = now
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"mark_chat_messages_read 失败: {e}")
            return False
        finally:
            session.close()

    def get_unread_count_for_session(self, session_id: int) -> int:
        session = self.get_session()
        try:
            cs = session.query(ChatSession).filter(ChatSession.id == session_id).first()
            return int(cs.unread_count or 0) if cs else 0
        finally:
            session.close()

    def get_total_unread_chat(self) -> int:
        session = self.get_session()
        try:
            v = (
                session.query(func.coalesce(func.sum(ChatSession.unread_count), 0))
                .filter(ChatSession.status == "active")
                .scalar()
            )
            return int(v or 0)
        except SQLAlchemyError as e:
            self.logger.error(f"get_total_unread_chat 失败: {e}")
            return 0
        finally:
            session.close()

    def get_quick_replies(
        self, account_id: Optional[int] = None, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        session = self.get_session()
        try:
            q = session.query(QuickReply)
            if account_id is not None:
                q = q.filter(or_(QuickReply.account_id.is_(None), QuickReply.account_id == account_id))
            else:
                q = q.filter(QuickReply.account_id.is_(None))
            if category:
                q = q.filter(QuickReply.category == category)
            q = q.order_by(QuickReply.usage_count.desc(), QuickReply.id.asc())
            return [
                {
                    "id": r.id,
                    "account_id": r.account_id,
                    "category": r.category,
                    "title": r.title,
                    "content": r.content,
                    "usage_count": r.usage_count,
                }
                for r in q.all()
            ]
        except SQLAlchemyError as e:
            self.logger.error(f"get_quick_replies 失败: {e}")
            return []
        finally:
            session.close()

    def add_quick_reply(
        self,
        content: str,
        account_id: Optional[int] = None,
        category: Optional[str] = None,
        title: Optional[str] = None,
    ) -> bool:
        session = self.get_session()
        try:
            session.add(
                QuickReply(
                    account_id=account_id,
                    category=category,
                    title=title,
                    content=content,
                )
            )
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"add_quick_reply 失败: {e}")
            return False
        finally:
            session.close()

    def delete_chat_session_by_buyer(self, account_id: int, buyer_uid: str) -> bool:
        """删除该买家在接待账号下的会话及全部消息（买家结束聊天后清理）。"""
        session = self.get_session()
        try:
            cs = (
                session.query(ChatSession)
                .filter(
                    ChatSession.account_id == account_id,
                    ChatSession.buyer_uid == str(buyer_uid),
                )
                .first()
            )
            if not cs:
                return False
            session.delete(cs)
            session.commit()
            return True
        except SQLAlchemyError as e:
            session.rollback()
            self.logger.error(f"delete_chat_session_by_buyer 失败: {e}")
            return False
        finally:
            session.close()

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

_db_instance = None

def get_db_manager() -> "DatabaseManager":
    global _db_instance
    if _db_instance is None:
        try:
            from config import get_config

            db_path = get_config("db_path", "./temp/customer.db") or "./temp/customer.db"
        except Exception:
            db_path = "./temp/customer.db"
        _db_instance = DatabaseManager(db_path=db_path)
    return _db_instance

class _LazyDBProxy:
    def __getattr__(self, name):
        return getattr(get_db_manager(), name)

db_manager = _LazyDBProxy()
