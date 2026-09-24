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
    UniqueConstraint,
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
        if not ft.has_physical_column:
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
    """在数据库中创建物理表（幂等：已存在则跳过），link 字段同步创建关联表."""
    if table_exists(engine, table.db_table_name):
        logger.debug("物理表已存在，跳过 CREATE TABLE: %s", table.db_table_name)
    else:
        metadata = MetaData()
        sa_table = build_sa_table(metadata, table)
        metadata.create_all(engine)
        logger.info("物理表已创建: %s（%d 个字段）", table.db_table_name, len(sa_table.columns) - 1)

    for field in table.active_fields():
        if field.field_type == "link":
            create_link_table(engine, field)


# ── ALTER TABLE: ADD COLUMN ─────────────────────────


def add_column(engine: Any, table: DataTable, field: DataField) -> None:
    """为物理表新增一列；link 字段改为创建关联物理表.

    策略：
    - PostgreSQL 等：直接 ALTER TABLE ADD COLUMN
    - SQLite：SQLite 3.35+ (2021-03-12) 支持 ALTER TABLE ADD COLUMN
      但不支持 AFTER 子句，新列自动追加到表尾
    """
    ft = default_registry.get(field.field_type)
    if ft is None:
        raise ValueError(f"未知字段类型: {field.field_type}")

    if not ft.has_physical_column:
        create_link_table(engine, field)
        return

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
    """从物理表删除一列；link 字段改为删除关联物理表.

    SQLite 兼容策略：
    - SQLite 3.35+ 支持 ALTER TABLE DROP COLUMN，直接用
    - 更老版本：需要重建表（读取现有 schema → 建新表 → 迁移数据 → 删旧表 → 重命名）
      此函数暂只支持 3.35+，低版本场景由上游捕获异常后升级驱动处理
    """
    ft = default_registry.get(field.field_type)
    if ft is not None and not ft.has_physical_column:
        drop_link_table(engine, field)
        return

    sql = f'ALTER TABLE "{table.db_table_name}" DROP COLUMN "{field.db_column_name}"'
    with engine.begin() as conn:
        conn.execute(text(sql))
    logger.info("物理表 %s 删除列: %s", table.db_table_name, field.db_column_name)


# ── 关联物理表（link 字段的多对多存储） ───────────────


def create_link_table(engine: Any, field: DataField) -> None:
    """创建关联字段的关联物理表：(row_id, target_row_id) 多对多，唯一约束防重复关联."""
    name = field.link_table_name
    if table_exists(engine, name):
        logger.debug("关联物理表已存在，跳过创建: %s", name)
        return
    metadata = MetaData()
    Table(
        name,
        metadata,
        Column("id", Integer, primary_key=True, autoincrement=True),
        Column("row_id", Integer, nullable=False, index=True),
        Column("target_row_id", Integer, nullable=False, index=True),
        UniqueConstraint("row_id", "target_row_id", name=f"uniq_{name}"),
    )
    metadata.create_all(engine)
    logger.info("关联物理表已创建: %s（字段 %s）", name, field.name)


def drop_link_table(engine: Any, field: DataField) -> None:
    """删除关联字段的关联物理表."""
    drop_table(engine, field.link_table_name)


# ── DROP TABLE ───────────────────────────────────────


def drop_table(engine: Any, db_table_name: str) -> None:
    """删除物理表（幂等：不存在则跳过）."""
    if not table_exists(engine, db_table_name):
        logger.debug("物理表不存在，跳过 DROP TABLE: %s", db_table_name)
        return
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE IF EXISTS "{db_table_name}"'))
    logger.info("物理表已删除: %s", db_table_name)


# ── is_unique 物理唯一索引 ────────────────────────────


def _unique_index_name(table_name: str, column_name: str) -> str:
    """唯一索引命名：idx_uniq_{table}_{col}（截断到 SQLite 64 字符限制内）."""
    raw = f"idx_u_{table_name}_{column_name}"
    if len(raw) > 60:
        raw = raw[:57] + ".."
    return raw


