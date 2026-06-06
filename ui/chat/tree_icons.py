"""会话树展开箭头（SVG data URI，供 QSS branch 使用）。"""
from __future__ import annotations

import base64


def _svg_data_uri(svg: str) -> str:
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"url(data:image/svg+xml;base64,{encoded})"


# 24×24，线宽 2.2，深色背景下清晰可见
CHEVRON_RIGHT_URI = _svg_data_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
    '<polyline points="9,7 15,12 9,17" fill="none" stroke="#B8C0D4" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)

CHEVRON_DOWN_URI = _svg_data_uri(
    '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">'
    '<polyline points="7,10 12,15 17,10" fill="none" stroke="#B8C0D4" '
    'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
)
