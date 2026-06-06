"""主窗口布局用 macOS 风格字体与间距（全局主题见 ``ui.theme``）。"""
from __future__ import annotations

from PyQt6.QtGui import QFont


class MacOSFonts:
    FONT_TINY = 9
    FONT_CAPTION = 10
    FONT_SUBHEAD = 11
    FONT_BODY = 12
    FONT_CALL_OUT = 13
    FONT_HEADLINE = 15
    FONT_TITLE3 = 16
    FONT_TITLE2 = 18
    FONT_TITLE1 = 20
    FONT_LARGE_TITLE = 24

    @staticmethod
    def get_font(size=FONT_BODY, weight="normal"):
        font_names = [
            ".SF NS Text",
            "SF Pro Text",
            "Helvetica Neue",
            "PingFang SC",
            "Microsoft YaHei",
        ]
        for font_name in font_names:
            font = QFont(font_name, size)
            if font.exactMatch():
                break
        else:
            font = QFont("Microsoft YaHei", size)

        weight_map = {
            "light": QFont.Weight.Light,
            "regular": QFont.Weight.Normal,
            "medium": QFont.Weight.Medium,
            "semibold": QFont.Weight.DemiBold,
            "bold": QFont.Weight.Bold,
        }
        font.setWeight(weight_map.get(weight, QFont.Weight.Normal))
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        return font


class MacOSSpacing:
    SPACING_XS = 4
    SPACING_S = 8
    SPACING_M = 12
    SPACING_L = 16
    SPACING_XL = 20
    SPACING_XXL = 24
    SPACING_XXXL = 32

    MARGIN_WINDOW = 0
    MARGIN_SIDEBAR = 8
    MARGIN_CONTENT = 20
    MARGIN_CARD = 16
