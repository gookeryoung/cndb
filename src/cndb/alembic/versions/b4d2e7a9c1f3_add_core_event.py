"""add_core_event — 统一事件/审计流.

Revision ID: b4d2e7a9c1f3
Revises: a3f1c9d2e7b4
Create Date: 2026-10-15

新增 ``core_event``：跨插件的统一事件表（actor/action/target/summary/detail/request_id）。
既有 ``accounts_userauditlog``、``tables_auditlog`` 及各插件 event 表**保持不变**，
统一流作为汇总视图，不做历史回填（历史痕迹仍可查原表）。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b4d2e7a9c1f3'
down_revision: Union[str, Sequence[str], None] = 'a3f1c9d2e7b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'core_event'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建统一事件表（幂等）."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('workspace_id', sa.Integer(), nullable=True),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_name', sa.String(length=150), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_id', sa.String(length=64), nullable=True),
        sa.Column('summary', sa.String(length=255), nullable=False, server_default=''),
        sa.Column('detail', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('request_id', sa.String(length=64), nullable=True),
    )
    op.create_index('ix_core_event_action', _TABLE, ['action'])
    op.create_index('ix_core_event_actor_id', _TABLE, ['actor_id'])
    op.create_index('ix_core_event_target_type', _TABLE, ['target_type'])
    op.create_index('ix_core_event_target_id', _TABLE, ['target_id'])
    op.create_index('ix_core_event_workspace_id', _TABLE, ['workspace_id'])
    op.create_index('ix_core_event_request_id', _TABLE, ['request_id'])
    op.create_index('ix_core_event_created_action', _TABLE, ['created_at', 'action'])


def downgrade() -> None:
    if not _table_exists(_TABLE):
        return
    for name in (
        'ix_core_event_created_action',
        'ix_core_event_request_id',
        'ix_core_event_workspace_id',
        'ix_core_event_target_id',
        'ix_core_event_target_type',
        'ix_core_event_actor_id',
        'ix_core_event_action',
    ):
        op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
