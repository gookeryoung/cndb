"""add_export_templates — 文档导出模板表（ADR 0152）.

Revision ID: b7c8d9e0f1a2
Revises: ea1b2c3d4e5f
Create Date: 2026-11-25 10:00:00.000000

新增 ``documents_exporttemplate``：工作区级 Word / PDF 排版模板。

- ``config`` 存 ``ExportTemplateConfig`` 的规范化 JSON，写入前由服务层强校验；
- ``(workspace_id, name)`` 唯一（同工作区不允许同名模板）；
- 内置预设（standard / research / …）是代码常量不落库，因此**存量零迁移**：
  没有自定义模板的工作区导出仍走内置 ``standard``，视觉与升级前逐项一致。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, Sequence[str], None] = 'ea1b2c3d4e5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'documents_exporttemplate'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建导出模板表."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('description', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('workspace_id', 'name', name='uq_documents_exporttemplate_ws_name'),
    )
    op.create_index(
        'ix_documents_exporttemplate_ws_default',
        _TABLE,
        ['workspace_id', 'is_default'],
    )


def downgrade() -> None:
    """删除导出模板表（模板是纯新增数据，回退不涉及业务行）."""
    if not _table_exists(_TABLE):
        return
    insp = sa.inspect(op.get_bind())
    indexes = {ix['name'] for ix in insp.get_indexes(_TABLE)}
    if 'ix_documents_exporttemplate_ws_default' in indexes:
        op.drop_index('ix_documents_exporttemplate_ws_default', table_name=_TABLE)
    op.drop_table(_TABLE)
