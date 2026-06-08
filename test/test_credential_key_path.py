"""凭据密钥文件路径与旧路径迁移。"""
import pytest

import utils.credential_crypto as cc


def test_key_file_path_uses_runtime_user_data_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "utils.runtime_path.get_user_data_dir",
        lambda: tmp_path / "user-data",
    )
    path = cc._key_file_path()
    assert path == tmp_path / "user-data" / ".credential_key"
    assert path.parent.is_dir()


def test_legacy_key_migration(monkeypatch, tmp_path):
    new_base = tmp_path / "user-data"
    legacy_key = tmp_path / "legacy" / ".credential_key"
    legacy_key.parent.mkdir(parents=True)
    seed = b"x" * 32
    legacy_key.write_bytes(seed)

    monkeypatch.setattr("utils.runtime_path.get_user_data_dir", lambda: new_base)
    monkeypatch.setattr(
        "utils.credential_crypto._legacy_key_file_path", lambda: legacy_key
    )
    monkeypatch.setattr("utils.credential_crypto._try_keyring_get", lambda: None)
    monkeypatch.setenv("AGENT_CREDENTIAL_KEY", "")
    cc._fernet = None
    cc._fernet_unavailable = False

    material = cc._load_or_create_key_material()
    assert material == seed
    assert (new_base / ".credential_key").read_bytes() == seed
