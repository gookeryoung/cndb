"""add_datasource_sync — 周期性外部数据同步（任务定义 + 运行记录）.

Revision ID: 0a1b2c3d4e5f
Revises: e7f8a9b0c1d2
Create Date: 2026-10-20 11:00:00.000000

新增两张表（见 ADR 0006）：

- ``datasource_sync_job``  同步任务定义：Provider / 目标表 / 标的集合 / 幂等键 / 游标 / 调度 / 租约
- ``datasource_sync_run``  每次运行留痕：状态 / 游标区间 / 增删改计数 / 逐请求明细

幂等：表已存在则跳过（create_all 时代建过的库不再重复建）；
downgrade 先删索引再删表，可完整还原；存量数据零迁移。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB = "datasource_sync_job"
_RUN = "datasource_sync_run"


def _table_exists(table: str) -> bool:
    """目标表是否已存在（存在则整表跳过，保证迁移幂等）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema: 建同步任务表与运行记录表（幂等）."""
    if not _table_exists(_JOB):
        op.create_table(
            _JOB,
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
            sa.Column(
                "table_id",
                sa.Integer(),
                sa.ForeignKey("tables_datatable.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("name", sa.String(length=128), nullable=False),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("request_spec", sa.JSON(), nullable=False),
            sa.Column("parser", sa.String(length=32), nullable=False),
            sa.Column("entrant_param", sa.String(length=64), nullable=True),
            sa.Column("entrant_keys", sa.JSON(), nullable=False),
            sa.Column("match_keys", sa.JSON(), nullable=False),
            sa.Column("field_mapping", sa.JSON(), nullable=False),
            sa.Column("cursor", sa.JSON(), nullable=False),
            sa.Column("schedule", sa.JSON(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_status", sa.String(length=16), nullable=False, server_default=""),
            sa.Column("lease_owner", sa.String(length=64), nullable=True),
            sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index(f"ix_{_JOB}_workspace_id", _JOB, ["workspace_id"])
        op.create_index(f"ix_{_JOB}_created_by", _JOB, ["created_by"])
        op.create_index(f"ix_{_JOB}_table_id", _JOB, ["table_id"])
        op.create_index(f"ix_{_JOB}_enabled", _JOB, ["enabled"])
        op.create_index(f"ix_{_JOB}_lease_until", _JOB, ["lease_until"])

    if not _table_exists(_RUN):
        op.create_table(
            _RUN,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column(
                "job_id",
                sa.Integer(),
                sa.ForeignKey(f"{_JOB}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("trigger", sa.String(length=16), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("cursor_from", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("cursor_to", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("fetched", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("inserted", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=False, server_default=""),
            sa.Column("detail", sa.JSON(), nullable=False),
        )
        op.create_index(f"ix_{_RUN}_job_id", _RUN, ["job_id"])
        op.create_index(f"ix_{_RUN}_status", _RUN, ["status"])


def downgrade() -> None:
    """Downgrade schema: 删运行记录表与任务表（缺表则跳过）."""
    if _table_exists(_RUN):
        op.drop_index(f"ix_{_RUN}_status", table_name=_RUN)
        op.drop_index(f"ix_{_RUN}_job_id", table_name=_RUN)
        op.drop_table(_RUN)
    if _table_exists(_JOB):
        for index in (
            f"ix_{_JOB}_lease_until",
            f"ix_{_JOB}_enabled",
            f"ix_{_JOB}_table_id",
            f"ix_{_JOB}_created_by",
            f"ix_{_JOB}_workspace_id",
        ):
            op.drop_index(index, table_name=_JOB)
        op.drop_table(_JOB)
