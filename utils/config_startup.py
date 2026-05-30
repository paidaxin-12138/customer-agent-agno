"""
应用启动时配置健康检查（告警为主，避免无头/脚本场景硬退出）。
"""
from __future__ import annotations

import os
from typing import List

from config import config, get_config
from utils.logger_loguru import get_logger

_logger = get_logger("ConfigStartup")


def validate_startup_config(*, strict: bool = False) -> List[str]:
    """
    检查关键配置是否可用。

    Args:
        strict: True 时若存在 error 级问题则抛出 ConfigError

    Returns:
        人类可读的问题列表（空表示无 error 级问题）
    """
    issues: List[str] = []

    api_key = (get_config("llm.api_key") or "").strip()
    if not api_key:
        issues.append(
            "llm.api_key 未配置（可设置环境变量 LLM_API_KEY）；AI 自动回复将不可用"
        )

    api_base = (get_config("llm.api_base") or "").strip()
    if api_key and not api_base:
        issues.append("llm.api_base 未配置，部分 OpenAI 兼容网关需要填写")

    model_name = (get_config("llm.model_name") or "").strip()
    if api_key and not model_name:
        issues.append("llm.model_name 未配置")

    if bool(get_config("pinduoduo_open.enabled", True)):
        po = config.get("pinduoduo_open") or {}
        if isinstance(po, dict):
            if not str(po.get("client_id") or "").strip():
                issues.append(
                    "pinduoduo_open.client_id 未配置，物流查询等开放平台能力不可用"
                )
            if not str(po.get("client_secret") or "").strip():
                issues.append("pinduoduo_open.client_secret 未配置")

    db_path = (get_config("db_path") or "").strip()
    if not db_path:
        issues.append("db_path 未配置，将使用默认 ./temp/customer.db")

    if strict and issues:
        from config import ConfigError

        raise ConfigError("启动配置检查未通过:\n- " + "\n- ".join(issues))

    return issues


def log_startup_config_issues(*, strict: bool = False) -> List[str]:
    """执行检查并写入日志；返回问题列表。"""
    strict = strict or os.getenv("STRICT_CONFIG", "").strip() in ("1", "true", "yes")
    issues = validate_startup_config(strict=strict)
    for msg in issues:
        _logger.warning(msg)
    if not issues:
        _logger.info("启动配置检查通过（关键项已填写或已显式关闭）")
    return issues
