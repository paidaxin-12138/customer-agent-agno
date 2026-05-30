import pytest

from utils.config_startup import validate_startup_config


def test_validate_startup_detects_missing_api_key(monkeypatch):
    monkeypatch.setattr(
        "utils.config_startup.get_config",
        lambda key, default=None: "" if key == "llm.api_key" else default,
    )
    monkeypatch.setattr(
        "utils.config_startup.config.get",
        lambda key, default=None: False if key == "pinduoduo_open.enabled" else default,
    )
    issues = validate_startup_config()
    assert any("llm.api_key" in i for i in issues)


def test_validate_startup_strict_raises(monkeypatch):
    monkeypatch.setattr(
        "utils.config_startup.get_config",
        lambda key, default=None: "" if key == "llm.api_key" else default,
    )
    monkeypatch.setattr(
        "utils.config_startup.config.get",
        lambda key, default=None: False if key == "pinduoduo_open.enabled" else default,
    )
    from config import ConfigError

    with pytest.raises(ConfigError):
        validate_startup_config(strict=True)
