"""add_document_content_templates — 文档内容模板表（需求 0169）.

新增 ``documents_contenttemplate``：工作区级 Markdown 正文骨架，用于「从模板新建
文档」。与导出模板 ``documents_exporttemplate``（ADR 0152）完全独立，不预置内置行。

**存量零迁移**：新表无存量数据；downgrade 直接删表。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d9e0f1a2b3c5"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "documents_contenttemplate"


def _has_table() -> bool:
    """全量建库后再 stamp 回旧版重放迁移的测试场景，表已存在则跳过（幂等）."""
    return _TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    if _has_table():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=32), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("(CURRENT_TIMESTAMP)")
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces_workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("workspace_id", "name", name="uq_documents_contenttemplate_ws_name"),
    )


def downgrade() -> None:
    if _has_table():
        op.drop_table(_TABLE)
