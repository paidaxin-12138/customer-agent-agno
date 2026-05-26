"""
安全配置加载器
从环境变量或配置文件加载敏感信息
"""

import os
import json
from pathlib import Path
from typing import Any, Optional
from dotenv import load_dotenv
from utils.logger_loguru import get_logger

logger = get_logger("SecureConfig")


class SecureConfig:
    """安全配置类"""
    
    def __init__(self, config_path: str = "config.json"):
        """
        初始化配置
        
        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self._config = {}
        self._load_env()
        self._load_config()
    
    def _load_env(self):
        """加载环境变量"""
        env_file = Path(".env")
        if env_file.exists():
            load_dotenv(env_file)
            logger.info(f"已加载环境变量：{env_file}")
        else:
            logger.warning(".env 文件不存在，使用配置文件")
    
    def _load_config(self):
        """加载配置文件"""
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self._config = json.load(f)
            logger.info(f"已加载配置文件：{self.config_path}")
        else:
            logger.warning(f"配置文件不存在：{self.config_path}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（优先从环境变量读取）
        
        Args:
            key: 配置键
            default: 默认值
            
        Returns:
            配置值
        """
        # 优先从环境变量获取
        env_value = os.getenv(key)
        if env_value is not None:
            return env_value
        
        # 从配置文件获取
        return self._config.get(key, default)
    
    def get_nested(self, *keys: str, default: Any = None) -> Any:
        """
        获取嵌套配置值
        
        Args:
            keys: 嵌套键路径
            default: 默认值
            
        Returns:
            配置值
        """
        value = self._config
        for key in keys:
            if isinstance(value, dict):
                value = value.get(key)
            else:
                return default
        
        if value is None:
            return default
        
        return value
    
    def get_secret(self, key: str, required: bool = True) -> Optional[str]:
        """
        获取敏感配置（如 API 密钥）
        
        Args:
            key: 配置键
            required: 是否必需
            
        Returns:
            配置值或 None
        """
        value = os.getenv(key)
        
        if value is None:
            if required:
                logger.error(f"必需的密钥未配置：{key}")
                logger.error("请设置环境变量或在 .env 文件中配置")
                raise ValueError(f"必需的密钥未配置：{key}")
            return None
        
        # 日志中隐藏密钥
        masked = value[:6] + "..." + value[-4:] if len(value) > 10 else "***"
        logger.debug(f"加载密钥：{key} = {masked}")
        
        return value
    
    def get_llm_config(self) -> dict:
        """获取 LLM 配置"""
        return {
            "model_name": self.get("LLM_MODEL_NAME") or self.get_nested("llm", "model_name"),
            "api_key": self.get_secret("LLM_API_KEY", required=False) or self.get_nested("llm", "api_key"),
            "api_base": self.get("LLM_API_BASE") or self.get_nested("llm", "api_base"),
            "max_tokens": int(self.get("LLM_MAX_TOKENS") or self.get_nested("llm", "max_tokens", default=256)),
            "temperature": float(self.get("LLM_TEMPERATURE") or self.get_nested("llm", "temperature", default=0.5)),
        }
    
    def get_embedder_config(self) -> dict:
        """获取 Embedder 配置"""
        return {
            "model_name": self.get("EMBEDDER_MODEL_NAME") or self.get_nested("embedder", "model_name"),
            "api_key": self.get_secret("EMBEDDER_API_KEY", required=False) or self.get_nested("embedder", "api_key"),
            "api_base": self.get("EMBEDDER_API_BASE") or self.get_nested("embedder", "api_base"),
        }


# 全局配置实例
_config: Optional[SecureConfig] = None


def get_config() -> SecureConfig:
    """获取全局配置实例"""
    global _config
    if _config is None:
        _config = SecureConfig()
    return _config


def get_secret(key: str, required: bool = True) -> Optional[str]:
    """获取敏感配置"""
    return get_config().get_secret(key, required)


def get_llm_config() -> dict:
    """获取 LLM 配置"""
    return get_config().get_llm_config()


def get_embedder_config() -> dict:
    """获取 Embedder 配置"""
    return get_config().get_embedder_config()
