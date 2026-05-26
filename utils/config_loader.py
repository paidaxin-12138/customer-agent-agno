"""
安全的配置加载器 - 支持环境变量和 .env 文件
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional
from dotenv import load_dotenv
from utils.logger_loguru import get_logger

logger = get_logger("ConfigLoader")

class SecureConfigLoader:
    """安全配置加载器"""
    
    def __init__(self, env_file: str = ".env"):
        """
        初始化配置加载器
        
        Args:
            env_file: .env 文件路径
        """
        self.env_file = env_file
        self._load_env_file()
        
    def _load_env_file(self):
        """加载 .env 文件"""
        env_path = Path(self.env_file)
        
        if env_path.exists():
            load_dotenv(env_path)
            logger.info(f"已加载环境变量：{self.env_file}")
        else:
            logger.warning(f".env 文件不存在：{self.env_file}")
            logger.warning("将从 config.json 加载配置（不安全）")
    
    def get(self, key: str, default: Any = None, required: bool = False) -> Any:
        """
        获取配置值（优先从环境变量读取）
        
        Args:
            key: 配置键
            default: 默认值
            required: 是否必需
            
        Returns:
            配置值
            
        Raises:
            ValueError: 必需的配置未提供
        """
        # 尝试从环境变量获取
        value = os.getenv(key)
        
        if value is not None:
            # 自动类型转换
            return self._auto_convert(value, default)
        
        # 环境变量未设置，使用默认值
        if default is not None:
            return default
        
        if required:
            raise ValueError(f"必需的配置项未提供：{key}")
        
        return None
    
    def get_secret(self, key: str, required: bool = True) -> Optional[str]:
        """
        获取敏感配置（如 API 密钥）
        
        Args:
            key: 配置键
            required: 是否必需
            
        Returns:
            配置值或 None
            
        Raises:
            ValueError: 必需的密钥未提供
        """
        value = os.getenv(key)
        
        if value is None and required:
            raise ValueError(
                f"敏感的密钥未配置：{key}\n"
                f"请设置环境变量或在 .env 文件中配置"
            )
        
        if value:
            # 日志中隐藏密钥
            masked = value[:6] + "..." + value[-4:] if len(value) > 10 else "***"
            logger.debug(f"加载密钥：{key} = {masked}")
        
        return value
    
    def _auto_convert(self, value: str, default: Any) -> Any:
        """自动类型转换"""
        if default is None:
            return value
        
        if isinstance(default, bool):
            return value.lower() in ('true', '1', 'yes', 'on')
        
        if isinstance(default, int):
            try:
                return int(value)
            except ValueError:
                return default
        
        if isinstance(default, float):
            try:
                return float(value)
            except ValueError:
                return default
        
        return value
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有环境变量"""
        return dict(os.environ)


# 便捷函数
_config_loader = None

def get_loader() -> SecureConfigLoader:
    """获取配置加载器单例"""
    global _config_loader
    if _config_loader is None:
        _config_loader = SecureConfigLoader()
    return _config_loader

def get_secure(key: str, default: Any = None, required: bool = False) -> Any:
    """获取安全配置"""
    return get_loader().get(key, default, required)

def get_secret(key: str, required: bool = True) -> Optional[str]:
    """获取敏感配置"""
    return get_loader().get_secret(key, required)
