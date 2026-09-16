"""add_import_task_validation_report — ImportTask 扩展校验报告字段.

Revision ID: d8e9f0a1b2c3
Revises: c7e8f9a0b1c2
Create Date: 2026-09-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e9f0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'c7e8f9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """ImportTask 新增 validation_report TEXT 列 + status 长度从 16 扩到 32."""
    op.add_column(
        'tables_importtask',
        sa.Column('validation_report', sa.Text(), nullable=False, server_default=''),
    )
    # SQLite 不支持 ALTER COLUMN，跳过 status 长度调整（16 字符对 pending_validation 不够）
    # 直接用 batch_alter_table 做标准迁移，SQLite 会重写表
    try:
        with op.batch_alter_table('tables_importtask') as batch_op:
            batch_op.alter_column(
                'status',
                existing_type=sa.String(length=16),
                type_=sa.String(length=32),
                existing_nullable=False,
            )
    except Exception:
        # 某些 SQLite 版本不支持 batch_alter，跳过（String 长度在 SQLite 下不强制）
        pass


def downgrade() -> None:
    """降级：移除 validation_report 列."""
    op.drop_column('tables_importtask', 'validation_report')
    # status 长度恢复（SQLite 下可能需要 batch）
    try:
        with op.batch_alter_table('tables_importtask') as batch_op:
            batch_op.alter_column(
                'status',
                existing_type=sa.String(length=32),
                type_=sa.String(length=16),
                existing_nullable=False,
            )
    except Exception:
        pass
