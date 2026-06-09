# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""macOS 无边框窗口：统一深色顶栏，消除系统标题栏白条。"""
from __future__ import annotations

import sys
from typing import Any

from utils.logger_loguru import get_logger

_log = get_logger("macos_window_chrome")

from ui import apple_ui_tokens as _T

_CHROME_BG = _T.BG_PRIMARY
_TITLEBAR_STYLESHEET = f"""
TitleBar, TitleBarBase {{
    background-color: {_CHROME_BG};
    border: none;
}}
QLabel#titleLabel {{
    color: #FFFFFF;
    background: transparent;
}}
"""


def apply_dark_titlebar_chrome(window: Any) -> bool:
    """
    将 NSWindow 设为深色透明标题栏，并与 Fluent 自绘 titleBar 背景一致。
    需在 winId 可用后调用（如 showEvent / QTimer.singleShot）。
    """
    if sys.platform != "darwin":
        return False
    try:
        win_id = window.winId()
        if not win_id:
            return False

        from qframelesswindow.utils.mac_utils import getNSWindow
        import Cocoa

        ns_window = getNSWindow(win_id)
        if ns_window is None:
            return False

        appearance = Cocoa.NSAppearance.appearanceNamed_(
            Cocoa.NSAppearanceNameDarkAqua
        )
        if appearance is not None:
            ns_window.setAppearance_(appearance)

        ns_window.setStyleMask_(
            ns_window.styleMask() | Cocoa.NSFullSizeContentViewWindowMask
        )
        ns_window.setTitlebarAppearsTransparent_(True)
        ns_window.setTitleVisibility_(Cocoa.NSWindowTitleHidden)
        ns_window.setMovableByWindowBackground_(False)

        r, g, b = 19 / 255.0, 19 / 255.0, 21 / 255.0
        ns_window.setBackgroundColor_(
            Cocoa.NSColor.colorWithRed_green_blue_alpha_(r, g, b, 1.0)
        )

        title_bar = getattr(window, "titleBar", None)
        if title_bar is not None:
            title_bar.setStyleSheet(_TITLEBAR_STYLESHEET)

        update_frameless = getattr(window, "updateFrameless", None)
        if callable(update_frameless):
            update_frameless()

        return True
    except Exception as e:
        _log.debug("apply_dark_titlebar_chrome: {}", e)
        return False


def use_unified_dark_titlebar(window: Any) -> None:
    """
    关闭 macOS 系统红绿灯，改用自绘标题栏按钮，避免顶部双层白条。
    在 MainWindow.__init__ 末尾、视图加载前调用。
    """
    if sys.platform != "darwin":
        return
    try:
        set_mica = getattr(window, "setMicaEffectEnabled", None)
        if callable(set_mica):
            set_mica(False)
        set_bg = getattr(window, "setCustomBackgroundColor", None)
        if callable(set_bg):
            set_bg(_CHROME_BG, _CHROME_BG)

        from PyQt6.QtCore import Qt

        safe_area = getattr(Qt.WidgetAttribute, "WA_ContentsMarginsRespectsSafeArea", None)
        if safe_area is not None:
            window.setAttribute(safe_area, False)

        set_system_btns = getattr(window, "setSystemTitleBarButtonVisible", None)
        if callable(set_system_btns):
            set_system_btns(False)

        title_bar = getattr(window, "titleBar", None)
        if title_bar is not None:
            for name in ("closeBtn", "minBtn", "maxBtn"):
                btn = getattr(title_bar, name, None)
                if btn is not None:
                    btn.show()
            title_bar.setStyleSheet(_TITLEBAR_STYLESHEET)
    except Exception as e:
        _log.debug("use_unified_dark_titlebar: {}", e)
