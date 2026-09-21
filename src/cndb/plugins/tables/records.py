"""行 CRUD 引擎 —— 基于动态 sa.Table 的数据读写.

核心职责：
- create_row / get_row / update_row / delete_row（单行）
- list_rows（列表查询，支持筛选/排序/分页）
- bulk_create / bulk_update / bulk_delete（批量）
- trash_row / restore_row（软删除/恢复）

所有写入值都经过 field_types 的 validate_value 规范化后才入库；
link 字段值（目标行 id 列表）不占物理列，经 _split_links 拆出后由 links 模块写入关联表，
读取时由 links.attach_links 附加摘要列表 [{"id", "value"}].
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import MetaData, Table, and_, func, or_, select

from cndb.plugins.tables.audit import (
    ACTION_CREATE,
    ACTION_DELETE,
    ACTION_RESTORE,
    ACTION_TRASH,
    ACTION_UPDATE,
    log_action,
)
from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.links import (
    attach_links,
    clear_row_links,
    ensure_link_targets_exist,
    is_link_field,
    set_links,
)
from cndb.plugins.tables.models import DataField, DataTable

logger = logging.getLogger(__name__)


# ── 值规范化 ──────────────────────────────────────────


def _normalize_values(
    table: DataTable,
    values: dict[str, Any],
    *,
    for_update: bool = False,
) -> tuple[dict[str, Any], list[tuple[DataField, list[int]]]]:
    """把前端传入的 {field_name: raw_value} 转为 {db_column_name: normalized_value}.

    - 根据 DataField.field_type 调用 validate_value 做类型强转和校验
    - link 字段不产生物理列值，拆分为 (DataField, 目标 id 列表) 由调用方写入关联表；
      值为 None 表示显式清空，归一为空列表
    - 跳过 None（除非 required 字段）
    - 字段不存在于 table.fields 时忽略（安全起见不报错）
    - date/datetime 字段的 auto_fill 自动填充（on_create 创建时补、on_update 每次都覆盖）
    - DataField.default_value 默认值填充（仅创建路径、用户未传该字段时；校验失败跳过）

    返回 (物理列值, 关联值列表)。
    """
    from cndb.plugins.tables.field_types import DateFieldConfig

    field_map: dict[str, DataField] = {f.name: f for f in table.fields}
    result: dict[str, Any] = {}
    link_values: list[tuple[DataField, list[int]]] = []

    for field_name, raw in values.items():
        f = field_map.get(field_name)
        if f is None or f.trashed:
            logger.debug("未知字段 %s，跳过", field_name)
            continue
        ft = default_registry.get(f.field_type)
        if ft is None:
            raise ValueError(f"未知字段类型: {f.field_type}")
        if is_link_field(f):
            ids = ft.validate_value(raw, f.config) if raw is not None else []
            link_values.append((f, ids))
            continue
        if raw is None:
            if f.required and not for_update:  # pragma: no cover - 必填校验分支
                raise ValueError(f"必填字段 {field_name} 不能为空")
            continue
        try:
            result[f.db_column_name] = ft.validate_value(raw, f.config)
        except Exception as exc:
            raise ValueError(f"字段 {field_name}({f.field_type}) 值校验失败: {exc}") from exc

    # ── date/datetime auto_fill 自动填充 ──
    for f in table.fields:
        if f.trashed or is_link_field(f):
            continue
        if f.field_type not in ("date", "datetime"):
            continue
        ft = default_registry.get(f.field_type)
        if ft is None:
            continue
        try:
            cfg = DateFieldConfig(**(f.config or {}))
        except Exception:
            continue
        if not cfg.should_auto_fill(for_update=for_update):
            continue
        auto_val = ft.default_value(f.config or {})
        if auto_val is None:
            continue
        if cfg.auto_fill == "on_update":
            # 更新时间戳：强制覆盖（即使用户传了值也覆盖）
            result[f.db_column_name] = auto_val
        elif cfg.auto_fill == "on_create" and f.db_column_name not in result:
            # 创建时间戳：仅当用户未传入时补值
            result[f.db_column_name] = auto_val

    # ── DataField.default_value 默认值填充（仅创建、用户未传该字段时）──
    if not for_update:
        for f in table.fields:
            if f.trashed or is_link_field(f):
                continue
            if f.name in values:
                # 用户显式传过（含 None 清空意图）则不覆盖
                continue
            dv = f.default_value
            if dv is None or dv == "":
                continue
            ft = default_registry.get(f.field_type)
            if ft is None:
                continue
            try:
                result[f.db_column_name] = ft.validate_value(dv, f.config or {})
            except Exception as exc:
                # 默认值配置非法时不阻塞建行，跳过并留调试日志
                logger.debug("字段 %s 默认值 %r 校验失败，跳过: %s", f.name, dv, exc)

    # 检查缺失的必填字段（link 字段无物理列，不参与）
    if not for_update:
        for f in table.fields:
            if f.trashed or not f.required or is_link_field(f):
                continue
            if f.db_column_name not in result:
                raise ValueError(f"必填字段 {f.name} 不能为空")

    return result, link_values


# ── 单表 sa.Table 获取（带缓存） ─────────────────────


def _apply_auto_increment_defaults(
    engine: Any,
    table: DataTable,
    values: dict[str, Any],
    normalized: dict[str, Any],
    assigned: dict[int, list[str]] | None = None,
) -> None:
    """把单行文本自动编号默认值写入 normalized（仅创建路径调用）.

    规则：
    - 字段 trashed / link / 用户显式传过（含 None 清空意图）→ 跳过
    - 字段类型不支持自动编号（next_increment_value 返回 None）→ 跳过
    - 自动编号优先于静态 default_value（两者同时配置时编号覆盖静态默认值）
    - assigned 记录本批次已分配编号（批量创建逐行传递，保证连续递增不重复）
    """
    for f in table.fields:
        if f.trashed or is_link_field(f) or f.name in values:
            continue
        ft = default_registry.get(f.field_type)
        if ft is None:
            continue
        next_val = ft.next_increment_value(engine, table, f, extra_seen=assigned.get(f.id, []) if assigned else ())
        if next_val is None:
            continue
        try:
            normalized[f.db_column_name] = ft.validate_value(next_val, f.config or {})
        except Exception as exc:
            # 自动编号生成异常不阻塞建行，留调试日志
            logger.debug("字段 %s 自动编号 %r 校验失败，跳过: %s", f.name, next_val, exc)
            continue
        if assigned is not None:
            assigned.setdefault(f.id, []).append(next_val)


def _get_sa_table(engine: Any, table: DataTable) -> Table:
    """获取已存在的物理表 sa.Table 对象.

    优先从 engine.dialect 反射；不存在则抛异常（create_table 应先被调用）.
    """
    metadata = MetaData()
    metadata.reflect(bind=engine, only=[table.db_table_name])
    if table.db_table_name not in metadata.tables:
        raise RuntimeError(f"物理表 {table.db_table_name} 不存在，请先调用 create_table()")
    return metadata.tables[table.db_table_name]


# ── CREATE ───────────────────────────────────────────


def create_row(
    engine: Any,
    table: DataTable,
    values: dict[str, Any],
    db: Any = None,
) -> dict[str, Any] | None:
    """创建一行，返回完整行数据（含自增 id 和默认值字段）；link 字段同步写关联表."""
    sa_table = _get_sa_table(engine, table)
    normalized, link_values = _normalize_values(table, values)
    _apply_auto_increment_defaults(engine, table, values, normalized)

    # 主行提交前预校验 link 目标存在，避免主行已入库但 link 写入失败返回 500
    if db is not None:
        for field, ids in link_values:
            if ids:
                ensure_link_targets_exist(engine, field, ids, db)

    with engine.begin() as conn:
        if normalized:
            result = conn.execute(sa_table.insert().values(**normalized))
        else:
            # 行仅有 link 值（无物理列值）：显式写软删标记保证 INSERT 合法
            result = conn.execute(sa_table.insert().values(_trashed=False))
        row_id = result.lastrowid

    for field, target_ids in link_values:
        set_links(engine, field, row_id, target_ids, db=db)

    row = get_row(engine, table, row_id, db=db)
    if row is not None:
        try:
            log_action(db, table, ACTION_CREATE, target_id=row_id, detail=row)
        except Exception as exc:
            logger.debug("audit create_row 失败: %s", exc)
    return row


# ── READ ─────────────────────────────────────────────


def get_row(
    engine: Any,
    table: DataTable,
    row_id: int,
    db: Any = None,
    *,
    user: Any = None,
) -> dict[str, Any] | None:
    """按主键读取单行，返回 dict；不存在返回 None（含软删除过滤 + 行级权限 + 字段隐藏）."""
    sa_table = _get_sa_table(engine, table)
    row_scope = _build_row_scope_where(table, sa_table, db)
    where = [sa_table.c.id == row_id, sa_table.c._trashed.is_(False)]
    if row_scope is not None:
        where.append(row_scope)
    with engine.connect() as conn:
        row = conn.execute(sa_table.select().where(and_(*where))).first()
    if row is None:
        return None
    result = attach_links(engine, table, [_row_to_dict(table, sa_table, row)], db=db)[0]
    if db is not None and user is not None:
        from cndb.plugins.tables.access import apply_field_hiding, get_hidden_field_names

        hidden = get_hidden_field_names(db, table, user)
        apply_field_hiding(result, hidden)
    return result


def _build_row_scope_where(table: DataTable, sa_table: Any, db: Any) -> Any | None:
    """从 TablePermission.row_filters 编译行级权限 WHERE 条件.

    仅在 db 可用且 row_filters 非空时生效。返回的条件会与 trashed 条件 AND 组合。
    """
    if db is None:
        return None
    from cndb.plugins.tables.access import get_row_scope, row_filter_conjunction
    from cndb.plugins.tables.query import compile_filters

    scope = get_row_scope(db, table)
    if not scope:
        return None
    conj = row_filter_conjunction(db, table)
    return compile_filters(table, sa_table, scope, conj)


def list_rows(
    engine: Any,
    table: DataTable,
    *,
    filters: list[dict[str, Any]] | None = None,
    filter_logic: str = "AND",
    sorts: list[dict[str, str]] | None = None,
    limit: int = 100,
    offset: int = 0,
    include_trashed: bool = False,
    db: Any = None,
    user: Any = None,
) -> tuple[list[dict[str, Any]], int]:
    """列表查询，返回 (rows, total_count).

    Args:
        filters: 过滤条件列表，每项 {field_name, op, value}. op 见 query.py，
            关联字段支持 is_null/has_any/has_all.
        filter_logic: "AND" 或 "OR"，多条件组合方式.
        sorts: 排序列表，每项 {field_name, direction}，direction="asc"|"desc".
        limit / offset: 分页.
        include_trashed: 是否包含软删除行.
        db: 元数据库会话（提供时 link 字段输出目标行摘要，否则回退 "#id"）.
        user: 当前用户（提供时按 TablePermission.hidden_fields 做字段隐藏）.
    """
    from cndb.plugins.tables.query import compile_filters, compile_sorts

    sa_table = _get_sa_table(engine, table)

    # 基础 where（trashed 条件始终与业务过滤 AND 组合）
    base_where: list[Any] = []
    if not include_trashed:
        base_where.append(sa_table.c._trashed.is_(False))

    # 行级权限（TablePermission.row_filters）
    row_scope = _build_row_scope_where(table, sa_table, db)
    if row_scope is not None:
        base_where.append(row_scope)

    # 业务过滤
    business_where: Any | None = None
    if filters:
        business_where = compile_filters(table, sa_table, filters, filter_logic)

    # 构建 base query —— trashed AND 权限 AND 业务过滤
    query = sa_table.select()
    final_where: list[Any] = list(base_where)
    if business_where is not None:
        final_where.append(business_where)
    if final_where:
        if len(final_where) == 1:
            query = query.where(final_where[0])
        else:
            query = query.where(and_(*final_where))

    # total count
    with engine.connect() as conn:
        count_query = select(func.count(sa_table.c.id))
        if final_where:
            count_query = count_query.where(*final_where)
        total = conn.execute(count_query).scalar()

        # 排序
        if sorts:
            query = query.order_by(*compile_sorts(table, sa_table, sorts))

        # 分页
        query = query.limit(limit).offset(offset)

        rows = conn.execute(query).all()

    result = attach_links(engine, table, [_row_to_dict(table, sa_table, r) for r in rows], db=db)

    # 字段隐藏
    if db is not None and user is not None:
        from cndb.plugins.tables.access import apply_field_hiding_rows, get_hidden_field_names

        hidden = get_hidden_field_names(db, table, user)
        apply_field_hiding_rows(result, hidden)

    return result, total or 0


# ── UPDATE ───────────────────────────────────────────


def update_row(
    engine: Any,
    table: DataTable,
    row_id: int,
    values: dict[str, Any],
    db: Any = None,
) -> dict[str, Any] | None:
    """更新一行，返回更新后的完整数据；行不存在或已软删除或被行级权限拦截时返回 None.

    仅传 link 字段（无物理列值）时同样生效；link 值为 None 表示显式清空关联.
    """
    sa_table = _get_sa_table(engine, table)
    normalized, link_values = _normalize_values(table, values, for_update=True)

    if not normalized and not link_values:
        return get_row(engine, table, row_id, db=db)

    # 主行提交前预校验 link 目标存在，避免主行已提交但 link 写入失败
    if db is not None:
        for field, ids in link_values:
            if ids:
                ensure_link_targets_exist(engine, field, ids, db)

    row_scope = _build_row_scope_where(table, sa_table, db)
    base_where: list[Any] = [sa_table.c.id == row_id, sa_table.c._trashed.is_(False)]
    if row_scope is not None:
        base_where.append(row_scope)

    with engine.begin() as conn:
        if normalized:
            result = conn.execute(sa_table.update().where(*base_where).values(**normalized))
            if result.rowcount == 0:
                return None
        else:  # pragma: no cover - 只更新关联分支待补测试
            existing = conn.execute(select(sa_table.c.id).where(*base_where)).first()
            if existing is None:
                return None

    for field, target_ids in link_values:
        set_links(engine, field, row_id, target_ids, db=db)

    row = get_row(engine, table, row_id, db=db)
    if row is not None:
        try:
            log_action(db, table, ACTION_UPDATE, target_id=row_id, detail=row)
        except Exception as exc:
            logger.debug("audit update_row 失败: %s", exc)
    return row


# ── DELETE ───────────────────────────────────────────


def delete_row(engine: Any, table: DataTable, row_id: int, db: Any = None) -> bool:
    """硬删除单行（同步清理关联记录），返回是否成功.

    行级权限拦截时返回 False（不会删除被 row_filters 过滤的行）.
    """
    sa_table = _get_sa_table(engine, table)
    row_scope = _build_row_scope_where(table, sa_table, db)
    base_where: list[Any] = [sa_table.c.id == row_id, sa_table.c._trashed.is_(False)]
    if row_scope is not None:
        base_where.append(row_scope)
    with engine.begin() as conn:
        result = conn.execute(sa_table.delete().where(*base_where))
        if result.rowcount > 0:
            clear_row_links(engine, table, [row_id])
            try:
                log_action(db, table, ACTION_DELETE, target_id=row_id)
            except Exception as exc:
                logger.debug("audit delete_row 失败: %s", exc)
            return True
    return False


# ── 软删除 / 恢复 ────────────────────────────────────


def trash_row(engine: Any, table: DataTable, row_id: int, db: Any = None) -> bool:
    """软删除（标记 _trashed=True）."""
    sa_table = _get_sa_table(engine, table)
    row_scope = _build_row_scope_where(table, sa_table, db)
    base_where: list[Any] = [sa_table.c.id == row_id]
    if row_scope is not None:
        base_where.append(row_scope)
    with engine.begin() as conn:
        result = conn.execute(
            sa_table.update()
            .where(*base_where)
            .values(
                _trashed=True,
                _trashed_at=datetime.now(UTC),
            )
        )
        ok = result.rowcount > 0
    if ok:
        try:
            log_action(db, table, ACTION_TRASH, target_id=row_id)
        except Exception as exc:
            logger.debug("audit trash_row 失败: %s", exc)
    return ok


def restore_row(engine: Any, table: DataTable, row_id: int, db: Any = None) -> bool:
    """从回收站恢复."""
    sa_table = _get_sa_table(engine, table)
    row_scope = _build_row_scope_where(table, sa_table, db)
    base_where: list[Any] = [sa_table.c.id == row_id]
    if row_scope is not None:
        base_where.append(row_scope)
    with engine.begin() as conn:
        result = conn.execute(
            sa_table.update()
            .where(*base_where)
            .values(
                _trashed=False,
                _trashed_at=None,
            )
        )
        ok = result.rowcount > 0
    if ok:
        try:
            log_action(db, table, ACTION_RESTORE, target_id=row_id)
        except Exception as exc:
            logger.debug("audit restore_row 失败: %s", exc)
    return ok


# ── BULK ─────────────────────────────────────────────


def bulk_create(
    engine: Any,
    table: DataTable,
    rows: list[dict[str, Any]],
    db: Any = None,
) -> list[int]:
    """批量创建，返回新行 id 列表；行内 link 字段同步写关联表."""
    sa_table = _get_sa_table(engine, table)
    # 逐行生成自动编号（顺序递增），再统一写入；assigned 记录本批次已分配编号，
    # 否则后续行扫描不到前面尚未落库的编号会重复分配
    assigned: dict[int, list[str]] = {}
    split_rows: list[tuple[dict[str, Any], list[tuple[DataField, list[int]]]]] = []
    for r in rows:
        normalized, link_values = _normalize_values(table, r)
        _apply_auto_increment_defaults(engine, table, r, normalized, assigned)
        split_rows.append((normalized, link_values))

    # 所有主行提交前预校验全部 link 目标存在，避免部分主行已入库但后续 link 写入失败
    if db is not None:
        for _values, link_values in split_rows:
            for field, ids in link_values:
                if ids:
                    ensure_link_targets_exist(engine, field, ids, db)

    ids: list[int] = []
    with engine.begin() as conn:
        for values, _link_values in split_rows:
            if values:
                result = conn.execute(sa_table.insert().values(**values))
            else:
                # 行仅有 link 值（无物理列值）：显式写软删标记保证 INSERT 合法
                result = conn.execute(sa_table.insert().values(_trashed=False))
            ids.append(result.lastrowid)

    for row_id, (_values, link_values) in zip(ids, split_rows, strict=True):
        for field, target_ids in link_values:
            set_links(engine, field, row_id, target_ids, db=db)

    return ids


def bulk_update(
    engine: Any,
    table: DataTable,
    row_ids: list[int],
    values: dict[str, Any],
    db: Any = None,
) -> int:
    """批量更新，返回影响行数；link 字段对每行写入相同关联集合.

    被 row_filters 过滤的行不会被更新（不泄漏存在性）.
    """
    sa_table = _get_sa_table(engine, table)
    normalized, link_values = _normalize_values(table, values, for_update=True)

    if not normalized and not link_values:
        return 0

    # 主行提交前预校验 link 目标存在，避免物理列已更新但 link 写入失败
    if db is not None:
        for field, ids in link_values:
            if ids:
                ensure_link_targets_exist(engine, field, ids, db)

    row_scope = _build_row_scope_where(table, sa_table, db)
    count = 0
    with engine.connect() as conn:
        valid_where: list[Any] = [sa_table.c.id.in_(row_ids), sa_table.c._trashed.is_(False)]
        if row_scope is not None:
            valid_where.append(row_scope)
        valid_ids = [int(r[0]) for r in conn.execute(select(sa_table.c.id).where(*valid_where)).all()]

    if normalized:
        update_where: list[Any] = [sa_table.c.id.in_(valid_ids)]
        if row_scope is not None:
            update_where.append(row_scope)
        with engine.begin() as conn:
            result = conn.execute(sa_table.update().where(*update_where).values(**normalized))
            count = result.rowcount
    else:
        count = len(valid_ids)

    if valid_ids and link_values:
        for row_id in valid_ids:
            for field, target_ids in link_values:
                set_links(engine, field, row_id, target_ids, db=db)

    return count


def bulk_delete(engine: Any, table: DataTable, row_ids: list[int], db: Any = None) -> int:
    """批量硬删除（同步清理关联记录），返回影响行数.

    被 row_filters 过滤的行不会被删除，也不会被清理关联或记 audit.
    """
    sa_table = _get_sa_table(engine, table)
    if not row_ids:
        return 0
    row_scope = _build_row_scope_where(table, sa_table, db)

    # 先查哪些行真正符合删除条件（同时受 row_filters 约束），避免误删 links / 误记 audit
    check_where: list[Any] = [sa_table.c.id.in_(row_ids), sa_table.c._trashed.is_(False)]
    if row_scope is not None:
        check_where.append(row_scope)
    with engine.connect() as conn:
        valid_ids = [int(r[0]) for r in conn.execute(select(sa_table.c.id).where(*check_where)).all()]

    if not valid_ids:
        return 0

    del_where: list[Any] = [sa_table.c.id.in_(valid_ids)]
    with engine.begin() as conn:
        result = conn.execute(sa_table.delete().where(*del_where))
        count = result.rowcount

    if count > 0:
        # 只清理实际被删除行的 links（valid_ids 一定是 row_ids 的子集）
        clear_row_links(engine, table, valid_ids)
        for rid in valid_ids:
            try:
                log_action(db, table, ACTION_DELETE, target_id=rid)
            except Exception as exc:
                logger.debug("audit bulk_delete 失败 row %s: %s", rid, exc)
    return count


# ── 内部辅助 ─────────────────────────────────────────


def _row_to_dict(table: DataTable, _sa_table: Table, row: Any) -> dict[str, Any]:
    """把 Row 对象转为前端友好的 dict（用 field_name 作为 key，不是 db_column_name）."""
    field_map_rev: dict[str, DataField] = {f.db_column_name: f for f in table.fields}
    result: dict[str, Any] = {}

    for col_name, value in row._mapping.items():
        if col_name == "id":
            result["id"] = value
            continue
        if col_name in ("_trashed", "_trashed_at"):
            continue
        f = field_map_rev.get(col_name)
        if f is not None:
            result[f.name] = value
        else:
            result[col_name] = value

    return result


# ── UPSERT 支撑（导入流水线用）──────────────────────


def find_rows_by_key(
    engine: Any,
    table: DataTable,
    key_cols: list[str],
    values_list: list[dict[str, Any]],
    *,
    chunk_size: int = 500,
) -> tuple[dict[tuple[Any, ...], int], dict[tuple[Any, ...], int]]:
    """按多列组合批量查询已有行，返回 `{key_tuple: row_id}` 映射.

    Args:
        engine: SQLAlchemy engine.
        table: 目标数据表元数据.
        key_cols: 参与匹配的字段名列表（DataField.name，不是 db_column_name）.
        values_list: 文件行原始 values 列表（每个 dict 至少包含 key_cols）.
        chunk_size: 每批 OR 条件数量，默认 500.

    Returns:
        (exact_map, conflict_map) —
            exact_map: {key_tuple: 唯一 row_id}；
            conflict_map: {key_tuple: 匹配到的行数}（多行同 key 时取 min(id) 做 exact_map，
                同时在 conflict_map 里记录冲突数，让调用方决定是否告警）.
    """
    if not key_cols or not values_list:
        return {}, {}

    sa_table = _get_sa_table(engine, table)
    # 把 field_name → db_column_name 建立映射
    col_map: dict[str, str] = {}
    for f in table.fields:
        if f.trashed:
            continue
        if f.name in key_cols:
            col_map[f.name] = f.db_column_name
    # key_cols 里若有不存在的字段，过滤掉
    effective_cols = [c for c in key_cols if c in col_map]
    if not effective_cols:
        return {}, {}

    # 收集所有唯一 key tuple（保持 None，不用空串替代）
    unique_keys: list[tuple[Any, ...]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in values_list:
        tup = tuple(row.get(c) for c in effective_cols)
        if tup not in seen:
            seen.add(tup)
            unique_keys.append(tup)

    exact_map: dict[tuple[Any, ...], int] = {}
    conflict_map: dict[tuple[Any, ...], int] = {}

    for i in range(0, len(unique_keys), chunk_size):
        chunk = unique_keys[i : i + chunk_size]
        # 构建 OR 条件：(k1=? AND k2=? AND _trashed=FALSE) OR ...
        or_parts = []
        for tup in chunk:
            and_parts: list[Any] = [sa_table.c._trashed.is_(False)]
            for c, val in zip(effective_cols, tup, strict=True):
                db_col = sa_table.c[col_map[c]]
                if val is None:
                    and_parts.append(db_col.is_(None))
                else:
                    and_parts.append(db_col == val)
            or_parts.append(and_(*and_parts))
        where = or_(*or_parts)
        query = select(sa_table.c.id, *[sa_table.c[col_map[c]] for c in effective_cols]).where(where)

        with engine.connect() as conn:
            rows = conn.execute(query).all()

        # 按 key 分组
        grouped: dict[tuple[Any, ...], list[int]] = defaultdict(list)
        for r in rows:
            row_id = int(r[0])
            key_tup = tuple(r[i + 1] for i in range(len(effective_cols)))
            grouped[key_tup].append(row_id)

        for key_tup, ids in grouped.items():
            if len(ids) > 1:
                conflict_map[key_tup] = len(ids)
            exact_map[key_tup] = min(ids)

    return exact_map, conflict_map


def bulk_update_rows(
    engine: Any,
    table: DataTable,
    updates: list[dict[str, Any]],
    db: Any = None,
) -> int:
    """批量单行更新 — 每条 row_id 对应独立 values（upsert 分流时用）.

    与 bulk_update 不同：bulk_update 是 "N 行共用一组 values"，这里是 "N 行各有自己的 values"。
    批量导入场景不逐条记 audit log（避免海量 audit 行）。返回成功更新的行数。
    """
    if not updates:
        return 0

    sa_table = _get_sa_table(engine, table)
    row_scope = _build_row_scope_where(table, sa_table, db)
    total = 0

    # 总事务前预校验所有待更新行的 link 目标存在，避免部分行已提交但 link 失败
    if db is not None:
        for item in updates:
            values = item.get("values") or {}
            if not values:
                continue
            _normalized, link_values = _normalize_values(table, values, for_update=True)
            for field, ids in link_values:
                if ids:
                    ensure_link_targets_exist(engine, field, ids, db)

    # 逐行在同一个事务里执行（SQLite/PostgreSQL 对 100-500 行循环开销可接受）
    with engine.begin() as conn:
        for item in updates:
            row_id = item.get("row_id")
            values = item.get("values") or {}
            if row_id is None or not values:
                continue
            normalized, link_values = _normalize_values(table, values, for_update=True)
            if not normalized and not link_values:
                continue
            # 构造带行级权限的 WHERE 条件
            row_where: list[Any] = [sa_table.c.id == row_id, sa_table.c._trashed.is_(False)]
            if row_scope is not None:
                row_where.append(row_scope)
            # 物理列更新
            if normalized:
                result = conn.execute(sa_table.update().where(*row_where).values(**normalized))
                if result.rowcount == 0:
                    # 行不存在、被软删或被行级权限过滤，跳过
                    continue
                total += 1
            else:
                # 只有 link 值
                existing = conn.execute(select(sa_table.c.id).where(*row_where)).first()
                if existing is None:
                    continue
                total += 1
            # link 同步（事务外 set_links 有自己的 engine.begin）
            for field, target_ids in link_values:
                set_links(engine, field, row_id, target_ids, db=db)

    return total


__all__ = [
    "bulk_create",
    "bulk_delete",
    "bulk_update",
    "bulk_update_rows",
    "create_row",
    "delete_row",
    "find_rows_by_key",
    "get_row",
    "list_rows",
    "restore_row",
    "trash_row",
    "update_row",
]
