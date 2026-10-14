"""select / multiselect 选项的预填充、同步、检测与存量数据重写.

从 field_ops.py 拆出；对外仍通过 field_ops 转发，调用方与 monkeypatch 目标不变。
"""

from __future__ import annotations

import difflib
import logging
from typing import TYPE_CHECKING, Any

from cndb.plugins.tables.field_types import split_multi_select_string
from cndb.plugins.tables.models import DataField, DataTable

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


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

    from sqlalchemy import select as _sa_select

    from cndb.plugins.tables.services.core.ddl import get_reflected_table

    changed: list[DataField] = []
    select_fields = [f for f in table.active_fields() if f.field_type in ("select", "multiselect")]
    if not select_fields:
        return changed

    engine: _Any = db.get_bind()
    try:
        sa_table = get_reflected_table(engine, table.db_table_name)
    except RuntimeError:
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


def detect_options_from_field_data(
    db: Session,
    table: DataTable,
    field: DataField,
    *,
    target_type: str,
    delimiter: str = ",",
) -> list[str]:
    """扫描字段物理列存量数据，收集可作为 select/multiselect 选项的唯一值.

    字段类型修改为单选/多选时的「识别选项」入口：不做持久化，只返回识别结果，
    由前端把结果填入选项编辑器、用户确认后随 config 一并保存。
    识别发生在类型保存切换**之前**，物理列存的仍是旧类型数据，
    因此按调用方传入的目标类型（而非字段存量类型）决定拆分语义。

    Args:
        db: SQLAlchemy Session（用于反射物理表读取数据）.
        table: 字段所属数据表元数据.
        field: 待切换类型的字段（须有物理列；link/lookup 无物理列时抛错）.
        target_type: 目标字段类型，仅接受 "select" / "multiselect".
        delimiter: multiselect 识别分隔符，默认逗号；select 忽略该参数.

    Returns:
        按首现顺序排列的唯一值列表（已 strip、去空）.

    Raises:
        ValueError: target_type 不是 select/multiselect，或 multiselect 分隔符为空.
        RuntimeError: 物理表不存在或字段物理列缺失.
    """
    if target_type not in ("select", "multiselect"):
        raise ValueError(f"目标类型 {target_type!r} 不是单选/多选，无法识别选项")
    if target_type == "multiselect" and not delimiter:
        raise ValueError("多选识别分隔符不能为空")

    from sqlalchemy import select as _sa_select

    from cndb.plugins.tables.services.core.ddl import get_reflected_table

    engine: Any = db.get_bind()
    try:
        sa_table = get_reflected_table(engine, table.db_table_name)
    except RuntimeError as exc:
        raise RuntimeError(f"物理表 {table.db_table_name} 不存在，无法识别选项") from exc
    col = sa_table.c.get(field.db_column_name)
    if col is None:
        raise RuntimeError(f"物理表 {table.db_table_name} 缺少列 {field.db_column_name}，无法识别选项")

    query = _sa_select(col).distinct().where(col.isnot(None)).where(col != "")
    raw_values = [row[0] for row in db.execute(query).all()]

    collected: list[str] = []
    seen: set[str] = set()
    for rv in raw_values:
        if rv is None:
            continue
        if target_type == "multiselect":
            # 按用户指定的分隔符拆分（支持多字符分隔符），与识别预览语义一致
            parts = str(rv).split(delimiter)
            for p in parts:
                s = p.strip()
                if s and s not in seen:
                    seen.add(s)
                    collected.append(s)
        else:
            s = str(rv).strip()
            if s and s not in seen:
                seen.add(s)
                collected.append(s)
    return collected


# ── 选项变更 → 存量数据同步 ──────────────────────────


def _ordered_option_values(raw_options: list[Any] | None) -> list[str]:
    """按顺序提取选项 value 列表（与 _allowed_values_from_config 同一取值语义）.

    兼容三种历史形态：纯字符串 / dict（value 缺省回退 label）/ SelectOption 对象.
    """
    from cndb.plugins.tables.field_types.select import SelectOption

    values: list[str] = []
    for item in raw_options or []:
        if isinstance(item, dict):
            values.append(str(item.get("value", item.get("label", ""))))
        elif isinstance(item, SelectOption):
            values.append(str(item.value))
        else:
            values.append(str(item))
    return values


