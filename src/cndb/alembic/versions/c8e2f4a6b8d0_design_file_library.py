"""design_file_library —— 设计文件库与装配约束（ADR 0086 P0）.

Revision ID: c8e2f4a6b8d0
Revises: a7c1d2e3f4b5
Create Date: 2026-11-02 14:00:00.000000

- ``design_design``：升级为「设计文件」——新增 ``kind`` / ``file_key`` / ``folder`` /
  ``dependencies`` / ``dependencies_stale`` / ``refactored_from_version``；唯一键从
  ``(workspace_id, title)`` 换为 ``(workspace_id, folder, title)`` + ``(workspace_id, file_key)``
  （folder 缺省空串时对存量行为不变）；
- ``design_designversion``：新增 ``dependencies`` 依赖闭包快照（I5 可复现）；
- 新表 ``design_designref``：当前直接引用索引（删除阻断，C3）。

存量零迁移：新列全部带 server_default；``file_key`` 回填 ``design-<id>``。
upgrade 幂等（逐列 / 逐约束检查），downgrade 可还原。
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "c8e2f4a6b8d0"
down_revision: str | Sequence[str] | None = "a7c1d2e3f4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DESIGN = "design_design"
_VERSION = "design_designversion"
_REF = "design_designref"

_OLD_TITLE_UNIQ = "uniq_design_design_title"
_FOLDER_TITLE_UNIQ = "uniq_design_design_folder_title"
_FILE_KEY_UNIQ = "uniq_design_design_file_key"

_NEW_DESIGN_COLUMNS: tuple[sa.Column[Any], ...] = (
    sa.Column[Any]("kind", sa.String(length=16), nullable=False, server_default="assembly"),
    sa.Column[Any]("file_key", sa.String(length=64), nullable=False, server_default=""),
    sa.Column[Any]("folder", sa.String(length=200), nullable=False, server_default=""),
    sa.Column[Any]("dependencies", sa.JSON(), nullable=False, server_default="[]"),
    sa.Column[Any]("dependencies_stale", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    sa.Column[Any]("refactored_from_version", sa.Integer(), nullable=True),
)


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _unique_names(table: str) -> set[str]:
    return {u["name"] for u in sa.inspect(op.get_bind()).get_unique_constraints(table) if u.get("name")}


def _add_columns_if_missing(table: str, columns: tuple[sa.Column[Any], ...]) -> None:
    existing = _columns(table)
    for column in columns:
        if column.name not in existing:
            op.add_column(table, column)


def upgrade() -> None:
    """升级设计表为文件库模型；幂等（列 / 约束已存在则跳过）."""
    if not _table_exists(_DESIGN) or not _table_exists("workspaces_workspace"):
        # design 表整表不存在，或 legacy 最小库缺 workspaces 表（batch 反射
        # design_design 的 FK 会失败）：均由启动期 create_all 按完整 ORM
        # 元数据兜底建表 / 补列，迁移只在存量完整库上换轨
        return

    _add_columns_if_missing(_DESIGN, _NEW_DESIGN_COLUMNS)

    # file_key 回填：存量行按 id 生成稳定 key（创建后不可变，I2）
    op.get_bind().execute(
        sa.text(f"UPDATE {_DESIGN} SET file_key = 'design-' || CAST(id AS TEXT) WHERE file_key = ''")  # nosec B608 - 常量表名
    )

    # 唯一键换轨：(workspace_id, title) → (workspace_id, folder, title) + (workspace_id, file_key)
    uniqs = _unique_names(_DESIGN)
    with op.batch_alter_table(_DESIGN) as batch:
        if _OLD_TITLE_UNIQ in uniqs:
            batch.drop_constraint(_OLD_TITLE_UNIQ, type_="unique")
        if _FOLDER_TITLE_UNIQ not in uniqs:
            batch.create_unique_constraint(_FOLDER_TITLE_UNIQ, ["workspace_id", "folder", "title"])
        if _FILE_KEY_UNIQ not in uniqs:
            batch.create_unique_constraint(_FILE_KEY_UNIQ, ["workspace_id", "file_key"])

    if _table_exists(_VERSION):
        _add_columns_if_missing(_VERSION, (sa.Column("dependencies", sa.JSON(), nullable=False, server_default="[]"),))

    _create_ref_table()


def _create_ref_table() -> None:
    """建引用索引表（幂等：已存在或前置表缺失时跳过，由 create_all 兜底）."""
    if _table_exists(_REF):
        return
    if not _table_exists("workspaces_workspace"):
        return
    op.create_table(
        _REF,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "design_id",
            sa.Integer(),
            sa.ForeignKey(f"{_DESIGN}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_design_id",
            sa.Integer(),
            sa.ForeignKey(f"{_DESIGN}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("design_id", "target_design_id", name="uniq_design_ref_pair"),
    )
    op.create_index("ix_design_designref_target", _REF, ["target_design_id"])
    op.create_index("ix_design_designref_ws", _REF, ["workspace_id"])


def downgrade() -> None:
    """还原为单文件模型（缺表 / 缺列时跳过）."""
    if _table_exists(_REF):
        op.drop_table(_REF)

    if _table_exists(_VERSION) and "dependencies" in _columns(_VERSION):
        with op.batch_alter_table(_VERSION) as batch:
            batch.drop_column("dependencies")

    if not _table_exists(_DESIGN) or not _table_exists("workspaces_workspace"):
        return
    # D12：重构过的设计从 refactored_from_version 版本行还原原文（旧代码读到 use 原文会编译失败）
    cols = _columns(_DESIGN)
    if "refactored_from_version" in cols and _table_exists(_VERSION):
        op.get_bind().execute(
            sa.text(
                f"UPDATE {_DESIGN} SET"  # nosec B608 - 常量表名
                f" content = (SELECT v.content FROM {_VERSION} v"
                " WHERE v.design_id = design_design.id AND v.version_number = design_design.refactored_from_version),"
                f" compiled = (SELECT v.compiled FROM {_VERSION} v"
                " WHERE v.design_id = design_design.id AND v.version_number = design_design.refactored_from_version)"
                " WHERE refactored_from_version IS NOT NULL"
                " AND (SELECT v.content FROM design_designversion v"
                " WHERE v.design_id = design_design.id AND v.version_number = design_design.refactored_from_version) IS NOT NULL"
            )
        )
    # folder 清空后再恢复 (workspace_id, title) 唯一，避免目录分组造成的重名冲突
    op.get_bind().execute(sa.text(f"UPDATE {_DESIGN} SET folder = ''"))  # nosec B608 - 常量表名
    uniqs = _unique_names(_DESIGN)
    with op.batch_alter_table(_DESIGN) as batch:
        if _FILE_KEY_UNIQ in uniqs:
            batch.drop_constraint(_FILE_KEY_UNIQ, type_="unique")
        if _FOLDER_TITLE_UNIQ in uniqs:
            batch.drop_constraint(_FOLDER_TITLE_UNIQ, type_="unique")
        if _OLD_TITLE_UNIQ not in uniqs:
            batch.create_unique_constraint(_OLD_TITLE_UNIQ, ["workspace_id", "title"])
    existing = _columns(_DESIGN)
    with op.batch_alter_table(_DESIGN) as batch:
        for name in ("refactored_from_version", "dependencies_stale", "dependencies", "folder", "file_key", "kind"):
            if name in existing:
                batch.drop_column(name)
