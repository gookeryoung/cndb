"""复用模块库四表（ADR 0118 P0）.

新增 ``design_library_module`` / ``design_library_version`` /
``design_libraryref`` / ``design_library_vendor``；不改既有表、不回填数据。
upgrade / downgrade 均幂等。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "4c6e8a0b2d3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MODULE = "design_library_module"
_VERSION = "design_library_version"
_REF = "design_libraryref"
_VENDOR = "design_library_vendor"


def _table_exists(table: str) -> bool:
    """目标表是否存在（缺失则由启动期 create_all 兜底）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建四表与索引（已存在则跳过）."""
    if not _table_exists(_MODULE):
        op.create_table(
            _MODULE,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("module_key", sa.String(length=64), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("description", sa.String(length=500), nullable=False),
            sa.Column("visibility", sa.String(length=16), nullable=False),
            sa.Column("owner_workspace_id", sa.Integer(), nullable=True),
            sa.Column("source_design_id", sa.Integer(), nullable=True),
            sa.Column("is_archived", sa.Boolean(), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("updated_by_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["owner_workspace_id"], ["workspaces_workspace.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["source_design_id"], ["design_design.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["updated_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("module_key", name="uniq_design_library_module_key"),
        )
        op.create_index("ix_design_library_module_visibility_updated", _MODULE, ["visibility", "updated_at"])
        op.create_index("ix_design_library_module_owner", _MODULE, ["owner_workspace_id"])
        op.create_index("ix_design_library_module_created_by_id", _MODULE, ["created_by_id"])
        op.create_index("ix_design_library_module_updated_by_id", _MODULE, ["updated_by_id"])

    if not _table_exists(_VERSION):
        op.create_table(
            _VERSION,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("module_id", sa.Integer(), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("files", sa.JSON(), nullable=False),
            sa.Column("params", sa.JSON(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("bundle_hash", sa.String(length=64), nullable=False),
            sa.Column("comment", sa.String(length=200), nullable=False),
            sa.Column("created_by_id", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["module_id"], [f"{_MODULE}.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("module_id", "version_number", name="uniq_design_library_version"),
        )
        op.create_index("ix_design_library_version_module_id", _VERSION, ["module_id"])
        op.create_index("ix_design_library_version_created_by_id", _VERSION, ["created_by_id"])

    if not _table_exists(_REF):
        op.create_table(
            _REF,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("design_id", sa.Integer(), nullable=False),
            sa.Column("module_id", sa.Integer(), nullable=False),
            sa.Column("module_version_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces_workspace.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["design_id"], ["design_design.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["module_id"], [f"{_MODULE}.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["module_version_id"], [f"{_VERSION}.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("design_id", "module_version_id", name="uniq_design_libraryref_pair"),
        )
        op.create_index("ix_design_libraryref_module", _REF, ["module_id"])
        op.create_index("ix_design_libraryref_ws", _REF, ["workspace_id"])

    if not _table_exists(_VENDOR):
        op.create_table(
            _VENDOR,
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("workspace_id", sa.Integer(), nullable=False),
            sa.Column("module_key", sa.String(length=64), nullable=False),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("content_hash", sa.String(length=64), nullable=False),
            sa.Column("bundle_hash", sa.String(length=64), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("files", sa.JSON(), nullable=False),
            sa.Column("params", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["workspace_id"], ["workspaces_workspace.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "workspace_id",
                "module_key",
                "version_number",
                "content_hash",
                name="uniq_design_library_vendor_snapshot",
            ),
        )
        op.create_index("ix_design_library_vendor_ws", _VENDOR, ["workspace_id"])


def downgrade() -> None:
    """按依赖倒序删除四表（正文不回改；含 ``lib:`` 的设计在旧代码下不可编译）."""
    for table in (_REF, _VENDOR, _VERSION, _MODULE):
        if _table_exists(table):
            op.drop_table(table)
