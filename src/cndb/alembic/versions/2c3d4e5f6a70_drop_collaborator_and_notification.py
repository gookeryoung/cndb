"""drop_collaborator_and_notification — 移除文档协作者与站内通知.

Revision ID: 2c3d4e5f6a70
Revises: 1b2c3d4e5f60
Create Date: 2026-10-21 07:40:00.000000

协作者功能（文档级授权）取消后：

- ``documents_permission``：文档级授权覆盖表，随协作者接口一并废弃；
- ``accounts_notification``：站内通知的**唯一**产生方就是"被加入文档协作者"，
  协作者取消后不再有任何写入点，表与接口一并移除。

drop 前先删索引（SQLite 上 drop_table 虽会带走索引，但显式删除便于
downgrade/upgrade 在已有库上重复执行时保持幂等）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2c3d4e5f6a70"
down_revision: str | Sequence[str] | None = "1b2c3d4e5f60"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSION = "documents_permission"
_NOTIFICATION = "accounts_notification"

_NOTIFICATION_INDEXES = (
    "ix_accounts_notification_document_id",
    "ix_accounts_notification_workspace_id",
    "ix_accounts_notification_type",
    "ix_accounts_notification_recipient_id",
)
_PERMISSION_INDEXES = ("ix_documents_permission_user_id",)


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _index_exists(index: str, table: str) -> bool:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return False
    return index in {ix["name"] for ix in insp.get_indexes(table)}


def _drop(indexes: tuple[str, ...], table: str) -> None:
    if not _table_exists(table):
        return
    for index in indexes:
        if _index_exists(index, table):
            op.drop_index(index, table_name=table)
    op.drop_table(table)


def upgrade() -> None:
    """删除协作者授权表与通知表（缺表跳过）."""
    _drop(_PERMISSION_INDEXES, _PERMISSION)
    _drop(_NOTIFICATION_INDEXES, _NOTIFICATION)


def downgrade() -> None:
    """重建两表（结构与原迁移一致；历史数据不回填）."""
    if not _table_exists(_PERMISSION):
        op.create_table(
            _PERMISSION,
            sa.Column("document_id", sa.Integer(), primary_key=True),
            sa.Column("user_id", sa.Integer(), primary_key=True),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.ForeignKeyConstraint(["document_id"], ["documents_document.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["accounts_user.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_documents_permission_user_id", _PERMISSION, ["user_id"])

    if not _table_exists(_NOTIFICATION):
        op.create_table(
            _NOTIFICATION,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")
            ),
            sa.Column(
                "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")
            ),
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
        for index in _NOTIFICATION_INDEXES:
            op.create_index(index, _NOTIFICATION, [index.removeprefix("ix_accounts_notification_")])
