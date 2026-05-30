"""遗留 SQLite 增量补丁（记忆字段、退款日志、ops 列、时间戳）

Revision ID: 0001
Revises:
Create Date: 2026-05-30

已有生产库若已通过 DatabaseManager 跑过补丁，可执行：
  alembic stamp 0001
再执行 upgrade 将幂等跳过无变更列。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from database.schema_migrations import apply_legacy_migrations

    bind = op.get_bind()
    apply_legacy_migrations(bind.engine)


def downgrade() -> None:
    # 增量 ALTER 不可逆；降级仅用于开发重置
    pass
