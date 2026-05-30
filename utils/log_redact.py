"""日志脱敏：键名匹配 + 正则（手机号、身份证、地址片段等）。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Union

# 键名（小写子串匹配）
_SENSITIVE_KEY_SUBSTRINGS = (
    "password",
    "passwd",
    "cookie",
    "token",
    "secret",
    "sign",
    "authorization",
    "api_key",
    "apikey",
    "access_key",
    "session",
    "credential",
    "mobile",
    "phone",
    "receiver",
    "id_card",
    "idcard",
    "bank",
    "card_no",
)

# 值内正则（命中则整段替换）
_VALUE_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b1[3-9]\d{9}\b"),  # 大陆手机号
    re.compile(r"\b\d{17}[\dXx]\b"),  # 18 位身份证
    re.compile(r"\b\d{6}-\d{15,24}\b"),  # 拼多多订单号
    re.compile(
        r"(?i)(?:bearer\s+)[a-z0-9._\-]{8,}",
    ),
    re.compile(
        r"(?i)(?:enc:v1:)[A-Za-z0-9_\-=]{16,}",
    ),
    re.compile(
        r"(?i)[a-z0-9]{32,}",  # 长 hex/密钥状字符串（保守，仅 debug 用）
    ),
]

_REDACTED = "***"


def _key_is_sensitive(key: str) -> bool:
    k = key.lower()
    return any(s in k for s in _SENSITIVE_KEY_SUBSTRINGS)


def redact_string_value(text: str, *, aggressive: bool = False) -> str:
    if not text or not isinstance(text, str):
        return text
    out = text
    for pat in _VALUE_PATTERNS[:4]:  # 始终：手机/身份证/订单/bearer/enc
        out = pat.sub(_REDACTED, out)
    if aggressive:
        for pat in _VALUE_PATTERNS[4:]:
            out = pat.sub(_REDACTED, out)
    return out


def redact_log_payload(
    payload: Any,
    *,
    aggressive: bool = False,
    max_depth: int = 8,
) -> Any:
    """递归脱敏 dict/list/str，供 HTTP/WS 调试日志使用。"""
    return _redact_any(payload, aggressive=aggressive, depth=0, max_depth=max_depth)


def _redact_any(
    value: Any,
    *,
    aggressive: bool,
    depth: int,
    max_depth: int,
) -> Any:
    if depth > max_depth:
        return _REDACTED
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            if _key_is_sensitive(str(k)):
                out[k] = _REDACTED
            else:
                out[k] = _redact_any(v, aggressive=aggressive, depth=depth + 1, max_depth=max_depth)
        return out
    if isinstance(value, list):
        return [
            _redact_any(v, aggressive=aggressive, depth=depth + 1, max_depth=max_depth)
            for v in value[:50]
        ]
    if isinstance(value, str):
        if len(value) > 2000:
            value = value[:2000] + "…"
        return redact_string_value(value, aggressive=aggressive)
    return value
