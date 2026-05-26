"""
实时聊天气泡内 HTML：段落 <p>、URL 分段、图片白名单 + 后缀判定、非 URL 块半角化。
样式可通过 ChatBubbleHtmlOptions 覆盖；边框/链接默认 currentColor 以随文字色变化。
"""
from __future__ import annotations

import html as html_module
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urlparse

# 前瞻修剪句末标点：URL 本体不含尾随 .,;: !（其后须为空白、行尾或尖括号）
_URL_RE = re.compile(
    r"https?://[^\s<>]+?(?=(?:[.,;:!]+(?=\s|$|[<>]))|(?=\s|$|[<>]))",
    re.IGNORECASE,
)

_PARA_SPLIT_RE = re.compile(r"\n{2,}")


@dataclass(frozen=True)
class ChatBubbleHtmlOptions:
    """聊天气泡 HTML 可调参数；用 dataclasses.replace(opts, img_max_width=\"...\") 覆盖。"""

    line_height: str = "1.78"
    letter_spacing: str = "0.06em"
    word_spacing: str = "0.1em"
    inner_padding: str = "8px 0 12px 0"
    paragraph_margin_bottom: str = "0.85em"
    img_max_width: str = "min(280px,92vw)"
    img_max_height: str = "320px"
    img_margin: str = "14px 0 12px 0"
    img_border_radius: str = "10px"
    img_border: str = "1px solid currentColor"
    link_color: str = "currentColor"
    link_underline: bool = True
    image_suffixes: Tuple[str, ...] = (
        ".jpg",
        ".jpeg",
        ".png",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
    )
    image_host_allowlist: Tuple[str, ...] = (
        "pddugc.com",
        "pddpic.com",
    )


DEFAULT_CHAT_BUBBLE_OPTIONS = ChatBubbleHtmlOptions()


def _inner_wrap_style(opts: ChatBubbleHtmlOptions) -> str:
    return (
        "display:block;box-sizing:border-box;"
        f"padding:{opts.inner_padding};margin:0;"
        "font-size:inherit;"
        f"line-height:{opts.line_height};"
        f"letter-spacing:{opts.letter_spacing};word-spacing:{opts.word_spacing};"
    )


def _to_display_halfwidth(text: str) -> str:
    """全角 ASCII 区与全角空格 → 半角（仅用于非 URL 文本块）。"""
    out: List[str] = []
    for ch in text:
        o = ord(ch)
        if o == 0x3000:
            out.append(" ")
        elif 0xFF01 <= o <= 0xFF5E:
            out.append(chr(o - 0xFEE0))
        else:
            out.append(ch)
    return "".join(out)


def _text_chunk_to_markup(chunk: str) -> str:
    """纯文本块：半角化 → 转义 → 单换行变 br。"""
    return html_module.escape(_to_display_halfwidth(chunk)).replace("\n", "<br/>")


