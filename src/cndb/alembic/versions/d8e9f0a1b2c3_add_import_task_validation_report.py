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


def _table_exists(table_name: str) -> bool:
    """判断当前库中表是否存在."""
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _ensure_importtask_base_table() -> None:
    """tables_importtask 历史上由 create_all 兜底建表（迁移链从未创建）.

    从旧 schema 一路 upgrade 的库可能没有该表 —— 先补建截至本迁移时刻的基础表
    （不含本迁移及后续迁移新增的扩展列）。
    """
    if _table_exists('tables_importtask'):
        return
    op.create_table(
        'tables_importtask',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column('table_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('filename', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('format', sa.String(length=16), nullable=False, server_default='json'),
        sa.Column('file_content', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'),
        sa.Column('progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('imported_rows', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_message', sa.Text(), nullable=False, server_default=''),
        sa.Column('result_ids', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(
            ['table_id'], ['tables_datatable.id'], name='fk_importtask_table_id', ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(
            ['user_id'], ['accounts_user.id'], name='fk_importtask_user_id', ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tables_importtask_table_id'), 'tables_importtask', ['table_id'], unique=False)
    op.create_index(op.f('ix_tables_importtask_user_id'), 'tables_importtask', ['user_id'], unique=False)
    op.create_index(op.f('ix_tables_importtask_status'), 'tables_importtask', ['status'], unique=False)


def upgrade() -> None:
    """ImportTask 新增 validation_report TEXT 列 + status 长度从 16 扩到 32."""
    _ensure_importtask_base_table()
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
