"""add_import_task_cleaning_actions — ImportTask 扩展 cleaning_actions 字段.

Revision ID: f3a4b5c6d7e8
Revises: e1f2a3b4c5d6
Create Date: 2026-09-16 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f3a4b5c6d7e8'
down_revision: str | Sequence[str] | None = 'e1f2a3b4c5d6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """ImportTask 新增 cleaning_actions JSON 列.

    存放用户在确认导入时勾选的清洗动作列表；默认空列表以兼容旧数据.
    """
    op.add_column(
        'tables_importtask',
        sa.Column(
            'cleaning_actions',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    """降级：移除 cleaning_actions 列."""
    op.drop_column('tables_importtask', 'cleaning_actions')
