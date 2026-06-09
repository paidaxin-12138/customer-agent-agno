# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""
配置文件管理模块
获取config.json中的配置，提供配置访问接口
提供类型安全、线程安全的配置管理系统
支持配置验证
"""
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Dict, Optional, Union
from contextlib import contextmanager

from utils.logger_loguru import get_logger

from config_schema import (
    ChatConfig,
    ConfigModel,
    config_base,
    merge_missing_config_defaults,
    warn_unknown_config_keys,
)


def _load_dotenv_early() -> None:
    """在读取 config.json 之前加载 .env，供 get_config 环境变量覆盖。"""
    try:
        from dotenv import load_dotenv

        env_path = Path(__file__).resolve().parent / ".env"
        if env_path.is_file():
            load_dotenv(env_path, override=False)
    except Exception as e:
        get_logger("config").debug(".env 早期加载跳过: {}", e)


_load_dotenv_early()




class ConfigError(Exception):
    """配置相关错误的基类"""
    pass


class ConfigFileNotFoundError(ConfigError):
    """配置文件未找到错误"""
    pass


class ConfigParseError(ConfigError):
    """配置文件解析错误"""
    pass


class ConfigValidationError(ConfigError):
    """配置验证错误"""
    pass


class Config:
    """
    线程安全的配置管理器

    特性：
    - 类型安全的配置访问
    - 配置验证
    - 线程安全
    - 异常处理完善
    """

    def __init__(
        self,
        config_path: Union[str, Path] = 'config.json',
        auto_create: bool = True
    ):
        """
        初始化配置类

        Args:
            config_path: 配置文件路径
            auto_create: 是否自动创建默认配置文件
        """
        self.config_path = self._resolve_config_path(config_path)
        self.auto_create = auto_create

        # 线程安全锁
        self._lock = threading.RLock()

        # 配置缓存
        self._config: Optional[Dict[str, Any]] = None
        self._validated_config: Optional[ConfigModel] = None

        # 加载配置
        self.reload()

    @staticmethod
    def _resolve_config_path(config_path: Union[str, Path]) -> Path:
        """
        解析配置文件路径。
        - 开发环境：保持相对路径行为（项目根目录下 config.json）
        - 打包环境：相对路径改为用户可写目录，避免 .app 只读导致闪退
        """
        path = Path(config_path)
        if path.is_absolute():
            return path

        if getattr(sys, "frozen", False):
            from utils.runtime_path import get_user_data_dir

            user_dir = get_user_data_dir()
            user_dir.mkdir(parents=True, exist_ok=True)
            return user_dir / path.name

        return path

    def _load_config(self) -> Dict[str, Any]:
        """从文件加载配置"""
        if not self.config_path.exists():
            raise ConfigFileNotFoundError(f"配置文件不存在: {self.config_path}")

        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                raw_config = json.load(f)

            merged, merged_changed = merge_missing_config_defaults(raw_config, config_base)
            if merged_changed:
                try:
                    with open(self.config_path, 'w', encoding='utf-8') as wf:
                        json.dump(merged, wf, ensure_ascii=False, indent=4)
                    print(f"已补充默认配置项（含开放平台占位）至 {self.config_path}")
                except OSError as werr:
                    print(f"写入补充配置失败（仍使用内存合并结果）: {werr}")

            config_data = merged
            warn_unknown_config_keys(config_data, config_base)

            # 验证配置格式（chat / pinduoduo_open 强类型 + 顶层结构）
            validated_config = ConfigModel(**config_data)
            self._validated_config = validated_config

            return config_data
        except json.JSONDecodeError as e:
            raise ConfigParseError(f"配置文件格式错误: {e}")
        except Exception as e:
            raise ConfigValidationError(f"配置验证失败: {e}")

    def _create_default_config_file(self) -> None:
        """创建默认配置文件"""
        try:
            # 创建目录（如果不存在）
            self.config_path.parent.mkdir(parents=True, exist_ok=True)

            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(config_base, f, ensure_ascii=False, indent=4)

            print(f"已创建默认配置文件：{self.config_path}")
        except Exception as e:
            raise ConfigError(f"创建配置文件失败: {e}")

    def reload(self) -> Dict[str, Any]:
        """重新加载配置文件"""
        with self._lock:
            try:
                self._config = self._load_config()
                return self._config
            except ConfigFileNotFoundError:
                if self.auto_create:
                    self._create_default_config_file()
                    self._config = config_base.copy()
                    self._validated_config = ConfigModel(**config_base)
                    return self._config
                else:
                    raise
            except (ConfigParseError, ConfigValidationError) as e:
                if self._config is not None:
                    get_logger("config").error(
                        f"配置重载失败，继续使用上次有效配置: {e}"
                    )
                    return self._config
                raise ConfigError(f"配置文件无效且无可用的缓存配置: {e}") from e
            except Exception as e:
                if self._config is not None:
                    get_logger("config").error(
                        f"配置重载异常，继续使用上次有效配置: {e}"
                    )
                    return self._config
                raise ConfigError(f"加载配置失败: {e}") from e

    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置项，支持点号分隔的嵌套访问

        Args:
            key: 配置键名，支持嵌套访问如 'llm.api_key'
            default: 默认值

        Returns:
            配置值
        """
        with self._lock:
            if self._config is None:
                return default

            try:
                keys = key.split('.')
                value = self._config

                for k in keys:
                    if isinstance(value, dict) and k in value:
                        value = value[k]
                    else:
                        return default

                return value
            except Exception:
                return default

    def get_model(self) -> ConfigModel:
        """获取验证后的配置模型"""
        with self._lock:
            return self._validated_config or ConfigModel()

    def __getitem__(self, key: str) -> Any:
        """支持使用字典方式访问配置"""
        return self.get(key)

    def __contains__(self, key: str) -> bool:
        """支持使用 in 操作符检查配置项"""
        return self.get(key) is not None

    def set(self, key: str, value: Any, save: bool = True) -> Any:
        """
        设置配置项

        Args:
            key: 配置项键名
            value: 配置项值
            save: 是否立即保存到文件，默认为True

        Returns:
            设置的值
        """
        with self._lock:
            if self._config is None:
                self._config = config_base.copy()

            # 解析嵌套键
            keys = key.split('.')
            current = self._config

            # 导航到目标位置
            for k in keys[:-1]:
                if k not in current:
                    current[k] = {}
                current = current[k]

            # 设置值
            current[keys[-1]] = value

            # 重新验证配置
            try:
                self._validated_config = ConfigModel(**self._config)
                if save:
                    self.save()
            except Exception as e:
                raise ConfigValidationError(f"设置配置项失败: {e}")

            return value

    def update(self, config_dict: Dict[str, Any], save: bool = False) -> Dict[str, Any]:
        """
        批量更新配置

        Args:
            config_dict: 包含多个配置项的字典
            save: 是否立即保存到文件，默认为False

        Returns:
            更新后的完整配置
        """
        with self._lock:
            if self._config is None:
                self._config = config_base.copy()

            # 深度合并配置
            merged_config = self._deep_merge(self._config, config_dict)

            try:
                self._validated_config = ConfigModel(**merged_config)
                self._config = merged_config
                if save:
                    self.save()
                return self._config
            except Exception as e:
                raise ConfigValidationError(f"批量更新配置失败: {e}")

    def save(self) -> bool:
        """将当前配置保存到文件"""
        with self._lock:
            if self._config is None:
                raise ConfigError("没有可保存的配置")

            try:
                # 创建目录（如果不存在）
                self.config_path.parent.mkdir(parents=True, exist_ok=True)

                with open(self.config_path, 'w', encoding='utf-8') as f:
                    json.dump(self._config, f, ensure_ascii=False, indent=4)

                return True
            except Exception as e:
                print(f"保存配置文件失败: {e}")
                return False

    def _deep_merge(self, base: Dict[str, Any], update: Dict[str, Any]) -> Dict[str, Any]:
        """深度合并字典"""
        result = base.copy()

        for key, value in update.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result

    @contextmanager
    def atomic_update(self):
        """原子性更新配置的上下文管理器"""
        original_config = self._config.copy() if self._config else None
        try:
            yield self
            self.save()
        except Exception:
            # 回滚到原始配置
            if original_config:
                self._config = original_config
                try:
                    self._validated_config = ConfigModel(**original_config)
                except Exception as e:
                    get_logger("config").warning(f"atomic_update 回滚后配置校验失败: {e}")
            raise

