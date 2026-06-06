"""敏感配置与健康暴露检查。"""
import pytest

from utils.secret_config import check_health_exposure, check_plaintext_secrets


def test_plaintext_api_key_warning(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("SECRETS_ENV_ONLY", raising=False)
    monkeypatch.setattr(
        "utils.secret_config.config.get",
        lambda key, default=None: "sk-live-secret-key-abcdefghij" if key == "llm.api_key" else default,
    )
    errors, warnings = check_plaintext_secrets()
    assert not errors
    assert any("LLM_API_KEY" in w for w in warnings)


def test_env_override_no_warning(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "from-env")
    monkeypatch.setattr(
        "utils.secret_config.config.get",
        lambda key, default=None: "sk-live-secret-key-abcdefghij" if key == "llm.api_key" else default,
    )
    errors, warnings = check_plaintext_secrets()
    assert not errors
    assert not warnings


def test_secrets_env_only_strict_error(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("SECRETS_ENV_ONLY", "1")
    monkeypatch.setattr(
        "utils.secret_config.config.get",
        lambda key, default=None: "sk-live-secret-key-abcdefghij" if key == "llm.api_key" else default,
    )
    errors, warnings = check_plaintext_secrets()
    assert errors
    assert not warnings


def test_health_exposure_warns_without_token(monkeypatch):
    monkeypatch.delenv("HEALTH_CHECK_TOKEN", raising=False)
    monkeypatch.setattr(
        "utils.secret_config.get_config",
        lambda key, default=None: {
            "production.health_host": "0.0.0.0",
            "production.health_token": "",
        }.get(key, default),
    )
    errors, warnings = check_health_exposure()
    msgs = errors + warnings
    assert any("HEALTH_CHECK_TOKEN" in m for m in msgs)


def test_health_localhost_ok(monkeypatch):
    monkeypatch.delenv("HEALTH_CHECK_TOKEN", raising=False)
    monkeypatch.setattr(
        "utils.secret_config.get_config",
        lambda key, default=None: {
            "production.health_host": "127.0.0.1",
            "production.health_token": "",
        }.get(key, default),
    )
    assert check_health_exposure() == ([], [])
