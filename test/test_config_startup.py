# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
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
    errors, warnings = validate_startup_config()
    assert any("llm.api_key" in i for i in errors)


def test_validate_startup_strict_raises_on_api_key_only(monkeypatch):
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


def test_pinduoduo_open_missing_is_warning_not_strict_error(monkeypatch):
    monkeypatch.setattr(
        "utils.config_startup.get_config",
        lambda key, default=None: "sk-test" if key == "llm.api_key" else default,
    )
    monkeypatch.setattr(
        "utils.config_startup.config.get",
        lambda key, default=None: True if key == "pinduoduo_open.enabled" else default,
    )
    errors, warnings = validate_startup_config(strict=True)
    assert not errors
    assert any("pinduoduo_open" in w for w in warnings)
