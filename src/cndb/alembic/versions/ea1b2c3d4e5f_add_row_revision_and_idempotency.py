"""行级历史 + 写幂等键（ADR 0144 / 0145）.

Revision ID: ea1b2c3d4e5f
Revises: d1e2f3a4b5c6
Create Date: 2026-11-24 21:00:00.000000

新增两张元数据表（与动态物理表无关，存量数据零迁移）：

- ``tables_recordrevision``：行级历史版本（行 id + 版本号唯一），``diff`` 只存变化字段；
- ``tables_idempotencykey``：写请求幂等登记（用户 + key + 路由唯一）。

迁移可重入：表 / 唯一约束已存在时跳过；downgrade 可完整还原。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ea1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REVISION_TABLE = "tables_recordrevision"
_IDEMPOTENCY_TABLE = "tables_idempotencykey"


def _table_exists(bind: sa.engine.Connection, table: str) -> bool:
    return table in sa.inspect(bind).get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind, _REVISION_TABLE):
        op.create_table(
            _REVISION_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("table_id", sa.Integer(), sa.ForeignKey("tables_datatable.id", ondelete="CASCADE"), nullable=False),
            sa.Column("row_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("op", sa.String(length=16), nullable=False),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("accounts_user.id", ondelete="SET NULL"), nullable=True),
            sa.Column("actor_name", sa.String(length=150), nullable=True),
            sa.Column("diff", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("row_id", "version", name="uniq_recordrevision_row_version"),
        )
        op.create_index("ix_recordrevision_table_id", _REVISION_TABLE, ["table_id"])
        op.create_index("ix_recordrevision_row_id", _REVISION_TABLE, ["row_id"])
        op.create_index("ix_recordrevision_actor_id", _REVISION_TABLE, ["actor_id"])

    if not _table_exists(bind, _IDEMPOTENCY_TABLE):
        op.create_table(
            _IDEMPOTENCY_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("accounts_user.id", ondelete="CASCADE"), nullable=True),
            sa.Column("key", sa.String(length=128), nullable=False),
            sa.Column("route", sa.String(length=200), nullable=False),
            sa.Column("request_hash", sa.String(length=64), nullable=False),
            sa.Column("status_code", sa.Integer(), nullable=False),
            sa.Column("response", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("user_id", "key", "route", name="uniq_idempotency_user_key_route"),
        )
        op.create_index("ix_idempotency_user_id", _IDEMPOTENCY_TABLE, ["user_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if _table_exists(bind, _IDEMPOTENCY_TABLE):
        op.drop_table(_IDEMPOTENCY_TABLE)
    if _table_exists(bind, _REVISION_TABLE):
        op.drop_table(_REVISION_TABLE)
