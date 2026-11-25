"""add_teams — 团队层（`workspaces_team` / `workspaces_team_member` + `workspace.team_id`，ADR 0153 P1）.

Revision ID: e7d8c9b0a1f2
Revises: b7c8d9e0f1a2
Create Date: 2026-11-25 12:00:00.000000

- 团队单层扁平：**不建** ``parent_team_id``（ADR 0153 D2 / I7）；
- 工作区归属单值可空：``team_id IS NULL`` = 个人工作区（D3 / I5）；
- **存量零迁移**：不回填任何数据，``team_id`` 全空、``policy`` 缺键按默认补齐
  ⇒ 迁移后每个用户 × 每个工作区的判定结果与升级前逐条一致（I3）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7d8c9b0a1f2'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TEAM = 'workspaces_team'
_TEAM_MEMBER = 'workspaces_team_member'
_WORKSPACE = 'workspaces_workspace'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    """目标列是否存在（幂等：已存在时跳过）."""
    inspector = sa.inspect(op.get_bind())
    return any(col['name'] == column for col in inspector.get_columns(table))


def upgrade() -> None:
    """创建团队表与团队成员表，并给工作区加 ``team_id``."""
    if not _table_exists(_TEAM):
        op.create_table(
            _TEAM,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=128), nullable=False),
            sa.Column('slug', sa.String(length=64), nullable=False),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('policy', sa.JSON(), nullable=False, server_default='{}'),
            sa.Column('created_by_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('slug', name='uniq_team_slug'),
        )
        op.create_index('ix_workspaces_team_created_by_id', _TEAM, ['created_by_id'])
        op.create_index('ix_workspaces_team_slug', _TEAM, ['slug'])

    if not _table_exists(_TEAM_MEMBER):
        op.create_table(
            _TEAM_MEMBER,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('team_id', sa.Integer(), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('role', sa.Enum('OWNER', 'ADMIN', 'MEMBER', name='teamrole'), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.ForeignKeyConstraint(['team_id'], [f'{_TEAM}.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['accounts_user.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('team_id', 'user_id', name='uniq_team_member'),
        )
        op.create_index('ix_workspaces_team_member_team_id', _TEAM_MEMBER, ['team_id'])
        op.create_index('ix_workspaces_team_member_user_id', _TEAM_MEMBER, ['user_id'])

    # 部分升级场景（老库 / 迁移测试桩）里 workspaces_workspace 可能不存在：先判表再判列
    if _table_exists(_WORKSPACE) and not _column_exists(_WORKSPACE, 'team_id'):
        # SQLite 不支持 ALTER ADD CONSTRAINT：用 batch 模式重建列（仅此一处代价），
        # 存量行 team_id 保持 NULL（零迁移，H13 / I3）
        with op.batch_alter_table(_WORKSPACE, recreate='always') as batch:
            batch.add_column(
                sa.Column(
                    'team_id',
                    sa.Integer(),
                    nullable=True,
                    comment='所属团队（空 = 个人工作区，ADR 0153）',
                )
            )
            batch.create_foreign_key(
                'fk_workspaces_workspace_team_id',
                _TEAM,
                ['team_id'],
                ['id'],
                ondelete='SET NULL',
            )
            batch.create_index('ix_workspaces_workspace_team_id', ['team_id'])


def downgrade() -> None:
    """还原：先删工作区列，再删两张团队表（顺序反解）."""
    if _table_exists(_WORKSPACE) and _column_exists(_WORKSPACE, 'team_id'):
        # 同样走 batch 重建（SQLite 无法原地 DROP CONSTRAINT）
        with op.batch_alter_table(_WORKSPACE, recreate='always') as batch:
            batch.drop_index('ix_workspaces_workspace_team_id')
            batch.drop_constraint('fk_workspaces_workspace_team_id', type_='foreignkey')
            batch.drop_column('team_id')

    if _table_exists(_TEAM_MEMBER):
        op.drop_table(_TEAM_MEMBER)
    if _table_exists(_TEAM):
        op.drop_table(_TEAM)
