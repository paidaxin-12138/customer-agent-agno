"""
账号密码 / Cookie 字段级加密（Fernet）。
明文历史数据在读取时自动迁移为 enc: 前缀密文。
密钥：环境变量 AGENT_CREDENTIAL_KEY（推荐）或用户目录下 .credential_key。
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Optional

from utils.logger_loguru import get_logger

_logger = get_logger("CredentialCrypto")

_ENC_PREFIX = "enc:v1:"
_KEYRING_SERVICE = "AgentCustomer"
_KEYRING_USER = "credential_master_key"
_fernet = None
_fernet_unavailable = False


def _ensure_private_file(path: Path) -> None:
    """强制密钥文件仅属主可读写（0o600）。"""
    try:
        if path.exists():
            os.chmod(path, 0o600)
        parent = path.parent
        if parent.exists():
            os.chmod(parent, 0o700)
    except OSError as e:
        _logger.warning("无法设置密钥路径权限 {}: {}", path, e)


def _try_keyring_get() -> Optional[bytes]:
    try:
        import keyring
    except ImportError:
        return None
    try:
        raw = keyring.get_password(_KEYRING_SERVICE, _KEYRING_USER)
        if raw and raw.strip():
            return hashlib.sha256(raw.strip().encode("utf-8")).digest()
    except Exception as e:
        _logger.debug("keyring 读取失败: {}", e)
    return None


def _try_keyring_set(seed_hex: str) -> bool:
    try:
        import keyring
    except ImportError:
        return False
    try:
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USER, seed_hex)
        return True
    except Exception as e:
        _logger.debug("keyring 写入失败: {}", e)
        return False


def _key_file_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home())) / "AgentCustomer"
    else:
        base = Path.home() / "Library" / "Application Support" / "AgentCustomer"
    base.mkdir(parents=True, exist_ok=True)
    return base / ".credential_key"


def _load_or_create_key_material() -> bytes:
    env_key = (os.getenv("AGENT_CREDENTIAL_KEY") or "").strip()
    if env_key:
        return hashlib.sha256(env_key.encode("utf-8")).digest()

    from_keyring = _try_keyring_get()
    if from_keyring is not None:
        return from_keyring

    path = _key_file_path()
    _ensure_private_file(path)
    if path.exists():
        raw = path.read_bytes()
        if len(raw) >= 32:
            return raw[:32]

    seed = os.urandom(32)
    seed_hex = seed.hex()
    if _try_keyring_set(seed_hex):
        _logger.info("凭据主密钥已存入系统钥匙串（{}）", _KEYRING_SERVICE)
        return seed
    try:
        path.write_bytes(seed)
        _ensure_private_file(path)
        _logger.info("凭据主密钥已写入 {}（权限 600）", path)
    except OSError as e:
        _logger.warning("无法写入本地密钥文件 {}: {}", path, e)
    return seed


def _get_fernet():
    global _fernet, _fernet_unavailable
    if _fernet is not None:
        return _fernet
    if _fernet_unavailable:
        return None
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        _fernet_unavailable = True
        _logger.warning("未安装 cryptography，凭据将以明文存储（请 uv add cryptography）")
        return None

    key_material = _load_or_create_key_material()
    fernet_key = base64.urlsafe_b64encode(key_material)
    _fernet = Fernet(fernet_key)
    return _fernet


def encrypt_field(plain: Optional[str]) -> Optional[str]:
    if plain is None or plain == "":
        return plain
    if isinstance(plain, str) and plain.startswith(_ENC_PREFIX):
        return plain
    f = _get_fernet()
    if f is None:
        return plain
    token = f.encrypt(plain.encode("utf-8")).decode("ascii")
    return f"{_ENC_PREFIX}{token}"


def decrypt_field(stored: Optional[str]) -> Optional[str]:
    if stored is None or stored == "":
        return stored
    if not isinstance(stored, str) or not stored.startswith(_ENC_PREFIX):
        return stored
    f = _get_fernet()
    if f is None:
        _logger.error("无法解密凭据：缺少 cryptography 或 AGENT_CREDENTIAL_KEY 不匹配")
        return None
    try:
        token = stored[len(_ENC_PREFIX) :].encode("ascii")
        return f.decrypt(token).decode("utf-8")
    except Exception as e:
        _logger.error("凭据解密失败: {}", e)
        return None


def maybe_encrypt_for_storage(value: Optional[str]) -> Optional[str]:
    return encrypt_field(value)


def maybe_decrypt_from_storage(value: Optional[str]) -> Optional[str]:
    return decrypt_field(value)


def is_encrypted(value: Optional[str]) -> bool:
    return isinstance(value, str) and value.startswith(_ENC_PREFIX)
