"""add_documents_chart — 文档图表实例表（ADR 0048）.

Revision ID: e0f1a2b3c4d5
Revises: c4d5e6f7a8b9
Create Date: 2026-10-27 10:00:00.000000

文档正文新增 ``{{chart:<id>}}`` 引用：类别 / 模板是代码注册表，
用户自定义只落 ``documents_chart`` 实例行（template_key + config），
渲染在请求期完成（唯一渲染器，SVG / PNG 双写端）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e0f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CHART = "documents_chart"
_TS_DEFAULT = sa.text("(CURRENT_TIMESTAMP)")


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过，兼容 create_all 时代旧库）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建图表实例表."""
    if _table_exists(_CHART):
        return
    op.create_table(
        _CHART,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False, server_default=""),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces_workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_documents_chart_ws", _CHART, ["workspace_id"])


def downgrade() -> None:
    """删除图表实例表."""
    if _table_exists(_CHART):
        op.drop_table(_CHART)
