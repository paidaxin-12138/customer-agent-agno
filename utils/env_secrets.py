# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""读写项目根目录 .env 中的敏感配置（与 config.get_config 环境变量名对齐）。"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, Optional

from utils.logger_loguru import get_logger
from utils.private_paths import ensure_private_file

_logger = get_logger("EnvSecrets")

_ENV_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")


def _parse_env_value(raw: str) -> str:
    val = (raw or "").strip()
    if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
        inner = val[1:-1]
        if val[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return val


def _format_env_value(val: str) -> str:
    if any(c in val for c in " \t#\"\n\r'\\"):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return val


def env_file_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".env"


def read_env_file() -> Dict[str, str]:
    path = env_file_path()
    if not path.is_file():
        return {}
    out: Dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _ENV_LINE_RE.match(line)
        if not m:
            continue
        key, val = m.group(1), _parse_env_value(m.group(2))
        out[key] = val
    return out


def write_env_file(updates: Dict[str, Optional[str]]) -> None:
    """合并写入 .env；值为 None 或空字符串时删除对应键。"""
    path = env_file_path()
    existing_lines: list[str] = []
    if path.is_file():
        existing_lines = path.read_text(encoding="utf-8").splitlines()

    current = read_env_file()
    for key, val in updates.items():
        if val is None or str(val).strip() == "":
            current.pop(key, None)
        else:
            current[key] = str(val).strip()

    preserved: list[str] = []
    seen: set[str] = set()
    for raw in existing_lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            preserved.append(raw)
            continue
        m = _ENV_LINE_RE.match(stripped)
        if not m:
            preserved.append(raw)
            continue
        key = m.group(1)
        if key in current:
            preserved.append(f"{key}={_format_env_value(current[key])}")
            seen.add(key)
        elif key in updates:
            continue
        else:
            preserved.append(raw)
            seen.add(key)

    for key, val in sorted(current.items()):
        if key not in seen:
            preserved.append(f"{key}={_format_env_value(val)}")

    if not preserved:
        preserved = [
            "# Customer-Agent 敏感配置（勿提交 Git）",
            "",
        ]
        for key, val in sorted(current.items()):
            preserved.append(f"{key}={_format_env_value(val)}")

    text = "\n".join(preserved).rstrip() + "\n"
    path.write_text(text, encoding="utf-8")
    ensure_private_file(path)
    _logger.info("已更新 .env（{} 项）", len(current))


def effective_secret(config_key: str, ui_value: str = "") -> str:
    """UI 输入优先，否则 get_config（含 .env）。"""
    ui = (ui_value or "").strip()
    if ui:
        return ui
    try:
        from config import get_config

        return str(get_config(config_key) or "").strip()
    except Exception:
        return ""


def secret_configured(config_key: str) -> bool:
    return bool(effective_secret(config_key, ""))


def persist_settings_secrets(
    *,
    llm: Dict[str, str],
    embedder: Dict[str, str],
    pinduoduo_open: Optional[Dict[str, str]] = None,
) -> None:
    """将设置页中的密钥写入 .env；空字段表示保留 .env 原值。"""
    updates: Dict[str, Optional[str]] = {}

    def _set(env_key: str, ui_val: str, cfg_key: str) -> None:
        v = (ui_val or "").strip()
        if v:
            updates[env_key] = v
        elif secret_configured(cfg_key):
            pass
        else:
            updates[env_key] = None

    _set("LLM_API_KEY", llm.get("api_key", ""), "llm.api_key")
    if (llm.get("api_base") or "").strip():
        updates["LLM_API_BASE"] = llm["api_base"].strip()
    if (llm.get("model_name") or "").strip():
        updates["LLM_MODEL_NAME"] = llm["model_name"].strip()

    _set("EMBEDDER_API_KEY", embedder.get("api_key", ""), "embedder.api_key")
    if (embedder.get("api_base") or "").strip():
        updates["EMBEDDER_API_BASE"] = embedder["api_base"].strip()
    if (embedder.get("model_name") or "").strip():
        updates["EMBEDDER_MODEL_NAME"] = embedder["model_name"].strip()

    if pinduoduo_open is not None:
        po = pinduoduo_open
        if (po.get("client_id") or "").strip():
            updates["PDD_OPEN_CLIENT_ID"] = po["client_id"].strip()
        if (po.get("client_secret") or "").strip():
            updates["PDD_OPEN_CLIENT_SECRET"] = po["client_secret"].strip()
        if (po.get("access_token") or "").strip():
            updates["PDD_OPEN_ACCESS_TOKEN"] = po["access_token"].strip()

    write_env_file(updates)

    for env_key, val in updates.items():
        if val:
            os.environ[env_key] = val


def strip_secrets_for_json(llm: dict, embedder: dict, pinduoduo_open: dict) -> tuple:
    """config.json 不落明文密钥。"""
    llm_out = dict(llm)
    emb_out = dict(embedder)
    po_out = dict(pinduoduo_open)
    llm_out["api_key"] = ""
    emb_out["api_key"] = ""
    po_out["client_secret"] = ""
    po_out["access_token"] = ""
    return llm_out, emb_out, po_out
