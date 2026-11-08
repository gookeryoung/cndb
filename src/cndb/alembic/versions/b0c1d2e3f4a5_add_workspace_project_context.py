"""工作区项目上下文（ADR 0122 P0）.

新增 ``workspaces_workspace.project_mode``（默认 workspace，存量零回填）与
项目状态表 ``workspaces_workspace_project_state``、项目文档映射表
``workspaces_workspace_project_document``。upgrade / downgrade 均幂等。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b0c1d2e3f4a5"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WS = "workspaces_workspace"
_STATE = "workspaces_workspace_project_state"
_DOC = "workspaces_workspace_project_document"


def _table_exists(table: str) -> bool:
    """目标表是否存在（缺失则由启动期 create_all 兜底）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    """目标列是否存在（幂等：重复执行 upgrade 不报错）."""
    insp = sa.inspect(op.get_bind())
    return column in {col["name"] for col in insp.get_columns(table)}


def upgrade() -> None:
    """新增项目模式列与两张项目级表."""
    # 缺表时整表由启动期 create_all 兜底，本迁移跳过（与既有迁移口径一致）
    if not _table_exists(_WS):
        return

    if not _column_exists(_WS, "project_mode"):
        op.add_column(
            _WS,
            sa.Column("project_mode", sa.String(length=16), nullable=False, server_default="workspace"),
        )

    if not _table_exists(_STATE):
        op.create_table(
            _STATE,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("project_row_id", sa.Integer(), nullable=False),
            sa.Column("stage_key", sa.String(length=64), nullable=False),
            sa.Column("history", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces_workspace.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("workspace_id", "project_row_id", name="uniq_workspace_project_state"),
        )
        op.create_index("ix_workspaces_workspace_project_state_workspace_id", _STATE, ["workspace_id"])
        op.create_index("ix_workspaces_workspace_project_state_stage_key", _STATE, ["stage_key"])

    if _table_exists("documents_document") and not _table_exists(_DOC):
        op.create_table(
            _DOC,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("project_row_id", sa.Integer(), nullable=False),
            sa.Column("doc_key", sa.String(length=64), nullable=False),
            sa.Column("document_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces_workspace.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["document_id"], ["documents_document.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "workspace_id", "project_row_id", "doc_key", name="uniq_workspace_project_document"
            ),
        )
        op.create_index("ix_workspaces_workspace_project_document_workspace_id", _DOC, ["workspace_id"])
        op.create_index("ix_workspaces_workspace_project_document_project_row_id", _DOC, ["project_row_id"])
        op.create_index("ix_workspaces_workspace_project_document_document_id", _DOC, ["document_id"])


def downgrade() -> None:
    """按依赖序回退（表 / 列不存在则跳过）."""
    if _table_exists(_DOC):
        op.drop_table(_DOC)
    if _table_exists(_STATE):
        op.drop_table(_STATE)
    if _table_exists(_WS) and _column_exists(_WS, "project_mode"):
        op.drop_column(_WS, "project_mode")
