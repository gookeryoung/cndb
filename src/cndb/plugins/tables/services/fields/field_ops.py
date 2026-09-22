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
- field_mapping 支持源字段 → 目标字段的重命名 / 跳过：
  ``{源字段名: 目标字段名}``，目标字段名为 None 时跳过该源字段。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cndb.plugins.tables.services.core import ddl as _ddl
from cndb.plugins.tables.services.importing.field_mapping import apply_user_mapping, build_default_mapping
from cndb.plugins.tables.field_types import split_multi_select_string
from cndb.plugins.tables.services.core.links import is_link_field
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
    field_mapping: dict[str, str | None] | None = None,
) -> tuple[list[DataField], list[str]]:
    """规划字段导入：按映射计算目标字段名、检测冲突、分配 order.

    Args:
        dst_table: 目标数据表.
        src_fields: 已从源表筛选好的待克隆字段.
        start_order: 起始 order —— None 时取目标表当前最大 order + 1.
        field_mapping: 可选的字段重命名 / 跳过映射。
            ``{源字段名: 目标字段名}``，目标名为 None 时跳过该源字段。
            未显式列出的源字段按 源名 == 目标名 处理（行为与不传 mapping 等价）。

    Returns:
        (计划创建的 DataField 列表（未提交、未分配 id）, 被跳过的原因说明列表).
    """
    existing_names = {f.name for f in dst_table.fields if not f.trashed}
    if start_order is None:
        current_max = max((f.order for f in dst_table.fields if not f.trashed), default=-1)
        start_order = current_max + 1

    # 1. 构造映射（默认源名 → 同名，用户覆盖）
    src_names = [f.name for f in src_fields]
    mapping: dict[str, str] = build_default_mapping(src_names)
    if field_mapping:
        mapping = apply_user_mapping(mapping, field_mapping, src_names)

    # 2. 目标名冲突预扫：包括目标表已有字段 + 本次计划内重复目标名
    planned_dst_names: set[str] = set()
    plan: list[DataField] = []
    skipped: list[str] = []
    for idx, src in enumerate(src_fields):
        if src.name not in mapping:
            # 用户显式跳过
            skipped.append(f"{src.name} — 用户通过 field_mapping 指定跳过")
            continue

        dst_name = mapping[src.name]

        # 目标表已有同名字段
        if dst_name in existing_names:
            if dst_name == src.name:
                skipped.append(f"{src.name} — 目标表已存在同名字段，跳过")
            else:
                skipped.append(f"{src.name} → {dst_name} — 目标表已存在字段 {dst_name!r}，跳过")
            continue

        # 本次计划内重复目标名
        if dst_name in planned_dst_names:
            skipped.append(f"{src.name} → {dst_name} — 已有另一个源字段也映射到 {dst_name!r}，跳过")
            continue

        planned_dst_names.add(dst_name)
        plan.append(
            DataField(
                table_id=dst_table.id,
                name=dst_name,
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
    field_mapping: dict[str, str | None] | None = None,
) -> list[DataField]:
    """执行字段克隆：元数据 + DDL 物理列.

    Args:
        engine: SQLAlchemy engine（用于 DDL）.
        db: SQLAlchemy Session（用于元数据持久化）.
        dst_table: 目标数据表.
        src_fields: 待克隆的源字段列表.
        skip_conflicts: True 时跳过同名字段（返回列表中不含被跳过字段）；
            False 时同名冲突直接抛 ValueError.
        field_mapping: 可选的字段重命名 / 跳过映射 — 见 :func:`plan_field_import`.

    Returns:
        成功创建并持久化（含 db_column_name）的 DataField 列表.

    Raises:
        ValueError: link 字段的 target_table_id 不存在，或同名冲突且 skip_conflicts=False.
        RuntimeError: DDL 物理加列失败.
    """
    validate_link_targets_exist(src_fields, db)

    if skip_conflicts:
        plan, _skipped = plan_field_import(dst_table, src_fields, field_mapping=field_mapping)
    else:
        # 有 mapping 时冲突延后到 plan_field_import 内处理（因为重命名后可能恰好避冲突）
        # 不传 mapping 时沿用原有"同名冲突即报错"行为
        if not field_mapping:
            validate_field_import_conflicts(dst_table, src_fields)
        plan, _skipped = plan_field_import(dst_table, src_fields, field_mapping=field_mapping)

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
    field_mapping: dict[str, str | None] | None = None,
) -> tuple[list[DataField], list[str]]:
    """一站式：筛选 → 校验 → 规划 → 执行，返回 (创建的字段列表, 跳过说明).

    Args:
        field_mapping: 可选的字段重命名 / 跳过映射 — 见 :func:`plan_field_import`.

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
        plan, skipped = plan_field_import(dst_table, src_fields, field_mapping=field_mapping)
    else:
        if not field_mapping:
            validate_field_import_conflicts(dst_table, src_fields)
        plan, skipped = plan_field_import(dst_table, src_fields, field_mapping=field_mapping)

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


# ── select / multiselect options 自动补全 ────────────


def _merge_new_options(
    field: DataField,
    new_values: list[str],
) -> bool:
    """把 new_values 合并到 field.config.options，保持已有项不变.

    去重逻辑：label 或 value 任一已存在 → 跳过.

    Returns:
        True 表示 config 有变更.
    """
    from typing import Any as _Any

    from cndb.plugins.tables.field_types.smart_color import suggest_colors

    existing_options: list[dict[str, _Any]] = []
    config = field.config or {}
    for item in config.get("options", []) or []:
        if isinstance(item, str):
            existing_options.append({"label": item, "value": item, "color": ""})
        elif isinstance(item, dict):
            label = str(item.get("label", ""))
            val = item.get("value", label)
            existing_options.append(
                {
                    "label": label,
                    "value": val,
                    "color": str(item.get("color", "")),
                }
            )

    existing_labels = {o["label"] for o in existing_options}
    existing_values = {str(o["value"]) for o in existing_options}

    new_labels: list[str] = []
    seen_new: set[str] = set()
    for v in new_values:
        if not v or v in seen_new:
            continue
        if v in existing_labels or v in existing_values:
            continue
        seen_new.add(v)
        new_labels.append(v)

    if not new_labels:
        return False

    # 让新增选项避开已有选项已占用的颜色（既有 color 可能是用户手动设置或历史推荐值），
    # 保证导入追加的选项与存量选项在颜色上尽量区分
    existing_used = {o["color"] for o in existing_options if o["color"]}
    new_colors = suggest_colors(new_labels, used_colors=existing_used)
    new_options = [{"label": label, "value": label, "color": new_colors[i]} for i, label in enumerate(new_labels)]
    merged = existing_options + new_options

    new_config = dict(config)
    new_config["options"] = merged
    field.config = new_config
    return True


def _extract_values_from_rows(
    field: DataField,
    rows: list[dict[str, Any]],
) -> list[str]:
    """从待导入行数据中提取某 select/multiselect 字段出现过的所有唯一值.

    multiselect 字段的值如果是 list → 直接展开；如果是逗号分隔字符串 → split.
    """
    collected: list[str] = []
    seen: set[str] = set()
    field_name = field.name

    for row in rows:
        raw = row.get(field_name)
        if raw is None:
            continue

        if field.field_type == "multiselect":
            # list 值直接展开（JSON 导入格式）；字符串按分隔符拆分，
            # 与 validate_value 共用同一分隔符集，保证预填充选项与校验一致
            if isinstance(raw, list):
                items = [str(item).strip() if item is not None else "" for item in raw]
            else:
                items = split_multi_select_string(str(raw))
            for p in items:
                if p and p not in seen:
                    seen.add(p)
                    collected.append(p)
        else:
            s = str(raw).strip()
            if s and s not in seen:
                seen.add(s)
                collected.append(s)

    return collected


def prefill_select_options_from_rows(
    db: Session,
    table: DataTable,
    rows: list[dict[str, Any]],
) -> list[DataField]:
    """从待导入行数据中预填充 select / multiselect 字段的 options.

    bulk_create **之前**调用：扫描行数据中 select/multiselect 字段出现过的
    所有唯一值，合并到 config.options（保持已有项，新值追加），这样
    FieldType.validate_value 校验就能通过.

    Args:
        db: SQLAlchemy Session（用于持久化 DataField.config）.
        table: 目标数据表元数据.
        rows: 待导入行（list[dict]，键为源字段名）.

    Returns:
        config 有变更的 DataField 列表（已 commit）.
    """
    select_fields = [f for f in table.active_fields() if f.field_type in ("select", "multiselect")]
    if not select_fields or not rows:
        return []

    changed: list[DataField] = []
    for field in select_fields:
        values = _extract_values_from_rows(field, rows)
        if not values:
            continue
        if _merge_new_options(field, values):
            changed.append(field)

    if changed:
        db.commit()
        logger.info(
            "[prefill_select_options] 为表 %s 的 %d 个字段预填充了 options",
            table.name,
            len(changed),
        )

    return changed


def sync_select_options_from_table(db: Session, table: DataTable) -> list[DataField]:
    """从物理表数据中自动补全 select / multiselect 字段的 config.options.

    导入完成后调用：扫描表中所有 select / multiselect 类型字段，
    从物理表里收集该列所有非空值，与现有 config.options 合并
    （保持已有选项顺序和 color 不变，新值追加到末尾并自动智能配色）.

    用于覆盖**存量行**中的值（prefill 只处理本轮新导入的行数据）.

    Args:
        db: SQLAlchemy Session（用于读取物理表 + 持久化 DataField.config）.
        table: 目标数据表元数据.

    Returns:
        config 有变更的 DataField 列表（已 commit）.
    """
    from typing import Any as _Any

    from sqlalchemy import MetaData
    from sqlalchemy import select as _sa_select

    changed: list[DataField] = []
    select_fields = [f for f in table.active_fields() if f.field_type in ("select", "multiselect")]
    if not select_fields:
        return changed

    engine: _Any = db.get_bind()
    metadata = MetaData()
    metadata.reflect(bind=engine, only=[table.db_table_name])
    sa_table = metadata.tables.get(table.db_table_name)
    if sa_table is None:
        logger.warning("[sync_select_options] 物理表 %s 不存在，跳过", table.db_table_name)
        return changed

    for field in select_fields:
        col = sa_table.c.get(field.db_column_name)
        if col is None:
            continue

        query = _sa_select(col).distinct().where(col.isnot(None)).where(col != "")
        raw_values = [row[0] for row in db.execute(query).all()]

        collected: list[str] = []
        seen: set[str] = set()
        for rv in raw_values:
            if rv is None:
                continue
            if field.field_type == "multiselect":
                # 与 validate_value 共用同一分隔符集，保证同步选项与校验一致
                parts = split_multi_select_string(str(rv))
                for p in parts:
                    if p not in seen:
                        seen.add(p)
                        collected.append(p)
            else:
                s = str(rv).strip()
                if s and s not in seen:
                    seen.add(s)
                    collected.append(s)

        if not collected:
            continue

        if _merge_new_options(field, collected):
            changed.append(field)

    if changed:
        db.commit()
        logger.info(
            "[sync_select_options] 为表 %s 的 %d 个字段从存量数据补全了 options",
            table.name,
            len(changed),
        )

    return changed


__all__ = [
    "clone_fields_between_tables",
    "execute_field_import",
    "generate_column_name",
    "plan_field_import",
    "resolve_source_fields",
    "sync_select_options_from_table",
    "validate_field_import_conflicts",
    "validate_link_targets_exist",
]
