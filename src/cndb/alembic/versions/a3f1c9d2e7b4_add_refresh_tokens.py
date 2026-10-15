"""add_refresh_tokens — 会话/授权生命周期：刷新令牌表 + 用户令牌代次.

Revision ID: a3f1c9d2e7b4
Revises: f5a6b7c8d9e0
Create Date: 2026-10-15

- accounts_refreshtoken：刷新令牌（会话）表，**只存 SHA-256 哈希**，支持吊销与轮换链
- accounts_user.token_version：令牌代次，改密 / 强制下线时 +1 使既有 access token 立即失效
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a3f1c9d2e7b4'
down_revision: Union[str, Sequence[str], None] = 'f5a6b7c8d9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'accounts_refreshtoken'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _has_table(table: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names()


def _has_column(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return False
    return column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    # 兼容「缺表的旧库」：accounts_user 不存在时跳过加列（与既有迁移的宽容策略一致）
    if _has_table("accounts_user") and not _has_column("accounts_user", "token_version"):
        with op.batch_alter_table("accounts_user") as batch:
            batch.add_column(sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))

    if not _has_table(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.Column("user_id", sa.Integer(), nullable=False),
            sa.Column("token_hash", sa.String(length=64), nullable=False),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("replaced_by", sa.String(length=64), nullable=True),
            sa.Column("revoked_reason", sa.String(length=32), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["user_id"], ["accounts_user.id"], ondelete="CASCADE"),
        )
        op.create_index(f"ix_{_TABLE}_user_id", _TABLE, ["user_id"])
        op.create_index(f"ix_{_TABLE}_token_hash", _TABLE, ["token_hash"], unique=True)


def downgrade() -> None:
    if _has_table(_TABLE):
        op.drop_index(f"ix_{_TABLE}_token_hash", table_name=_TABLE)
        op.drop_index(f"ix_{_TABLE}_user_id", table_name=_TABLE)
        op.drop_table(_TABLE)

    if _has_column("accounts_user", "token_version"):
        with op.batch_alter_table("accounts_user") as batch:
            batch.drop_column("token_version")
