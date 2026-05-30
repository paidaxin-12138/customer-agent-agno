import pytest

from Message.handlers.channel_send import build_send_metadata


def test_build_send_metadata_merges_existing():
    meta = build_send_metadata(
        "s1",
        "u1",
        "b1",
        metadata={"shop_id": "s1", "username": "seller"},
    )
    assert meta["from_uid"] == "b1"
    assert meta["username"] == "seller"
