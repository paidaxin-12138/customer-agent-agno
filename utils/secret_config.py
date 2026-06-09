# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""敏感配置：检测 config.json 明文密钥、健康检查暴露面。"""
from __future__ import annotations

import os
from typing import List, Tuple

from config import config, get_config

_SECRET_ENV_PAIRS: Tuple[Tuple[str, str], ...] = (
    ("llm.api_key", "LLM_API_KEY"),
    ("embedder.api_key", "EMBEDDER_API_KEY"),
    ("pinduoduo_open.client_secret", "PDD_OPEN_CLIENT_SECRET"),
    ("pinduoduo_open.access_token", "PDD_OPEN_ACCESS_TOKEN"),
)

_PLACEHOLDER_MARKERS = (
    "your-api-key",
    "your-client",
    "your-access-token",
    "changeme",
    "placeholder",
    "example",
)


def _looks_like_real_secret(value: str) -> bool:
    v = (value or "").strip()
    if len(v) < 8:
        return False
    low = v.lower()
    return not any(marker in low for marker in _PLACEHOLDER_MARKERS)


def secrets_env_only_enabled() -> bool:
    return os.getenv("SECRETS_ENV_ONLY", "").strip().lower() in ("1", "true", "yes")


def check_plaintext_secrets() -> Tuple[List[str], List[str]]:
    """
    若密钥只写在 config.json、未用环境变量覆盖，返回 (errors, warnings)。
  SECRETS_ENV_ONLY=1 时明文密钥视为 error。
    """
    errors: List[str] = []
    warnings: List[str] = []
    strict = secrets_env_only_enabled()

    for cfg_key, env_key in _SECRET_ENV_PAIRS:
        file_val = str(config.get(cfg_key) or "").strip()
        if not file_val or not _looks_like_real_secret(file_val):
            continue
        if os.getenv(env_key, "").strip():
            continue
        msg = (
            f"{cfg_key} 仍写在 config.json 中，运行时虽可用但存在泄露风险；"
            f"请改用环境变量 {env_key} 并从文件中删除"
        )
        if strict:
            errors.append(msg)
        else:
            warnings.append(msg)
    return errors, warnings


def check_health_exposure(*, strict: bool = False) -> tuple[List[str], List[str]]:
    """非本机绑定健康检查时，要求配置 HEALTH_CHECK_TOKEN。"""
    errors: List[str] = []
    warnings: List[str] = []
    host = str(get_config("production.health_host") or "127.0.0.1").strip().lower()
    token = (
        os.getenv("HEALTH_CHECK_TOKEN", "").strip()
        or str(get_config("production.health_token") or "").strip()
    )
    if host in ("127.0.0.1", "::1", "localhost") or token:
        return errors, warnings
    msg = (
        "production.health_host 已绑定非本机地址且未设置 HEALTH_CHECK_TOKEN；"
        "/ready 与 /metrics 将对同网段匿名开放，请设置 Token 或改回 127.0.0.1"
    )
    if strict:
        errors.append(msg)
    else:
        warnings.append(msg)
    return errors, warnings
