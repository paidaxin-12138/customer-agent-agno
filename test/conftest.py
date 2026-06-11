# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""PyQt 测试共用 fixture。"""

import os

import pytest

os.environ.setdefault("CHAT_MESSAGE_BUFFER_DISABLE", "1")


@pytest.fixture(scope="session")
def qapp():
    from PyQt6.QtWidgets import QApplication
    import sys

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


def _clear_qt_process_singletons() -> None:
    try:
        import ui.conversation_hub as hub_mod

        hub_mod._conversation_hub = None
    except Exception:
        pass
    try:
        from utils.chat_image_cache import ChatImageCache

        ChatImageCache._instance = None
    except Exception:
        pass
    try:
        import core.human_assist_bus as hab_mod

        hab_mod._BUS = None
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_qt_process_singletons():
    """用例前后清理进程级 Qt 单例，降低全量套件中 UI 测试顺序敏感。"""
    _clear_qt_process_singletons()
    yield
    _clear_qt_process_singletons()


_FLUENT_LABEL_NAMES = (
    "SubtitleLabel",
    "TitleLabel",
    "BodyLabel",
    "CaptionLabel",
    "StrongBodyLabel",
    "LargeTitleLabel",
)


@pytest.fixture(autouse=True)
def _stub_qfluent_labels(monkeypatch):
    """qfluentwidgets 标签会挂接 QConfig；全量套件后部 C++ 对象可能已销毁。"""
    try:
        from PyQt6.QtWidgets import QLabel
    except ImportError:
        yield
        return

    import sys

    def _label(text="", parent=None, *args, **kwargs):
        return QLabel(text or "", parent)

    for name in _FLUENT_LABEL_NAMES:
        monkeypatch.setattr(f"qfluentwidgets.{name}", _label, raising=False)

    for mod_name, mod in list(sys.modules.items()):
        if not mod_name.startswith("ui.") or mod is None:
            continue
        for name in _FLUENT_LABEL_NAMES:
            if hasattr(mod, name):
                monkeypatch.setattr(mod, name, _label, raising=False)

    yield
