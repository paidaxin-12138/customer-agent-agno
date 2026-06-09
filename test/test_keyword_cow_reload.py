# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
from unittest.mock import patch

from Message.handlers.keyword_handler import KeywordDetectionHandler


def test_reload_keywords_copy_on_write():
    handler = KeywordDetectionHandler()
    old_ref = handler._keywords_snapshot
    with patch.object(
        handler,
        "_load_keywords_frozen",
        return_value=frozenset({"新关键词", "人工"}),
    ):
        handler.reload_keywords()
    assert handler._keywords_snapshot is not old_ref
    assert "新关键词" in handler._keywords_snapshot
    assert handler.get_keyword_count() == 2
