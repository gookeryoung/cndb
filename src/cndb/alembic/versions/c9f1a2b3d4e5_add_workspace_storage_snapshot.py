"""add_workspace_storage_snapshot — 工作区存储用量快照（ADR 0024 P0）.

Revision ID: c9f1a2b3d4e5
Revises: 9d0e1f2a3b4c
Create Date: 2026-10-24 09:40:00.000000

- ``workspaces_storage_snapshot``：一工作区一行（``workspace_id`` 主键，随工作区
  级联删除），存后台刷新器算出的 ``used_bytes`` 与 ``computed_at`` / ``duration_ms``。
- 管理台「空间分配」、工作区详情与上传配额预判改读本表；缺行 = 尚未统计。
- upgrade 幂等（表已存在跳过）；downgrade 删表（数据可重建：刷新器会重新计算）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9f1a2b3d4e5"
down_revision: str | Sequence[str] | None = "9d0e1f2a3b4c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "workspaces_storage_snapshot"
_INDEX = "ix_workspaces_storage_snapshot_computed_at"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """建快照表（幂等：表已存在跳过）."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("used_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
    )
    op.create_index(_INDEX, _TABLE, ["computed_at"])


def downgrade() -> None:
    """删快照表（幂等：不存在跳过）."""
    if not _table_exists(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_index(_INDEX)
    op.drop_table(_TABLE)