def add_unique_constraint(engine: Any, table: DataTable, field: DataField) -> None:
    """为字段创建物理唯一索引（SQLite / PostgreSQL 通用）.

    已存在则跳过（幂等）；数据冲突时抛异常由上层处理.
    """
    ft = default_registry.get(field.field_type)
    if ft is None or not ft.has_physical_column:
        # link 等无物理列字段不支持唯一约束
        logger.debug("字段 %s 无物理列，跳过唯一约束", field.name)
        return

    idx_name = _unique_index_name(table.db_table_name, field.db_column_name)
    insp = inspect(engine)
    existing_idx_names = {idx["name"] for idx in insp.get_indexes(table.db_table_name)}
    if idx_name in existing_idx_names:
        logger.debug("唯一索引 %s 已存在，跳过", idx_name)
        return

    sql = f'CREATE UNIQUE INDEX "{idx_name}" ON "{table.db_table_name}" ("{field.db_column_name}")'
    with engine.begin() as conn:
        conn.execute(text(sql))
    logger.info("唯一索引已创建: %s (%s.%s)", idx_name, table.db_table_name, field.db_column_name)


def drop_unique_constraint(engine: Any, table: DataTable, field: DataField) -> None:
    """移除字段的物理唯一索引（幂等：不存在则跳过）."""
    ft = default_registry.get(field.field_type)
    if ft is None or not ft.has_physical_column:
        return

    idx_name = _unique_index_name(table.db_table_name, field.db_column_name)
    insp = inspect(engine)
    existing_idx_names = {idx["name"] for idx in insp.get_indexes(table.db_table_name)}
    if idx_name not in existing_idx_names:
        logger.debug("唯一索引 %s 不存在，跳过删除", idx_name)
        return

    sql = f'DROP INDEX IF EXISTS "{idx_name}"'
    with engine.begin() as conn:
        conn.execute(text(sql))
    logger.info("唯一索引已删除: %s", idx_name)


# ── 数据巡检（字段变更保存前预检） ─────────────────────


def find_null_rows(engine: Any, table: DataTable, field: DataField, limit: int = 20) -> list[int]:
    """返回该物理列值为 NULL 的行 id 列表（含软删行，物理 NOT NULL 对全表生效）.

    用于把字段设为必填前的数据预检；物理表不存在或字段无物理列时返回空列表.
    """
    ft = default_registry.get(field.field_type)
    if ft is None or not ft.has_physical_column:
        return []
    if not table_exists(engine, table.db_table_name):
        return []

    sql = text(
        f'SELECT id FROM "{table.db_table_name}" WHERE "{field.db_column_name}" IS NULL ORDER BY id LIMIT :limit'  # nosec B608 - 标识符来自内部元数据
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"limit": limit}).all()
    return [int(r[0]) for r in rows]


def find_duplicate_values(
    engine: Any, table: DataTable, field: DataField, limit: int = 10
) -> list[tuple[Any, list[int]]]:
    """返回 (重复值, 行 id 列表) 列表；NULL 不参与判重（唯一索引允许多个 NULL）.

    用于启用唯一约束前的数据预检；物理表不存在或字段无物理列时返回空列表.
    """
    ft = default_registry.get(field.field_type)
    if ft is None or not ft.has_physical_column:
        return []
    if not table_exists(engine, table.db_table_name):
        return []

    sql = text(
        f'SELECT "{field.db_column_name}", GROUP_CONCAT(id) FROM "{table.db_table_name}" '  # nosec B608 - 标识符来自内部元数据
        f'WHERE "{field.db_column_name}" IS NOT NULL '
        f'GROUP BY "{field.db_column_name}" HAVING COUNT(*) > 1 ORDER BY MIN(id) LIMIT :limit'
    )
    with engine.connect() as conn:
        rows = conn.execute(sql, {"limit": limit}).all()

    result: list[tuple[Any, list[int]]] = []
    for value, ids_raw in rows:
        ids = [int(x) for x in str(ids_raw).split(",") if x]
        result.append((value, ids))
    return result


# ── 列变更检测与物理重建 ──────────────────────────────


def _not_null_placeholder(col_type: Any) -> str:
    """按 SQLAlchemy 列类型推导 ADD COLUMN NOT NULL 时的 DDL 合规默认值字面量.

    数值/布尔用 0，其余（字符串/日期等）用空串；仅作 SQLite DDL 合规占位。
    """
    try:
        py_type = col_type.python_type
    except (NotImplementedError, TypeError):
        return "''"
    if py_type in (int, float, bool):
        return "0"
    return "''"


