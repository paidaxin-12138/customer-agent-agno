from dataclasses import replace

from utils.chat_message_html import (
    ChatBubbleHtmlOptions,
    DEFAULT_CHAT_BUBBLE_OPTIONS,
    format_chat_bubble_html,
    looks_like_image_url,
)


def test_looks_like_pdd_chat_image():
    u = "https://chat-img.pddugc.com/chat-pic-mall-user-v1/2026-05-12/5f31c95f-d8d6-4130/foo"
    assert looks_like_image_url(u)


def test_looks_like_suffix_without_whitelist():
    assert looks_like_image_url("https://example.com/a/b/photo.PNG?x=1")


def test_looks_like_rejects_plain_http_on_unknown_host():
    assert not looks_like_image_url("https://example.com/no-suffix-here/path")


def test_bubble_html_renders_img_for_pdd_url():
    u = "https://chat-img.pddugc.com/chat-pic-mall-user-v1/2026-05-12/x"
    h = format_chat_bubble_html(u)
    assert "<img " in h
    assert "chat-img.pddugc.com" in h
    assert "onerror=" in h


def test_bubble_html_escapes_plain_text():
    h = format_chat_bubble_html("hello <b>x</b>")
    assert "<b>" not in h
    assert "&lt;b&gt;" in h or "x" in h


def test_bubble_html_halfwidth_punctuation():
    h = format_chat_bubble_html("\uff0c\u3000\uff11")
    assert "," in h
    assert "1" in h
    assert "\uff0c" not in h


def test_bubble_html_wraps_inner_typography():
    h = format_chat_bubble_html("hi")
    assert "letter-spacing" in h
    assert "padding:" in h
    assert "<p " in h


def test_paragraphs_use_p_tags():
    h = format_chat_bubble_html("first line\nstill first\n\nsecond para")
    assert h.count("<p ") == 2
    assert "<br/>" in h


def test_url_trailing_period_not_inside_href():
    h = format_chat_bubble_html("see https://a.com/x.")
    assert 'href="https://a.com/x."' not in h
    assert 'href="https://a.com/x"' in h or "https://a.com/x" in h


def test_halfwidth_only_outside_url():
    h = format_chat_bubble_html("\uff11 https://chat-img.pddugc.com/a/b.")
    assert "<img " in h
    assert h.find("1 ") < h.find("<img")


def test_options_override_line_height():
    opts = replace(DEFAULT_CHAT_BUBBLE_OPTIONS, line_height="2.0")
    h = format_chat_bubble_html("a", options=opts)
    assert "line-height:2.0" in h
