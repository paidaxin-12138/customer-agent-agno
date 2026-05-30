from utils.credential_crypto import decrypt_field, encrypt_field, is_encrypted


def test_encrypt_roundtrip():
    plain = "secret-cookie-value"
    enc = encrypt_field(plain)
    assert enc is not None
    assert is_encrypted(enc)
    assert decrypt_field(enc) == plain


def test_plaintext_passthrough():
    assert decrypt_field("plain") == "plain"
