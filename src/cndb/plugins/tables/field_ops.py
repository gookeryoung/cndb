"""字段层公共操作 —— 跨表字段克隆、冲突校验、批量 DDL 加列.

本模块抽取 copy_table 和新字段导入路由共用的字段 schema 复制逻辑，
让"复制整表"、"从其他表引入字段"、"基于模板建表"三类场景复用同一套
字段克隆 + 物理列创建流程。

语义约定：
- 克隆只复制 schema（field_type/config/required/is_unique/default_value/hidden），
  新字段拥有独立的 db_column_name 与生命周期，与源字段无后续关联；
- link 字段的 config.target_table_id 保留原值（link 字段天然支持跨工作区关联），
  但会校验目标表存在性，不存在时拒绝该 link 字段的克隆；
- 字段顺序：按源字段在源表的展示顺序（order, id）复制，目标表已有字段时从当前最大 order 后追加；
- 冲突（同名字段）由调用方决定是跳过还是报错 —— 提供两个 API：
  `validate_field_import_conflicts` 抛错版，`plan_field_import` 返回计划版。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cndb.plugins.tables import ddl as _ddl
from cndb.plugins.tables.links import is_link_field
from cndb.plugins.tables.models import DataField, DataTable, generate_db_column_name

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


# ── 字段筛选 ─────────────────────────────────────────


def resolve_source_fields(
    src_table: DataTable,
    *,
    field_ids: list[int] | None = None,
    field_names: list[str] | None = None,
    exclude_trashed: bool = True,
) -> list[DataField]:
    """按 field_ids 或 field_names 从源表筛选要克隆的字段.

    Args:
        src_table: 源数据表元数据.
        field_ids: 指定字段 id 列表；None 时按 field_names 或全量.
        field_names: 指定字段名列表；field_ids 提供时被忽略.
        exclude_trashed: 是否排除已进回收站的字段.

    Returns:
        按源表展示顺序排列的字段列表.

    Raises:
        ValueError: 指定的 field_ids 或 field_names 在源表中不存在.
    """
    pool: list[DataField] = [f for f in src_table.fields if not (exclude_trashed and f.trashed)]

    if field_ids:
        id_set = set(field_ids)
        selected: list[DataField] = [f for f in pool if f.id in id_set]
        missing = id_set - {f.id for f in selected}
        if missing:
            raise ValueError(f"源表不存在这些字段 id: {sorted(missing)}")
        # 按传入 field_ids 顺序输出
        order_index = {fid: idx for idx, fid in enumerate(field_ids)}
        selected.sort(key=lambda f: order_index[f.id])  # type: ignore[implicit-any-lambda]
        return selected

    if field_names:
        name_set = set(field_names)
        selected = [f for f in pool if f.name in name_set]
        missing = name_set - {f.name for f in selected}
        if missing:
            raise ValueError(f"源表不存在这些字段名: {sorted(missing)}")
        # 按传入 field_names 顺序输出
        order_index = {name: idx for idx, name in enumerate(field_names)}
        selected.sort(key=lambda f: order_index[f.name])  # type: ignore[implicit-any-lambda]
        return selected

    # 未指定则取全部（按展示顺序）
    selected = sorted(pool, key=lambda f: (f.order, f.id))  # type: ignore[implicit-any-lambda]
    return selected


# ── 冲突校验 ─────────────────────────────────────────


def validate_field_import_conflicts(dst_table: DataTable, src_fields: list[DataField]) -> None:
    """校验目标表是否可接收这批源字段 —— 同名字段视为冲突.

    Raises:
        ValueError: 目标表已存在同名字段时抛出，附带冲突字段名列表.
    """
    existing_names = {f.name for f in dst_table.fields if not f.trashed}
    conflicts = [f.name for f in src_fields if f.name in existing_names]
    if conflicts:
        raise ValueError(f"目标表已存在同名字段: {conflicts}")


def validate_link_targets_exist(src_fields: list[DataField], db: Session) -> None:
    """校验 link 字段引用的 target_table_id 在数据库中仍存在.

    Raises:
        ValueError: 某个 link 字段的 target_table_id 不存在.
    """
    for f in src_fields:
        if not is_link_field(f):
            continue
        tid = (f.config or {}).get("target_table_id")
        if tid is None:
            continue
        target = db.get(DataTable, tid)
        if target is None:
            raise ValueError(f"源字段 {f.name!r} 是 link 类型，其 target_table_id={tid} 在数据库中不存在，无法克隆")


# ── 规划 ─────────────────────────────────────────────


def plan_field_import(
    dst_table: DataTable,
    src_fields: list[DataField],
    *,
    start_order: int | None = None,
) -> tuple[list[DataField], list[str]]:
    """规划字段导入：计算冲突、分配目标字段的 order.

    Args:
        dst_table: 目标数据表.
        src_fields: 已从源表筛选好的待克隆字段.
        start_order: 起始 order —— None 时取目标表当前最大 order + 1.

    Returns:
        (计划创建的 DataField 列表（未提交、未分配 id）, 被跳过的原因说明列表).
    """
    existing_names = {f.name for f in dst_table.fields if not f.trashed}
    if start_order is None:
        current_max = max((f.order for f in dst_table.fields if not f.trashed), default=-1)
        start_order = current_max + 1

    plan: list[DataField] = []
    skipped: list[str] = []
    for idx, src in enumerate(src_fields):
        if src.name in existing_names:
            skipped.append(f"{src.name} — 目标表已存在同名字段，跳过")
            continue
        plan.append(
            DataField(
                table_id=dst_table.id,
                name=src.name,
                field_type=src.field_type,
                config=dict(src.config) if src.config else {},
                required=src.required,
                is_unique=src.is_unique,
                default_value=src.default_value,
                hidden=src.hidden,
                order=start_order + idx,
            )
        )
    return plan, skipped


# ── 执行 ─────────────────────────────────────────────


def execute_field_import(
    engine: Any,
    db: Session,
    dst_table: DataTable,
    src_fields: list[DataField],
    *,
    skip_conflicts: bool = False,
) -> list[DataField]:
    """执行字段克隆：元数据 + DDL 物理列.

    Args:
        engine: SQLAlchemy engine（用于 DDL）.
        db: SQLAlchemy Session（用于元数据持久化）.
        dst_table: 目标数据表.
        src_fields: 待克隆的源字段列表.
        skip_conflicts: True 时跳过同名字段（返回列表中不含被跳过字段）；
            False 时同名冲突直接抛 ValueError.

    Returns:
        成功创建并持久化（含 db_column_name）的 DataField 列表.

    Raises:
        ValueError: link 字段的 target_table_id 不存在，或同名冲突且 skip_conflicts=False.
        RuntimeError: DDL 物理加列失败.
    """
    validate_link_targets_exist(src_fields, db)

    if skip_conflicts:
        plan, _skipped = plan_field_import(dst_table, src_fields)
    else:
        validate_field_import_conflicts(dst_table, src_fields)
        plan, _skipped = plan_field_import(dst_table, src_fields)

    if not plan:
        logger.info("[field_ops] 没有可克隆的字段，跳过")
        return []

    # 分配物理列名 + 持久化 metadata
    for f in plan:
        f.ensure_db_name()
        db.add(f)
    db.commit()
    # 重新加载拿到 db_column_name 等完整属性
    for f in plan:
        db.refresh(f)

    # 批量物理加列
    created: list[DataField] = []
    try:
        for f in plan:
            _ddl.add_column(engine, dst_table, f)
            if f.is_unique:
                _ddl.add_unique_constraint(engine, dst_table, f)
            created.append(f)
    except Exception:
        db.rollback()
        # 已成功加列的需要回滚 DDL —— 简单起见这里直接抛错让上层决定
        raise

    logger.info("[field_ops] 从源表克隆 %d 个字段到 %s", len(created), dst_table.name)
    return created


# ── 便捷入口 ─────────────────────────────────────────


def clone_fields_between_tables(
    engine: Any,
    db: Session,
    src_table: DataTable,
    dst_table: DataTable,
    *,
    field_ids: list[int] | None = None,
    field_names: list[str] | None = None,
    exclude_trashed: bool = True,
    skip_conflicts: bool = False,
) -> tuple[list[DataField], list[str]]:
    """一站式：筛选 → 校验 → 规划 → 执行，返回 (创建的字段列表, 跳过说明).

    Raises:
        ValueError: 字段不存在 / link target 不存在 / 同名冲突（且 skip_conflicts=False）.
    """
    src_fields = resolve_source_fields(
        src_table,
        field_ids=field_ids,
        field_names=field_names,
        exclude_trashed=exclude_trashed,
    )
    validate_link_targets_exist(src_fields, db)

    if skip_conflicts:
        plan, skipped = plan_field_import(dst_table, src_fields)
    else:
        validate_field_import_conflicts(dst_table, src_fields)
        plan, skipped = plan_field_import(dst_table, src_fields)

    if not plan:
        return [], skipped

    for f in plan:
        f.ensure_db_name()
        db.add(f)
    db.commit()
    for f in plan:
        db.refresh(f)

    try:
        created: list[DataField] = []
        for f in plan:
            _ddl.add_column(engine, dst_table, f)
            if f.is_unique:
                _ddl.add_unique_constraint(engine, dst_table, f)
            created.append(f)
    except Exception:
        db.rollback()
        raise
    return created, skipped


def generate_column_name() -> str:
    """生成唯一的物理列名（对外暴露 generate_db_column_name 的别名，便于字段克隆场景调用）."""
    return generate_db_column_name()


__all__ = [
    "clone_fields_between_tables",
    "execute_field_import",
    "generate_column_name",
    "plan_field_import",
    "resolve_source_fields",
    "validate_field_import_conflicts",
    "validate_link_targets_exist",
]
