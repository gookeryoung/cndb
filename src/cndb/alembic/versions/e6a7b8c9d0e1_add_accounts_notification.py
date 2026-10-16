"""add_accounts_notification — 站内通知（文档协作授权）.

Revision ID: e6a7b8c9d0e1
Revises: c3d4e5f6a7b8
Create Date: 2026-10-16

新增 ``accounts_notification``：让协作动作可见 —— 被授权者收到
「X 邀请你协作《文档》（角色）」，未读数供前端角标使用。
payload 保存渲染快照（文档标题、角色、操作者名），不做历史回填。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "accounts_notification"
_TS_DEFAULT = sa.text("(CURRENT_TIMESTAMP)")


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建通知表（幂等）."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["recipient_id"], ["accounts_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces_workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents_document.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_accounts_notification_recipient_id", _TABLE, ["recipient_id"])
    op.create_index("ix_accounts_notification_type", _TABLE, ["type"])
    op.create_index("ix_accounts_notification_workspace_id", _TABLE, ["workspace_id"])
    op.create_index("ix_accounts_notification_document_id", _TABLE, ["document_id"])


def downgrade() -> None:
    if not _table_exists(_TABLE):
        return
    for name in (
        "ix_accounts_notification_document_id",
        "ix_accounts_notification_workspace_id",
        "ix_accounts_notification_type",
        "ix_accounts_notification_recipient_id",
    ):
        op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