def _column_needs_rebuild(old_field: DataField, new_field: DataField) -> bool:
    """判断字段变更是否需要物理列重建.

    以下变更需要重建：
    - field_type 改变（SQLAlchemy 类型或长度可能变了）
    - required 从 False 改为 True（SQLite 不支持 ALTER COLUMN）
    """
    return old_field.field_type != new_field.field_type or (
        old_field.required != new_field.required and new_field.required
    )


def rebuild_column(engine: Any, table: DataTable, old_field: DataField, new_field: DataField) -> None:
    """SQLite 兼容的列重建：rename → create → copy → drop → rename.

    步骤：
    1. 把旧列改名为 _{col}_bak
    2. 用新定义 ADD COLUMN 新列（原列名）
    3. 把旧列数据复制到新列（做必要的类型转换）
    4. DROP COLUMN 旧列（备份列）

    PostgreSQL 等支持 ALTER COLUMN 的引擎暂不走此路径（add_column 直接 ADD 即可）。
    """
    ft_old = default_registry.get(old_field.field_type)
    ft_new = default_registry.get(new_field.field_type)
    if ft_old is None or not ft_old.has_physical_column:
        raise ValueError(f"旧字段 {old_field.name} 无物理列，无法重建")
    if ft_new is None or not ft_new.has_physical_column:
        raise ValueError(f"新字段 {new_field.name} 无物理列，无法重建")

    old_col = old_field.db_column_name
    new_col = new_field.db_column_name
    bak_col = f"{old_col}_bak"

    col = ft_new.make_column(new_col, nullable=not new_field.required)
    col_def = f'"{col.name}" {col.type.compile(engine.dialect)}'
    if not col.nullable:
        col_def += " NOT NULL"
        # SQLite 约束：ADD COLUMN 的 NOT NULL 列必须带非 NULL 默认值，否则直接报错。
        # 应用层 required 校验保证实际写入总是提供值，此默认值仅为 DDL 合规占位，
        # 仅在未来 INSERT 缺省该列时兜底生效（copy 步骤会覆盖所有存量行）。
        col_def += f" DEFAULT {_not_null_placeholder(col.type)}"

    with engine.begin() as conn:
        # 1. rename old → bak
        conn.execute(text(f'ALTER TABLE "{table.db_table_name}" RENAME COLUMN "{old_col}" TO "{bak_col}"'))
        # 2. add new
        conn.execute(text(f'ALTER TABLE "{table.db_table_name}" ADD COLUMN {col_def}'))
        # 3. copy data（做宽松类型转换：CASE WHEN）
        conn.execute(
            text(
                f'UPDATE "{table.db_table_name}" SET "{new_col}" = CAST("{bak_col}" AS {col.type.compile(engine.dialect)}) '  # nosec B608 - 标识符来自内部元数据
                f'WHERE "{bak_col}" IS NOT NULL'
            )
        )
        # 4. drop bak column
        try:
            conn.execute(text(f'ALTER TABLE "{table.db_table_name}" DROP COLUMN "{bak_col}"'))
        except Exception as exc:  # pragma: no cover - 低版本 SQLite 兜底
            logger.warning("删除备份列 %s 失败（低版本 SQLite？）: %s", bak_col, exc)

    logger.info(
        "物理列已重建: %s.%s (%s → %s)",
        table.db_table_name,
        new_col,
        old_field.field_type,
        new_field.field_type,
    )


# ── 快速入口（从 engine 字符串创建 engine） ────────────


def get_engine(database_url: str) -> Any:
    """创建 SQLAlchemy Engine（统一入口，集中 connect_args 处理）."""
    if database_url.startswith("sqlite"):
        return create_engine(database_url, connect_args={"check_same_thread": False})
    return create_engine(database_url)


__all__ = [
    "_column_needs_rebuild",
    "add_column",
    "add_unique_constraint",
    "build_sa_table",
    "create_link_table",
    "create_table",
    "drop_column",
    "drop_link_table",
    "drop_table",
    "drop_unique_constraint",
    "find_duplicate_values",
    "find_null_rows",
    "get_engine",
    "rebuild_column",
    "table_exists",
]
