# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from config import ChatConfig, ConfigModel, warn_unknown_config_keys, config_base


def test_chat_config_coerces_numeric_fields():
    cfg = ChatConfig.model_validate(
        {"message_consumer_max_concurrent": "16", "ws_message_max_concurrent": 16}
    )
    assert cfg.message_consumer_max_concurrent == 16


def test_warn_unknown_chat_keys_does_not_raise():
    data = {
        **{k: v for k, v in config_base.items() if k != "chat"},
        "chat": {**config_base["chat"], "queue_degrade_enable": True},
    }
    warn_unknown_config_keys(data, config_base)


def test_config_model_accepts_merged_defaults():
    model = ConfigModel(**config_base)
    assert model.chat.message_consumer_max_concurrent == 16
    assert model.pinduoduo_open.enabled is True
