"""add_import_task_upsert_options — ImportTask 扩展 upsert 选项字段.

Revision ID: e1f2a3b4c5d6
Revises: d8e9f0a1b2c3
Create Date: 2026-09-16 11:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e1f2a3b4c5d6'
down_revision: Union[str, Sequence[str], None] = 'd8e9f0a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tables_importtask',
        sa.Column('match_keys', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        'tables_importtask',
        sa.Column('unknown_cols_strategy', sa.String(length=16), nullable=False, server_default='drop'),
    )


def downgrade() -> None:
    op.drop_column('tables_importtask', 'unknown_cols_strategy')
    op.drop_column('tables_importtask', 'match_keys')
