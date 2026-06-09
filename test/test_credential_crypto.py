# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from utils.credential_crypto import decrypt_field, encrypt_field, is_encrypted


def test_encrypt_roundtrip():
    plain = "secret-cookie-value"
    enc = encrypt_field(plain)
    assert enc is not None
    assert is_encrypted(enc)
    assert decrypt_field(enc) == plain


def test_plaintext_passthrough():
    assert decrypt_field("plain") == "plain"
