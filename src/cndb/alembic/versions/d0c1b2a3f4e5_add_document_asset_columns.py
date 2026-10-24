"""add_document_asset_columns — 文档原件列（ADR 0025）.

Revision ID: d0c1b2a3f4e5
Revises: c9f1a2b3d4e5
Create Date: 2026-10-24 10:00:00.000000

PDF / Office / 图片原样存档：``asset_file_key`` 指向工作区上传目录中的原件，
``asset_mime`` 保存原件 MIME。两列均可不回填 —— 历史文档 NULL 即普通 Markdown。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0c1b2a3f4e5"
down_revision: str | Sequence[str] | None = "c9f1a2b3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "documents_document"


def _table_exists() -> bool:
    """表是否存在（迁移测试会在「表缺失」场景下升级到 head，需跳过）."""
    return _TABLE in sa.inspect(op.get_bind()).get_table_names()


def _columns() -> set[str]:
    """现有列名集合（幂等：重复执行时跳过已存在的列）."""
    return {col["name"] for col in sa.inspect(op.get_bind()).get_columns(_TABLE)}


def upgrade() -> None:
    """为文档表补充原件列."""
    if not _table_exists():
        return
    existing = _columns()
    with op.batch_alter_table(_TABLE) as batch:
        if "asset_file_key" not in existing:
            batch.add_column(sa.Column("asset_file_key", sa.String(255), nullable=True))
        if "asset_mime" not in existing:
            batch.add_column(
                sa.Column("asset_mime", sa.String(128), nullable=False, server_default=""),
            )


def downgrade() -> None:
    """移除原件列."""
    if not _table_exists():
        return
    existing = _columns()
    with op.batch_alter_table(_TABLE) as batch:
        if "asset_file_key" in existing:
            batch.drop_column("asset_file_key")
        if "asset_mime" in existing:
            batch.drop_column("asset_mime")
