# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""加载 dark_theme.qss 并注入色板占位符。"""
from __future__ import annotations

from pathlib import Path

from ui import apple_ui_tokens as T

_QSS_PATH = Path(__file__).resolve().parent / "dark_theme.qss"


def load_dark_theme_qss() -> str:
    raw = _QSS_PATH.read_text(encoding="utf-8")
    mapping = {
        "{{BG_PRIMARY}}": T.BG_PRIMARY,
        "{{BG_SECONDARY}}": T.BG_SECONDARY,
        "{{BG_TERTIARY}}": T.BG_TERTIARY,
        "{{BG_ELEVATED}}": T.BG_ELEVATED,
        "{{BG_HOVER}}": T.BG_HOVER,
        "{{GLASS_PANEL}}": T.GLASS_PANEL,
        "{{GLASS_PANEL_SOLID}}": T.GLASS_PANEL_SOLID,
        "{{TEXT_PRIMARY}}": T.TEXT_PRIMARY,
        "{{TEXT_SECONDARY}}": T.TEXT_SECONDARY,
        "{{TEXT_MUTED}}": T.TEXT_MUTED,
        "{{ACCENT}}": T.ACCENT,
        "{{ACCENT_SECONDARY}}": T.ACCENT_SECONDARY,
        "{{ACCENT_HOVER}}": T.ACCENT_HOVER,
        "{{ACCENT_SURFACE}}": T.ACCENT_SURFACE,
        "{{ACCENT_SURFACE_HOVER}}": T.ACCENT_SURFACE_HOVER,
        "{{ACCENT_SURFACE_BORDER}}": T.ACCENT_SURFACE_BORDER,
        "{{ACCENT_FILL}}": T.ACCENT_FILL,
        "{{ACCENT_FILL_HOVER}}": T.ACCENT_FILL_HOVER,
        "{{SUCCESS}}": T.SUCCESS,
        "{{ERROR}}": T.ERROR,
        "{{BORDER}}": T.BORDER,
        "{{BORDER_LIGHT}}": T.BORDER_LIGHT,
        "{{BORDER_PANEL}}": T.BORDER_PANEL,
        "{{GRID_LINE}}": T.GRID_LINE,
        "{{FONT_FAMILY}}": T.FONT_FAMILY_CSS,
        "{{RADIUS_SM}}": T.RADIUS_SM,
        "{{RADIUS_MD}}": T.RADIUS_MD,
        "{{RADIUS_LG}}": T.RADIUS_LG,
        "{{RADIUS_PILL}}": T.RADIUS_PILL,
    }
    for key, val in mapping.items():
        raw = raw.replace(key, val)
    return raw
