"""add_design_drafts — 设计个人草稿表（保存与版本落库解耦）.

Revision ID: c1d2e3f4a5b7
Revises: b0c1d2e3f4a5
Create Date: 2026-11-08 09:00:00.000000

ADR 0125：3s 自动保存此前每次都落一条 ``design_designversion``，版本序列被
过程态淹没。本迁移新增 ``design_designdraft``：自动保存只写个人草稿，
手动保存 / 10 分钟检查点才落版本。每位用户对每份设计至多一份，随设计或
用户级联删除；存量表与数据零改动。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b7"
down_revision: Union[str, Sequence[str], None] = "b0c1d2e3f4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "design_designdraft"
_TS_DEFAULT = sa.text("(CURRENT_TIMESTAMP)")


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过，兼容 create_all 时代旧库）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建 design_designdraft 表与唯一约束 / 索引."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("design_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_size", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("content_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("base_version_number", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.ForeignKeyConstraint(["design_id"], ["design_design.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["accounts_user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("design_id", "user_id", name="uniq_design_draft_design_user"),
    )
    # 与 ORM 的 index=True 对齐：按设计查草稿 / 按用户清理
    op.create_index(f"ix_{_TABLE}_design_id", _TABLE, ["design_id"])
    op.create_index(f"ix_{_TABLE}_user_id", _TABLE, ["user_id"])


def downgrade() -> None:
    """删除设计草稿表（不触碰 design_design / design_designversion）."""
    if not _table_exists(_TABLE):
        return
    op.drop_table(_TABLE)
