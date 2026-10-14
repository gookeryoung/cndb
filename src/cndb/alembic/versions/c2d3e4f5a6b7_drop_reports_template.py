"""drop_reports_template — 移除报表功能，删除 reports_template 表.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-10-14 23:30:00.000000

报表功能已下线，导出能力（Word/PDF/Markdown）迁移到文档功能，
reports_template 不再有模型与读写路径，此处删除该表。

downgrade 会按删除前的最终 schema 重建空表（数据不可恢复），
保证 alembic 降级链不因表缺失而断裂。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """判断当前库中表是否存在."""
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """删除 reports_template（表不存在时跳过，兼容全新库与已清理库）."""
    if _table_exists('reports_template'):
        op.drop_table('reports_template')


def downgrade() -> None:
    """按最终 schema 重建 reports_template 空表（数据不可恢复）."""
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
        sa.Column('view_id', sa.Integer(), nullable=True),
        sa.Column('extra_table_ids', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('theme', sa.String(length=16), nullable=False, server_default='minimal'),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        # 约束名与历史迁移一致：降级链上 e9f0a1b2c3d4 会按名 drop_constraint
        sa.ForeignKeyConstraint(
            ['table_id'], ['tables_datatable.id'], name='fk_template_table_id', ondelete='SET NULL'
        ),
        sa.ForeignKeyConstraint(
            ['view_id'], ['tables_dataview.id'], name='fk_reports_template_view_id', ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reports_template_table_id'), 'reports_template', ['table_id'], unique=False)
    op.create_index(op.f('ix_reports_template_view_id'), 'reports_template', ['view_id'], unique=False)
    op.create_index(op.f('ix_reports_template_workspace_id'), 'reports_template', ['workspace_id'], unique=False)
