"""add_import_task_dropped_columns — ImportTask 扩展 dropped_columns 字段.

Revision ID: a2b3c4d5e6f7
Revises: f3a4b5c6d7e8
Create Date: 2026-09-18 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: str | Sequence[str] | None = 'f3a4b5c6d7e8'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """ImportTask 新增 dropped_columns JSON 列.

    存放用户在预览阶段勾选丢弃的未知字段名列表.
    """
    op.add_column(
        'tables_importtask',
        sa.Column(
            'dropped_columns',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    """降级：移除 dropped_columns 列."""
    op.drop_column('tables_importtask', 'dropped_columns')
