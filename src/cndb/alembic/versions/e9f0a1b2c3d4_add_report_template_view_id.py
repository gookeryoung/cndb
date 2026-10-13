"""add_report_template_view_id — ReportTemplate 关联视图列.

Revision ID: e9f0a1b2c3d4
Revises: e8f9a0b1c2d3
Create Date: 2026-10-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e9f0a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    """判断当前库中表是否存在."""
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """ReportTemplate 新增 view_id 列（可选绑定主表视图，视图删除落 NULL）."""
    if not _table_exists('reports_template'):
        # legacy 库缺表：启动期 create_all 按完整 ORM 元数据兜底建表，此处跳过
        return
    # SQLite 不支持裸 ALTER 加约束，统一走 batch 模式（copy-and-move 重建表）
    with op.batch_alter_table('reports_template') as batch_op:
        batch_op.add_column(sa.Column('view_id', sa.Integer(), nullable=True))
        batch_op.create_index(op.f('ix_reports_template_view_id'), ['view_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_reports_template_view_id',
            'tables_dataview',
            ['view_id'],
            ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    """降级：移除 view_id 列及其索引/外键."""
    if not _table_exists('reports_template'):
        return
    with op.batch_alter_table('reports_template') as batch_op:
        batch_op.drop_index(op.f('ix_reports_template_view_id'))
        batch_op.drop_constraint('fk_reports_template_view_id', type_='foreignkey')
        batch_op.drop_column('view_id')
