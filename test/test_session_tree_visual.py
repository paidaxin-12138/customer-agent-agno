"""会话树展示：全量列表与未读红点。"""
from ui.chat.session_tree import (
    apply_session_tree_item_visual,
    format_session_tree_label,
    session_sort_key,
    unread_dot_icon,
)


def test_unread_dot_icon_cached(qapp):
    a = unread_dot_icon()
    b = unread_dot_icon()
    assert a is b
    assert not a.isNull()


def test_format_session_tree_label_shows_closed_tag():
    label = format_session_tree_label(
        {
            "buyer_nickname": "小*姑",
            "status": "closed",
            "last_message": "你好",
            "unread_count": 0,
        }
    )
    assert "已结案" in label
    assert "小*姑" in label


def test_session_sort_key_unread_first():
    older_unread = {"unread_count": 2, "updated_at": 1.0}
    newer_read = {"unread_count": 0, "updated_at": 99.0}
    assert session_sort_key(older_unread) > session_sort_key(newer_read)


def test_apply_session_tree_item_visual_sets_icon_when_unread(qapp):
    from PyQt6.QtWidgets import QTreeWidgetItem

    item = QTreeWidgetItem(["test"])
    apply_session_tree_item_visual(item, {"unread_count": 3})
    assert not item.icon(0).isNull()
    apply_session_tree_item_visual(item, {"unread_count": 0})
    assert item.icon(0).isNull()
