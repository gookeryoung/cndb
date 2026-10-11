"""add_forms_formdefinition — 新增表单定制与权限控制模块.

Revision ID: b8a7c6d5e4f3
Revises: a9c0d1e2f3b4
Create Date: 2026-10-11 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8a7c6d5e4f3'
down_revision: str | Sequence[str] | None = 'a9c0d1e2f3b4'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建 forms_formdefinition 表：表单定义 + 字段配置 + 三权限阈值.

    FK 内联在列定义中（SQLite 不支持 ALTER TABLE ADD CONSTRAINT）。
    """
    op.create_table(
        'forms_formdefinition',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            'workspace_id',
            sa.Integer(),
            sa.ForeignKey('workspaces_workspace.id', ondelete='CASCADE', name='fk_formdefinition_workspace'),
            nullable=False,
            index=True,
        ),
        sa.Column(
            'table_id',
            sa.Integer(),
            sa.ForeignKey('tables_datatable.id', ondelete='CASCADE', name='fk_formdefinition_table'),
            nullable=False,
            index=True,
        ),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('field_config', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('layout', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('use_role', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('edit_role', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('delete_role', sa.String(length=16), nullable=False, server_default=''),
        sa.Column('order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('trashed', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('trashed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint('table_id', 'name', name='uniq_form_table_name'),
    )


def downgrade() -> None:
    """降级：删除 forms_formdefinition 表."""
    op.drop_table('forms_formdefinition')
