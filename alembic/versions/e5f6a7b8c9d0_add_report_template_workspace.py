"""add_report_template_workspace — ReportTemplate 归属工作区列.

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-09-28 12:00:00.000000

报表归属工作区：reports_template 新增 workspace_id 列（显式归属，优先于
table_id 反推）。回填策略：显式归属为空的存量模板按所属表反推工作区，
表已删除的保持 NULL（不归属任何工作区，仅全量 API 可见）。

链上加列迁移均不建 FK（b2c3d4e5f6a7 / d4e5f6a7b8c9 先例，SQLite 不支持
裸 ALTER 加约束且不强制 FK）——FK 由 ORM 声明，create_all 新库生效；
存量库仅建列+索引，工作区删除后 workspace_id 悬挂（与 table_id 行为一致，
悬挂 id 不计入任何工作区报表页）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: reports_template 加 workspace_id 列并按归属表回填."""
    op.add_column('reports_template', sa.Column('workspace_id', sa.Integer(), nullable=True))
    op.create_index(
        op.f('ix_reports_template_workspace_id'),
        'reports_template',
        ['workspace_id'],
        unique=False,
    )
    # 回填：显式归属为空的存量模板按所属表反推工作区（关联子查询，表已删的保持 NULL）
    op.execute(
        'UPDATE reports_template '
        'SET workspace_id = ('
        '  SELECT t.workspace_id FROM tables_datatable t WHERE t.id = reports_template.table_id'
        ') '
        'WHERE table_id IS NOT NULL AND workspace_id IS NULL'
    )


def downgrade() -> None:
    """Downgrade schema: 移除 workspace_id 列与索引."""
    op.drop_index(op.f('ix_reports_template_workspace_id'), table_name='reports_template')
    op.drop_column('reports_template', 'workspace_id')
