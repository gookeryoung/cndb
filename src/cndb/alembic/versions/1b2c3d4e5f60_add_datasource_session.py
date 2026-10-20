"""add_datasource_session — 凭证会话 + 任务限流（ADR 0006 M5）.

Revision ID: 1b2c3d4e5f60
Revises: 0a1b2c3d4e5f
Create Date: 2026-10-20 13:00:00.000000

- 新建 ``datasource_session``：集中管理请求头与密钥（密钥不随导出，读接口只回显键名）
- ``datasource_sync_job`` 增 ``session_id``（会话引用，SET NULL）与 ``rate_limit_ms``（相邻请求最小间隔）

全部幂等：表 / 列已存在就跳过；downgrade 反向移除，存量数据零迁移。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1b2c3d4e5f60"
down_revision: str | Sequence[str] | None = "0a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSION = "datasource_session"
_JOB = "datasource_sync_job"
_JOB_SESSION_INDEX = f"ix_{_JOB}_session_id"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {column["name"] for column in insp.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema: 建会话表并为任务补 session_id / rate_limit_ms（幂等）."""
    if not _table_exists(_SESSION):
        op.create_table(
            _SESSION,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column(
                "workspace_id",
                sa.Integer(),
                sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_by",
                sa.Integer(),
                sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("headers", sa.JSON(), nullable=False),
            sa.Column("secrets", sa.JSON(), nullable=False),
        )
        op.create_index(f"ix_{_SESSION}_workspace_id", _SESSION, ["workspace_id"])
        op.create_index(f"ix_{_SESSION}_created_by", _SESSION, ["created_by"])

    if _table_exists(_JOB):
        columns = _columns(_JOB)
        if "session_id" not in columns:
            # SQLite 不支持 ALTER TABLE 加外键约束（"No support for ALTER of constraints"），
            # 且本项目主用 SQLite：该列在 SQLite 上按普通可空整数列添加，
            # 引用完整性由 ORM / 应用层（删除会话时显式解绑）保证；
            # 其它方言（PostgreSQL）正常带 FK。
            if op.get_bind().dialect.name == "sqlite":
                op.add_column(_JOB, sa.Column("session_id", sa.Integer(), nullable=True))
            else:
                op.add_column(
                    _JOB,
                    sa.Column(
                        "session_id",
                        sa.Integer(),
                        sa.ForeignKey(f"{_SESSION}.id", ondelete="SET NULL"),
                        nullable=True,
                    ),
                )
            op.create_index(_JOB_SESSION_INDEX, _JOB, ["session_id"])
        if "rate_limit_ms" not in columns:
            op.add_column(
                _JOB,
                sa.Column("rate_limit_ms", sa.Integer(), nullable=False, server_default="0"),
            )


def downgrade() -> None:
    """Downgrade schema: 移除任务两列并删除会话表（缺表缺列跳过）."""
    if _table_exists(_JOB):
        columns = _columns(_JOB)
        if "rate_limit_ms" in columns:
            op.drop_column(_JOB, "rate_limit_ms")
        if "session_id" in columns:
            op.drop_index(_JOB_SESSION_INDEX, table_name=_JOB)
            op.drop_column(_JOB, "session_id")
    if _table_exists(_SESSION):
        op.drop_index(f"ix_{_SESSION}_created_by", table_name=_SESSION)
        op.drop_index(f"ix_{_SESSION}_workspace_id", table_name=_SESSION)
        op.drop_table(_SESSION)
