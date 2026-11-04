"""add_workspace_templates —— 工作区模板与生命周期（需求 0094 P1）.

Revision ID: 134adcb233cb
Revises: f1a2b3c4d5e6
Create Date: 2026-11-05 10:00:00.000000

- ``workspaces_template``：模板定义（spec 为经过校验的 JSON，version 递增）；
- ``workspaces_templaterevision``：每次保存的版本快照（diff / 审计）；
- ``workspaces_workspace`` 新增 4 列：模板引用、同步版本、当前阶段、实例化映射。

纯新增表 / 可空列，存量工作区回填 ``template_state='{}'``；upgrade 幂等。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "134adcb233cb"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TEMPLATE = "workspaces_template"
_REVISION = "workspaces_templaterevision"
_WORKSPACE = "workspaces_workspace"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _column_exists(table: str, column: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table in inspector.get_table_names() and column in {col["name"] for col in inspector.get_columns(table)}


def upgrade() -> None:
    """建模板两表并给工作区补模板 / 阶段列（幂等）."""
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

    # SQLite 的 ALTER TABLE 不支持给存量表补外键，这里只加标量列 + 索引；
    # ORM 侧仍声明 FK（PostgreSQL 新库由 create_all 建出完整约束）。
    # 缺表（极简 stub 库）整体跳过，由 create_all / 自愈补建。
    if not _table_exists(_WORKSPACE):
        return
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


def downgrade() -> None:
    """删除新增列与模板两表（幂等）."""
    if _table_exists(_WORKSPACE):
        if _column_exists(_WORKSPACE, "template_state"):
            with op.batch_alter_table(_WORKSPACE) as batch:
                batch.drop_column("template_state")
        if _column_exists(_WORKSPACE, "template_stage"):
            with op.batch_alter_table(_WORKSPACE) as batch:
                batch.drop_column("template_stage")
        if _column_exists(_WORKSPACE, "template_version"):
            with op.batch_alter_table(_WORKSPACE) as batch:
                batch.drop_column("template_version")
        if _column_exists(_WORKSPACE, "template_id"):
            op.drop_index("ix_workspaces_workspace_template_id", table_name=_WORKSPACE)
            with op.batch_alter_table(_WORKSPACE) as batch:
                batch.drop_column("template_id")
    if _table_exists(_REVISION):
        op.drop_table(_REVISION)
    if _table_exists(_TEMPLATE):
        op.drop_table(_TEMPLATE)
