"""add_report_template_theme — ReportTemplate 主题风格列.

Revision ID: d4e5f6a7b8c9
Revises: b3c4d5e6f7a8
Create Date: 2026-09-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'b3c4d5e6f7a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """判断当前库中表是否存在."""
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _ensure_template_base_table() -> None:
    """reports_template 历史上由 create_all 兜底建表（迁移链从未创建）.

    从旧 schema 一路 upgrade 的库可能没有该表 —— 先补建截至上一迁移时刻的基础表
    （不含本迁移新增的 theme 列）。
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
    op.add_column(
        'reports_template',
        sa.Column('extra_table_ids', sa.JSON(), nullable=False, server_default='[]'),
    )


def upgrade() -> None:
    """ReportTemplate 新增 theme 列（主题风格，存量行默认 minimal）."""
    _ensure_template_base_table()
    op.add_column(
        'reports_template',
        sa.Column('theme', sa.String(length=16), nullable=False, server_default='minimal'),
    )


def downgrade() -> None:
    """降级：移除 theme 列."""
    op.drop_column('reports_template', 'theme')