def _hostname(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def _host_on_allowlist(hostname: str, roots: Tuple[str, ...]) -> bool:
    if not hostname:
        return False
    for root in roots:
        r = root.lower().lstrip(".")
        if hostname == r or hostname.endswith("." + r):
            return True
    return False


def _path_has_image_suffix(url: str, suffixes: Tuple[str, ...]) -> bool:
    try:
        path = urlparse(url).path.lower()
    except Exception:
        return False
    return any(path.endswith(s) for s in suffixes)


def looks_like_image_url(
    url: str,
    *,
    options: Optional[ChatBubbleHtmlOptions] = None,
) -> bool:
    """
    图片 URL：路径带白名单后缀，或主机命中 image_host_allowlist（子域允许）。
    不再使用域名片段子串匹配。
    """
    opts = options or DEFAULT_CHAT_BUBBLE_OPTIONS
    if not url or not (url.startswith("http://") or url.startswith("https://")):
        return False
    host = _hostname(url)
    if _path_has_image_suffix(url, opts.image_suffixes):
        return True
    if _host_on_allowlist(host, opts.image_host_allowlist):
        return True
    return False


def _sanitize_img_src(url: str) -> Optional[str]:
    u = url.strip()
    if len(u) < 12 or len(u) > 2048:
        return None
    low = u.lower()
    if not (low.startswith("https://") or low.startswith("http://")):
        return None
    if any(c in u for c in "\n\r\t\"'<>"):
        return None
    if low.startswith("javascript:") or low.startswith("data:"):
        return None
    return html_module.escape(u, quote=True)


def _img_tag(src_escaped: str, opts: ChatBubbleHtmlOptions) -> str:
    img_style = (
        f"max-width:{opts.img_max_width};max-height:{opts.img_max_height};"
        f"width:auto;height:auto;object-fit:contain;border-radius:{opts.img_border_radius};"
        f"display:block;{opts.img_border};"
        "opacity:1;"
    )
    onerr = (
        "this.onerror=null;this.style.opacity='0.45';"
        "this.style.borderStyle='dashed';"
        "this.title='图片加载失败';"
    )
    return (
        f"<div style=\"margin:{opts.img_margin};color:inherit;\">"
        f"<img src=\"{src_escaped}\" alt=\"\" loading=\"lazy\" decoding=\"async\" "
        f"style=\"{img_style}\" "
        f'onerror="{onerr}" />'
        f"</div>"
    )


def _link_tag(url: str, opts: ChatBubbleHtmlOptions) -> str:
    esc = html_module.escape(url, quote=True)
    dec = "underline" if opts.link_underline else "none"
    return (
        f"<a href=\"{esc}\" style=\"word-break:break-all;color:{opts.link_color};"
        f"text-decoration:{dec};\">{esc}</a>"
    )


def _segment_plaintext_urls_to_markup(segment: str, opts: ChatBubbleHtmlOptions) -> str:
    """单段内：URL 与非 URL 文本交替渲染（半角仅作用于非 URL 块）。"""
    matches: List[re.Match[str]] = list(_URL_RE.finditer(segment))
    if not matches:
        return _text_chunk_to_markup(segment)

    parts: List[str] = []
    last = 0
    for m in matches:
        if m.start() > last:
            parts.append(_text_chunk_to_markup(segment[last : m.start()]))
        url = m.group(0)
        src = _sanitize_img_src(url)
        if src and looks_like_image_url(url, options=opts):
            parts.append(_img_tag(src, opts))
        elif src:
            parts.append(_link_tag(url, opts))
        else:
            parts.append(html_module.escape(_to_display_halfwidth(m.group(0))))
        last = m.end()
    if last < len(segment):
        parts.append(_text_chunk_to_markup(segment[last:]))
    return "".join(parts)


def _paragraphs_to_markup(body: str, opts: ChatBubbleHtmlOptions) -> str:
    """按连续换行分段，每段包 <p>，段内单换行为 <br/>。"""
    chunks = _PARA_SPLIT_RE.split(body)
    stripped = [c.strip("\n") for c in chunks]
    paragraphs = [p for p in stripped if p]
    if not paragraphs:
        return ""
    n = len(paragraphs)
    out: List[str] = []
    for i, para in enumerate(paragraphs):
        mb = "0" if i == n - 1 else opts.paragraph_margin_bottom
        inner = _segment_plaintext_urls_to_markup(para, opts)
        out.append(f'<p style="margin:0 0 {mb} 0;">{inner}</p>')
    return "".join(out)


def format_chat_bubble_html(
    content: str,
    *,
    options: Optional[ChatBubbleHtmlOptions] = None,
) -> str:
    """
    将消息正文转为可放入 QTextBrowser 的安全 HTML。

    - 连续换行分段为 ``<p>``，段内单换行为 ``<br/>``。
    - URL 用前瞻去掉句末标点；图片为「后缀命中 ∪ 主机白名单」。
    - 半角化仅应用于非 URL 文本块。
    """
    opts = options or DEFAULT_CHAT_BUBBLE_OPTIONS
    raw = (content or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return ""

    body_markup = _paragraphs_to_markup(raw, opts)
    if not body_markup:
        return ""

    wrap = _inner_wrap_style(opts)
    return f'<div style="{wrap}">{body_markup}</div>'