def diff_select_options(
    old_raw: list[Any] | None,
    new_raw: list[Any] | None,
) -> tuple[dict[str, str], list[str]]:
    """对比单选/多选字段的新旧选项，计算存量数据需要的迁移动作.

    语义约定（与前端选项编辑器"就地编辑"行为对齐）：
    - 改名：旧值消失 + 新值出现，且处于 SequenceMatcher 的同一 replace 段；
      等长段按顺序一一配对，不等长段按顺序配对 min(旧, 新) 个、多余旧值按删除；
      配对前再校验"旧值不在新列表、新值不在旧列表"，防止纯重排 / 重复值场景误判；
    - 删除：旧值在新列表中完全不存在且未配对成改名 → 引用该值的存量数据需清空；
    - 新增 / 纯重排 / 仅颜色调整 → 不产生任何数据迁移。

    Args:
        old_raw: 旧 config.options 原始列表（str / dict / SelectOption 混合）.
        new_raw: 新 config.options 原始列表.

    Returns:
        (rename_map: 旧值 → 新值, removed: 被移除的旧值列表，保序去重).
    """
    old_values = _ordered_option_values(old_raw)
    new_values = _ordered_option_values(new_raw)
    if old_values == new_values:
        return {}, []

    old_set, new_set = set(old_values), set(new_values)
    removed_set = old_set - new_set
    added_set = new_set - old_set

    rename_map: dict[str, str] = {}
    matcher = difflib.SequenceMatcher(a=old_values, b=new_values, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        # 不等长段（如"改名 + 删除相邻项"）按顺序配对 min(旧, 新) 个，多余旧值落删除
        pair_len = min(i2 - i1, j2 - j1)
        for k in range(pair_len):
            src, dst = old_values[i1 + k], new_values[j1 + k]
            # 双重保险：只有"真消失 → 真新增"才算改名，重排/重复值场景跳过
            if src in removed_set and dst in added_set:
                rename_map[src] = dst

    renamed_sources = set(rename_map)
    removed = [v for v in dict.fromkeys(old_values) if v in removed_set and v not in renamed_sources]
    return rename_map, removed


def _rewrite_select_column(db: Any, sa_table: Any, col: Any, rename_map: dict[str, str], removed: list[str]) -> int:
    """select 物理列：旧值整格改写为新值，被删值整格置 NULL.

    改名目标只可能来自"新增值"集合（与所有旧值不相交），逐条 UPDATE 无级联风险.

    Returns:
        受影响行数.
    """
    from sqlalchemy import update as _sa_update

    affected = 0
    for old_v, new_v in rename_map.items():
        result = db.execute(_sa_update(sa_table).where(col == old_v).values({col: new_v}))
        affected += max(result.rowcount or 0, 0)
    for v in removed:
        result = db.execute(_sa_update(sa_table).where(col == v).values({col: None}))
        affected += max(result.rowcount or 0, 0)
    return affected


def _rewrite_multiselect_rows(db: Any, sa_table: Any, col: Any, rename_map: dict[str, str], removed: list[str]) -> int:
    """multiselect 物理列：逐行拆分多值，套用改名/删除后重组写回.

    只改写确实引用了被改名/被删除选项的行；拆移后为空的行置 NULL。
    按主键逐行更新（executemany），避免中间态值与其他行原文碰撞造成误改。

    Returns:
        受影响行数.
    """
    from sqlalchemy import bindparam
    from sqlalchemy import select as _sa_select
    from sqlalchemy import update as _sa_update

    pk_cols = list(sa_table.primary_key.columns)
    if not pk_cols:
        logger.warning("[sync_select_data] 物理表 %s 无主键，跳过 multiselect 存量同步", sa_table.name)
        return 0
    pk_col = pk_cols[0]

    removed_set = set(removed)
    rows = db.execute(_sa_select(pk_col, col).where(col.isnot(None)).where(col != "")).all()

    updates: list[dict[str, Any]] = []
    for row_id, raw in rows:
        parts = split_multi_select_string(str(raw))
        if not any(p in removed_set or p in rename_map for p in parts):
            continue
        rewritten: list[str] = []
        seen: set[str] = set()
        for p in parts:
            if p in removed_set:
                continue
            v = rename_map.get(p, p)
            if v in seen:
                continue
            seen.add(v)
            rewritten.append(v)
        new_raw = ",".join(rewritten)
        if new_raw != str(raw):
            updates.append({"row_id": row_id, "new_value": new_raw if new_raw else None})

    if not updates:
        return 0

    db.execute(
        _sa_update(sa_table).where(pk_col == bindparam("row_id")).values({col: bindparam("new_value")}),
        updates,
    )
    return len(updates)


def sync_select_data_on_options_change(
    db: Any,
    table: DataTable,
    field: DataField,
    old_config: dict[str, Any] | None,
) -> int:
    """字段选项变更后，把存量数据同步到新选项（改名改写 / 删除清空）.

    - select：旧值整格改写为新值；被删值整格置 NULL；
    - multiselect：逐行拆分多值后套用迁移动作再重组，拆移后为空的行置 NULL。

    在调用方事务内执行 DML（不 commit），与字段 metadata 变更原子生效；
    供 update_field 路由在保存 config 的同一事务中调用。

    Args:
        db: SQLAlchemy Session（DML 挂在其事务上）.
        table: 字段所属数据表元数据.
        field: 已写入新 config 的字段对象.
        old_config: 变更前的字段 config 快照.

    Returns:
        受影响行数；无迁移动作或物理结构不可用时为 0.
    """
    from cndb.plugins.tables.services.core.ddl import get_reflected_table

    rename_map, removed = diff_select_options(
        (old_config or {}).get("options"),
        (field.config or {}).get("options"),
    )
    if not rename_map and not removed:
        return 0

    engine: Any = db.get_bind()
    try:
        sa_table = get_reflected_table(engine, table.db_table_name)
    except RuntimeError:
        logger.warning("[sync_select_data] 物理表 %s 不存在，跳过存量数据同步", table.db_table_name)
        return 0
    col = sa_table.c.get(field.db_column_name)
    if col is None:
        logger.warning(
            "[sync_select_data] 物理表 %s 缺少列 %s，跳过存量数据同步",
            table.db_table_name,
            field.db_column_name,
        )
        return 0

    if field.field_type == "multiselect":
        affected = _rewrite_multiselect_rows(db, sa_table, col, rename_map, removed)
    else:
        affected = _rewrite_select_column(db, sa_table, col, rename_map, removed)

    if affected:
        logger.info(
            "[sync_select_data] 字段 %s（表 %s）选项变更同步 %d 行存量数据（改名 %d 组，删除 %d 项）",
            field.name,
            table.name,
            affected,
            len(rename_map),
            len(removed),
        )
    return affected
