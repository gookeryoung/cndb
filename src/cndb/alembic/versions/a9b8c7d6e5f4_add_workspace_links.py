"""add_workspace_links — 工作区链接表（ADR 0154 P0）.

Revision ID: a9b8c7d6e5f4
Revises: f2b3c4d5e6a7
Create Date: 2026-11-25 13:40:00.000000

新增 ``workspaces_workspacelink``：跨工作区只读引用的申请 / 批准 / 到期载体。

- 权限口径：链接**不授予**权限；A 期批准时把受众批量加为源工作区真实
  ``WorkspaceMember(viewer)``，因此存量判定与 H15 均不变（ADR 0154 L1）。
- **存量零迁移**：新表，无回填；无链接时全部既有路径行为不变（L7）。
- 表名索引与 ``workspaces`` 插件同前缀，方便按插件聚合清理。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, Sequence[str], None] = 'f2b3c4d5e6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'workspaces_workspacelink'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建链接表（幂等：已存在则跳过）."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('source_workspace_id', sa.Integer(), nullable=False),
        sa.Column('target_type', sa.String(length=16), nullable=False),
        sa.Column('target_table_id', sa.Integer(), nullable=False),
        sa.Column('target_view_id', sa.Integer(), nullable=True),
        sa.Column('alias', sa.String(length=64), nullable=False),
        sa.Column(
            'status',
            sa.Enum('PENDING', 'ACTIVE', 'REJECTED', 'EXPIRED', name='workspacelinkstatus'),
            nullable=False,
        ),
        sa.Column('ttl_days', sa.Integer(), nullable=False),
        sa.Column('granted_member_ids', sa.JSON(), nullable=False),
        sa.Column('created_member_ids', sa.JSON(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_by_id', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('note', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['source_workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_table_id'], ['tables_datatable.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_view_id'], ['tables_dataview.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['approved_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workspace_id', 'alias', name='uniq_workspace_link_alias'),
    )
    op.create_index('ix_workspaces_workspacelink_workspace_id', _TABLE, ['workspace_id'])
    op.create_index('ix_workspaces_workspacelink_source_workspace_id', _TABLE, ['source_workspace_id'])
    op.create_index('ix_workspaces_workspacelink_target_table_id', _TABLE, ['target_table_id'])
    op.create_index('ix_workspaces_workspacelink_status', _TABLE, ['status'])


def downgrade() -> None:
    """删除链接表（数据随表丢弃，链接本身不参与备份）。"""
    if _table_exists(_TABLE):
        op.drop_table(_TABLE)
