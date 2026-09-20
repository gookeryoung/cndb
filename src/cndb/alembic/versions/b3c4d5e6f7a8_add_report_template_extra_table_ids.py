"""add_report_template_extra_table_ids — ReportTemplate 持久化额外引用表.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-20 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """判断当前库中表是否存在."""
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _ensure_template_base_table() -> None:
    """reports_template 历史上由 create_all 兜底建表（迁移链从未创建）.

    从旧 schema 一路 upgrade 的库可能没有该表 —— 先补建截至本迁移时刻的基础表
    （不含本迁移新增的 extra_table_ids 列）。
    """
    if _table_exists('reports_template'):
        return
    op.create_table(
        'reports_template',
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
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('output_format', sa.String(length=16), nullable=False, server_default='docx'),
        sa.Column('template_content', sa.Text(), nullable=False),
        sa.Column('parameters', sa.JSON(), nullable=False),
        sa.Column('table_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ['table_id'], ['tables_datatable.id'], name='fk_template_table_id', ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reports_template_table_id'), 'reports_template', ['table_id'], unique=False)


def upgrade() -> None:
    """ReportTemplate 新增 extra_table_ids JSON 列（额外引用表持久化，默认空列表）."""
    _ensure_template_base_table()
    op.add_column(
        'reports_template',
        sa.Column('extra_table_ids', sa.JSON(), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    """降级：移除 extra_table_ids 列."""
    op.drop_column('reports_template', 'extra_table_ids')
