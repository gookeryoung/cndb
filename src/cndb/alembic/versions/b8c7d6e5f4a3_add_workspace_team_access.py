"""add_workspace_team_access — 团队数据授权（ADR 0154 B′ / P3.1）.

Revision ID: b8c7d6e5f4a3
Revises: a9b8c7d6e5f4
Create Date: 2026-11-25 18:30:00.000000

两部分：
1. 新表 ``workspaces_teamaccess``：源工作区把「某团队 = viewer」授出去，
   只产 ``data_role``、不产管理面（ADR 0154 D11）；
2. ``workspaces_workspacelink`` 增 ``audience`` / ``granted_team_id``：
   链接申请可选择「授给团队」而不是逐个加成员（B′ 与 A 并存）。

**存量零迁移**：新表无回填；`audience` 给默认值 ``members``（等价 P0 行为），
`granted_team_id` 为 NULL。downgrade 删表 + 删两列（SQLite 走 batch 重建）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c7d6e5f4a3'
down_revision: Union[str, Sequence[str], None] = 'a9b8c7d6e5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEAM_ACCESS = 'workspaces_teamaccess'
_LINK = 'workspaces_workspacelink'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')

#: 链接表的外键依赖（batch 重建前必须都存在，否则反思失败）
_LINK_DEPS = (
    'workspaces_workspace',
    'workspaces_team',
    'tables_datatable',
    'tables_dataview',
    'accounts_user',
)


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    return any(col['name'] == column for col in sa.inspect(op.get_bind()).get_columns(table))


def upgrade() -> None:
    """建团队授权表，并给链接表加受众列."""
    # 部分升级场景（老库 / 迁移测试桩）里依赖表可能不存在：先判表，缺依赖就整段跳过
    team_access_ready = all(
        _table_exists(name) for name in ('workspaces_workspace', 'workspaces_team', 'accounts_user')
    )
    if team_access_ready and not _table_exists(_TEAM_ACCESS):
        op.create_table(
            _TEAM_ACCESS,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('workspace_id', sa.Integer(), nullable=False),
            sa.Column('team_id', sa.Integer(), nullable=False),
            sa.Column('role', sa.String(length=16), nullable=False, server_default='viewer'),
            sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('granted_by_id', sa.Integer(), nullable=True),
            sa.Column('note', sa.String(length=200), nullable=False, server_default=''),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['team_id'], ['workspaces_team.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['granted_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('workspace_id', 'team_id', name='uniq_workspace_team_access'),
        )
        op.create_index('ix_workspaces_teamaccess_workspace_id', _TEAM_ACCESS, ['workspace_id'])
        op.create_index('ix_workspaces_teamaccess_team_id', _TEAM_ACCESS, ['team_id'])

    if (
        _table_exists(_LINK)
        and all(_table_exists(name) for name in _LINK_DEPS)
        and not _column_exists(_LINK, 'audience')
    ):
        with op.batch_alter_table(_LINK, recreate='always') as batch:
            batch.add_column(sa.Column('audience', sa.String(length=16), nullable=False, server_default='members'))
            batch.add_column(sa.Column('granted_team_id', sa.Integer(), nullable=True))
            batch.create_foreign_key(
                'fk_workspaces_workspacelink_granted_team_id',
                'workspaces_team',
                ['granted_team_id'],
                ['id'],
                ondelete='SET NULL',
            )


def downgrade() -> None:
    """删链接表的受众列与团队授权表（顺序反解）."""
    if (
        _table_exists(_LINK)
        and all(_table_exists(name) for name in _LINK_DEPS)
        and _column_exists(_LINK, 'audience')
    ):
        with op.batch_alter_table(_LINK, recreate='always') as batch:
            batch.drop_constraint('fk_workspaces_workspacelink_granted_team_id', type_='foreignkey')
            batch.drop_column('granted_team_id')
            batch.drop_column('audience')

    if _table_exists(_TEAM_ACCESS):
        op.drop_table(_TEAM_ACCESS)
