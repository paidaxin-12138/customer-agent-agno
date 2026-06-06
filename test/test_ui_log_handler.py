"""UILogHandler 生命周期：卸载后 loguru 不再回调。"""
from __future__ import annotations

import pytest

loguru = pytest.importorskip("loguru")
from loguru import logger

from utils.logger_loguru import UILogHandler


def test_ui_log_handler_uninstall_removes_sink(qapp):
    handler = UILogHandler()
    handler.install()
    handler_id = handler.handler_id
    assert handler_id is not None
    handler.uninstall()
    assert handler.handler_id is None
    with pytest.raises(ValueError):
        logger.remove(handler_id)


def test_ui_log_handler_install_is_idempotent(qapp):
    handler = UILogHandler()
    handler.install()
    first = handler.handler_id
    handler.install()
    assert handler.handler_id == first
    handler.uninstall()