# 创建全局配置实例
config = Config()


# ==============================
# 便捷函数
# ==============================

_CONFIG_ENV_ALIASES = {
    "llm.api_key": "LLM_API_KEY",
    "llm.api_base": "LLM_API_BASE",
    "llm.model_name": "LLM_MODEL_NAME",
    "embedder.api_key": "EMBEDDER_API_KEY",
    "embedder.api_base": "EMBEDDER_API_BASE",
    "pinduoduo_open.client_id": "PDD_OPEN_CLIENT_ID",
    "pinduoduo_open.client_secret": "PDD_OPEN_CLIENT_SECRET",
    "pinduoduo_open.access_token": "PDD_OPEN_ACCESS_TOKEN",
    "production.health_token": "HEALTH_CHECK_TOKEN",
}


def get_config(key: str, default: Any = None) -> Any:
    """全局便捷函数：获取配置项（优先从环境变量读取）"""
    env_name = _CONFIG_ENV_ALIASES.get(key, key.replace(".", "_").upper())
    env_value = os.getenv(env_name)
    if env_value is None and env_name != key:
        env_value = os.getenv(key)
    if env_value is not None:
        return env_value

    return config.get(key, default)


def set_config(key: str, value: Any, save: bool = False) -> Any:
    """全局便捷函数：设置配置项"""
    return config.set(key, value, save)


def reload_config() -> Dict[str, Any]:
    """全局便捷函数：重新加载配置"""
    return config.reload()


def save_config() -> bool:
    """全局便捷函数：保存配置"""
    return config.save()


def update_config(config_dict: Dict[str, Any], save: bool = False) -> Dict[str, Any]:
    """全局便捷函数：批量更新配置"""
    return config.update(config_dict, save)


def get_validated_config() -> ConfigModel:
    """全局便捷函数：获取验证后的配置模型"""
    return config.get_model()


# 向后兼容：旧代码 from config import ChatConfig / config_base 等
__all__ = [
    "ChatConfig",
    "Config",
    "ConfigError",
    "ConfigFileNotFoundError",
    "ConfigModel",
    "ConfigParseError",
    "ConfigValidationError",
    "config",
    "config_base",
    "get_config",
    "get_validated_config",
    "merge_missing_config_defaults",
    "reload_config",
    "save_config",
    "set_config",
    "update_config",
    "warn_unknown_config_keys",
]
