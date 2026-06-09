# Copyright (c) 2026 paidaxin-12138
# Licensed under CC BY-NC 4.0 — see LICENSE in repository root.
# https://creativecommons.org/licenses/by-nc/4.0/
"""chat_messages 未读复合索引

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-06
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from database.schema_migrations import migrate_chat_messages_unread_index

    bind = op.get_bind()
    migrate_chat_messages_unread_index(bind.engine)


def downgrade() -> None:
    pass
