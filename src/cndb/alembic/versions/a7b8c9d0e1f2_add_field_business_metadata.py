"""add_field_business_metadata — 字段业务元数据（ADR 0188 P1）.

新增 6 列到 ``tables_datafield``，全部可空（存量行保持 NULL = 「未填写」）：

- ``business_meaning``  业务口径（该字段算的是什么、含不含税等）
- ``unit``              计量单位
- ``sensitivity``       敏感级（``public`` / ``internal`` / ``confidential``，NULL 视为 internal）
- ``owner_id``          字段责任人（FK accounts_user.id，删号置空）
- ``standard_ref``      标准来源（标准字段库 / 规范条目引用）
- ``example_value``     示例值（数据字典可读性最强的一项）

幂等：列已存在即跳过（全量建库后 stamp 回旧版重放的场景）；downgrade 删列还原。
存量零迁移：旧行读出为空，导出口径输出「未填写」，行为与升级前一致。
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | Sequence[str] | None = "e0f1a2b3c4d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "tables_datafield"

#: 列名 → 列定义（升级 / 降级都按列是否存在做幂等）
_COLUMNS: tuple[tuple[str, sa.Column[Any]], ...] = (
    ("business_meaning", sa.Column("business_meaning", sa.Text(), nullable=True)),
    ("unit", sa.Column("unit", sa.String(length=32), nullable=True)),
    ("sensitivity", sa.Column("sensitivity", sa.String(length=16), nullable=True)),
    ("owner_id", sa.Column("owner_id", sa.Integer(), nullable=True)),
    ("standard_ref", sa.Column("standard_ref", sa.String(length=255), nullable=True)),
    ("example_value", sa.Column("example_value", sa.String(length=255), nullable=True)),
)


def _column_names(table: str) -> set[str] | None:
    """表存在时返回列名集合；表不存在返回 None（残缺库升级时跳过）."""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    """补 6 列（已存在则跳过）；owner_id 额外补索引."""
    columns = _column_names(_TABLE)
    if columns is None:
        return
    for name, column in _COLUMNS:
        if name in columns:
            continue
        op.add_column(_TABLE, column)
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    if "ix_tables_datafield_owner_id" not in indexes:
        op.create_index("ix_tables_datafield_owner_id", _TABLE, ["owner_id"])


def downgrade() -> None:
    """删索引与 6 列，回到 ADR 0188 P1 之前的库结构（列不存在时跳过）."""
    columns = _column_names(_TABLE)
    if columns is None:
        return
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(_TABLE)}
    if "ix_tables_datafield_owner_id" in indexes:
        op.drop_index("ix_tables_datafield_owner_id", table_name=_TABLE)
    for name, _column in _COLUMNS:
        if name not in columns:
            continue
        op.drop_column(_TABLE, name)
