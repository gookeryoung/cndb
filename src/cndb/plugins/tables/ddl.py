"""动态 DDL 引擎 —— SQLAlchemy Core 驱动的物理表管理.

核心职责：
1. 根据 DataTable metadata + DataField 列表构建 SQLAlchemy Table 对象（sa.Table）
2. 在目标数据库执行 CREATE TABLE / ALTER TABLE / DROP TABLE
3. 处理 SQLite / PostgreSQL 的 DDL 差异（SQLite 不原生支持 DROP COLUMN）

不使用 Alembic 管理动态物理表（Alembic 只管元数据表）；
动态物理表完全由本模块在运行时直接执行 DDL.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    Table,
    create_engine,
    inspect,
    text,
)

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = logging.getLogger(__name__)


# ── sa.Table 构建 ─────────────────────────────────────


def build_sa_table(
    metadata: MetaData,
    table: DataTable,
    fields: Iterable[DataField] | None = None,
    *,
    include_trashed: bool = False,
    extra_columns: Iterable[Column[Any]] | None = None,
) -> Table:
    """从 DataTable metadata + DataField 列表构建 SQLAlchemy Table 对象（不在 DB 中执行 DDL）.

    生成的物理表包含：
    - id 主键（自增 Integer）
    - 每个 DataField 对应的 Column（由 field_types 解释）
    - created_at / updated_at（可选，若业务侧不需要可传 extra_columns 覆盖）
    - 软删除标记: _trashed (Boolean) + _trashed_at (DateTime nullable)

    Args:
        metadata: SQLAlchemy MetaData（用于注册 Table）.
        table: DataTable 元数据对象.
        fields: 字段列表；None 时用 table.active_fields().
        include_trashed: 是否包含已进回收站的字段.
        extra_columns: 额外补充的 Column（如 created_at/updated_at）.
    """
    cols: list[Column[Any]] = [Column("id", Integer, primary_key=True, autoincrement=True)]

    if fields is None:
        fields = table.fields

    for f in fields:
        if not include_trashed and f.trashed:
            continue
        ft = default_registry.get(f.field_type)
        if ft is None:
            logger.warning("未知字段类型 %s，跳过字段 %s", f.field_type, f.name)
            continue
        col = ft.make_column(f.db_column_name, nullable=not f.required)
        cols.append(col)

    # 软删除字段
    from sqlalchemy import Boolean
    from sqlalchemy import DateTime as SA_DateTime

    cols.append(Column("_trashed", Boolean, nullable=False, server_default="0"))
    cols.append(Column("_trashed_at", SA_DateTime(timezone=True), nullable=True))

    if extra_columns:
        cols.extend(extra_columns)

    return Table(table.db_table_name, metadata, *cols, extend_existing=True)


# ── 物理表存在性检查 ─────────────────────────────────


def table_exists(engine: Any, db_table_name: str) -> bool:
    """检查数据库中是否存在指定物理表."""
    insp = inspect(engine)
    return db_table_name in insp.get_table_names()


# ── CREATE TABLE ─────────────────────────────────────


def create_table(engine: Any, table: DataTable) -> None:
    """在数据库中创建物理表（幂等：已存在则跳过）."""
    if table_exists(engine, table.db_table_name):
        logger.debug("物理表已存在，跳过 CREATE TABLE: %s", table.db_table_name)
        return

    metadata = MetaData()
    sa_table = build_sa_table(metadata, table)
    metadata.create_all(engine)
    logger.info("物理表已创建: %s（%d 个字段）", table.db_table_name, len(sa_table.columns) - 1)


# ── ALTER TABLE: ADD COLUMN ─────────────────────────


def add_column(engine: Any, table: DataTable, field: DataField) -> None:
    """为物理表新增一列.

    策略：
    - PostgreSQL 等：直接 ALTER TABLE ADD COLUMN
    - SQLite：SQLite 3.35+ (2021-03-12) 支持 ALTER TABLE ADD COLUMN
      但不支持 AFTER 子句，新列自动追加到表尾
    """
    ft = default_registry.get(field.field_type)
    if ft is None:
        raise ValueError(f"未知字段类型: {field.field_type}")

    col = ft.make_column(field.db_column_name, nullable=not field.required)

    # 构建列定义字符串
    col_def = f'"{col.name}" {col.type.compile(engine.dialect)}'
    if not col.nullable:
        col_def += " NOT NULL"
    if col.default is not None:
        col_def += f" DEFAULT {col.default}"

    sql = f'ALTER TABLE "{table.db_table_name}" ADD COLUMN {col_def}'
    with engine.begin() as conn:
        conn.execute(text(sql))
    logger.info("物理表 %s 新增列: %s (%s)", table.db_table_name, field.db_column_name, field.name)


# ── ALTER TABLE: DROP COLUMN ────────────────────────


def drop_column(engine: Any, table: DataTable, field: DataField) -> None:
    """从物理表删除一列.

    SQLite 兼容策略：
    - SQLite 3.35+ 支持 ALTER TABLE DROP COLUMN，直接用
    - 更老版本：需要重建表（读取现有 schema → 建新表 → 迁移数据 → 删旧表 → 重命名）
      此函数暂只支持 3.35+，低版本场景由上游捕获异常后升级驱动处理
    """
    sql = f'ALTER TABLE "{table.db_table_name}" DROP COLUMN "{field.db_column_name}"'
    with engine.begin() as conn:
        conn.execute(text(sql))
    logger.info("物理表 %s 删除列: %s", table.db_table_name, field.db_column_name)


# ── DROP TABLE ───────────────────────────────────────


def drop_table(engine: Any, db_table_name: str) -> None:
    """删除物理表（幂等：不存在则跳过）."""
    if not table_exists(engine, db_table_name):
        logger.debug("物理表不存在，跳过 DROP TABLE: %s", db_table_name)
        return
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{db_table_name}"'))
    logger.info("物理表已删除: %s", db_table_name)


# ── 快速入口（从 engine 字符串创建 engine） ────────────


def get_engine(database_url: str) -> Any:
    """创建 SQLAlchemy Engine（统一入口，集中 connect_args 处理）."""
    if database_url.startswith("sqlite"):
        return create_engine(database_url, connect_args={"check_same_thread": False})
    return create_engine(database_url)


__all__ = [
    "add_column",
    "build_sa_table",
    "create_table",
    "drop_column",
    "drop_table",
    "get_engine",
    "table_exists",
]
