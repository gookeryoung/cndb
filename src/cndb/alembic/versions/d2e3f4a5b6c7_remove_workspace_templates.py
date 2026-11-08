"""remove_workspace_templates — 移除工作区模板、数据流程与生命周期（需求 0094/0095/0097/0121/0122）.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b7
Create Date: 2026-11-09 10:00:00.000000

删除模板定义 / 版本快照、项目级状态 / 文档映射，以及工作区上的模板与项目模式列。
该类数据随功能移除不再保留；downgrade 只恢复结构（空表 / 默认值）。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2e3f4a5b6c7"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEMPLATE = "workspaces_template"
_REVISION = "workspaces_templaterevision"
_STATE = "workspaces_workspace_project_state"
_DOC = "workspaces_workspace_project_document"
_WORKSPACE = "workspaces_workspace"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names() and column in {col["name"] for col in inspector.get_columns(table)}


def _drop_column(table: str, column: str) -> None:
    """SQLite 需 batch 模式重建表，与既有迁移口径一致."""
    if _table_exists(table) and _column_exists(table, column):
        with op.batch_alter_table(table) as batch:
            batch.drop_column(column)


def upgrade() -> None:
    """按依赖序删除项目映射 / 状态、工作区列与模板表（幂等）."""
    if _table_exists(_DOC):
        op.drop_table(_DOC)
    if _table_exists(_STATE):
        op.drop_table(_STATE)

    if _table_exists(_WORKSPACE) and _column_exists(_WORKSPACE, "template_id"):
        op.drop_index("ix_workspaces_workspace_template_id", table_name=_WORKSPACE)
    for column in ("template_state", "template_stage", "template_version", "template_id", "project_mode"):
        _drop_column(_WORKSPACE, column)

    if _table_exists(_REVISION):
        op.drop_table(_REVISION)
    if _table_exists(_TEMPLATE):
        op.drop_table(_TEMPLATE)


def downgrade() -> None:
    """恢复模板 / 项目表与工作区列（结构与默认值，不恢复已删除数据）."""
    if not _table_exists(_TEMPLATE):
        op.create_table(
            _TEMPLATE,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("category", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("modules", sa.JSON(), nullable=False, server_default='["tables", "documents", "design"]'),
            sa.Column("spec", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column(
                "created_by_id",
                sa.Integer(),
                sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "updated_by_id",
                sa.Integer(),
                sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("name", name="uniq_workspace_template_name"),
        )
        op.create_index("ix_workspaces_template_name", _TEMPLATE, ["name"])
        op.create_index("ix_workspaces_template_created_by_id", _TEMPLATE, ["created_by_id"])
        op.create_index("ix_workspaces_template_updated_by_id", _TEMPLATE, ["updated_by_id"])

    if not _table_exists(_REVISION):
        op.create_table(
            _REVISION,
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "template_id",
                sa.Integer(),
                sa.ForeignKey(f"{_TEMPLATE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("spec", sa.JSON(), nullable=False),
            sa.Column("change_summary", sa.String(length=500), nullable=False, server_default=""),
            sa.Column(
                "created_by_id",
                sa.Integer(),
                sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("template_id", "version", name="uniq_workspace_template_version"),
        )
        op.create_index("ix_workspaces_templaterevision_template_id", _REVISION, ["template_id"])

    if _table_exists(_WORKSPACE):
        if not _column_exists(_WORKSPACE, "template_id"):
            op.add_column(_WORKSPACE, sa.Column("template_id", sa.Integer(), nullable=True))
            op.create_index("ix_workspaces_workspace_template_id", _WORKSPACE, ["template_id"])
        if not _column_exists(_WORKSPACE, "template_version"):
            op.add_column(_WORKSPACE, sa.Column("template_version", sa.Integer(), nullable=True))
        if not _column_exists(_WORKSPACE, "template_stage"):
            op.add_column(_WORKSPACE, sa.Column("template_stage", sa.String(length=64), nullable=True))
        if not _column_exists(_WORKSPACE, "template_state"):
            op.add_column(
                _WORKSPACE,
                sa.Column("template_state", sa.JSON(), nullable=False, server_default="{}"),
            )
        if not _column_exists(_WORKSPACE, "project_mode"):
            op.add_column(
                _WORKSPACE,
                sa.Column("project_mode", sa.String(length=16), nullable=False, server_default="workspace"),
            )

    if _table_exists(_WORKSPACE) and not _table_exists(_STATE):
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

    if _table_exists("documents_document") and _table_exists(_WORKSPACE) and not _table_exists(_DOC):
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
