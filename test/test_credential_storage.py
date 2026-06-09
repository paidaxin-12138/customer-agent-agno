# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""账号 Cookie 写入加密与读取解密一致性。"""

import os

import pytest

import database.db_manager as dm_module
from database.db_manager import DatabaseManager
from database.models import Account
from utils.credential_crypto import is_encrypted, maybe_decrypt_from_storage


@pytest.fixture
def cred_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_CREDENTIAL_KEY", "test-credential-key-for-pytest")
    DatabaseManager._instance = None
    path = str(tmp_path / "credential_storage_test.db")
    db = DatabaseManager(db_path=path)
    dm_module._db_instance = db
    db.add_shop("pinduoduo", "shop-001", "测试店", "")
    db.add_account(
        "pinduoduo",
        "shop-001",
        "uid-001",
        "testuser",
        "pass",
        cookies='{"session":"plain-at-create"}',
    )
    yield db
    dm_module._db_instance = None
    DatabaseManager._instance = None


def _raw_cookies_from_db(db: DatabaseManager, username: str) -> str | None:
    session = db.get_session()
    try:
        acc = session.query(Account).filter(Account.username == username).first()
        return None if acc is None else acc.cookies
    finally:
        session.close()


def test_update_account_cookies_stores_encrypted(cred_db):
    plain = '{"session":"refreshed-cookie-json"}'
    ok = cred_db.update_account_cookies("pinduoduo", "shop-001", "uid-001", plain)
    assert ok is True

    raw = _raw_cookies_from_db(cred_db, "testuser")
    assert raw is not None
    assert is_encrypted(raw)
    assert maybe_decrypt_from_storage(raw) == plain


def test_get_account_row_by_id_returns_decrypted_cookies(cred_db):
    plain = '{"token":"read-path-test"}'
    cred_db.update_account_cookies("pinduoduo", "shop-001", "uid-001", plain)

    row = cred_db.get_account_row_by_id(
        cred_db.get_account("pinduoduo", "shop-001", "uid-001")["id"]
    )
    assert row is not None
    assert row["cookies"] == plain


def test_get_account_include_secrets_decrypts_after_cookie_update(cred_db):
    plain = '{"token":"get-account-test"}'
    cred_db.update_account_cookies("pinduoduo", "shop-001", "uid-001", plain)

    acc = cred_db.get_account("pinduoduo", "shop-001", "uid-001", include_secrets=True)
    assert acc is not None
    assert acc["cookies"] == plain
