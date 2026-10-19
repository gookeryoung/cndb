"""add_workspace_storage_quota — Workspace 表新增存储配额列.

Revision ID: b9c0d1e2f3a4
Revises: b8c9d0e1f2a3
Create Date: 2026-10-19 10:00:00.000000

新增 ``workspaces_workspace.storage_quota_bytes``：单工作区存储配额（字节），
默认 100MB，由系统管理员在管理台「空间分配」中调整。加列带 server_default，
存量工作区自动获得默认配额；幂等加列兼容经 create_all 建表已含该列的旧库。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b9c0d1e2f3a4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# 默认配额：100 MB
_DEFAULT_QUOTA_BYTES = 100 * 1024 * 1024


def _table_exists(table: str) -> bool:
    """目标表是否存在（不存在则整表由启动 create_all 兜底，本迁移跳过）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """Upgrade schema: workspaces_workspace 加 storage_quota_bytes."""
    if not _table_exists("workspaces_workspace"):
        return
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("workspaces_workspace")}
    if "storage_quota_bytes" in cols:
        return
    op.add_column(
        "workspaces_workspace",
        sa.Column(
            "storage_quota_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=str(_DEFAULT_QUOTA_BYTES),
        ),
    )


def downgrade() -> None:
    """Downgrade schema: 移除 storage_quota_bytes 列（缺表或缺列时跳过）."""
    if not _table_exists("workspaces_workspace"):
        return
    insp = sa.inspect(op.get_bind())
    cols = {c["name"] for c in insp.get_columns("workspaces_workspace")}
    if "storage_quota_bytes" in cols:
        op.drop_column("workspaces_workspace", "storage_quota_bytes")
