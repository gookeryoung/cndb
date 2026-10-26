"""字段引入（schema 导入）实现：解析源字段、冲突校验、落库与跨表克隆.

从 field_ops.py 拆出；对外仍通过 field_ops 转发，调用方与 monkeypatch 目标不变。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from cndb.plugins.tables.models import DataField, DataTable, generate_db_column_name
from cndb.plugins.tables.services.core import ddl as _ddl
from cndb.plugins.tables.services.core.links import is_link_field
from cndb.plugins.tables.services.importing.field_mapping import apply_user_mapping, build_default_mapping

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


def rename_trashed_field_aside(db: Session, field: DataField) -> str:
    """为软删除字段生成让位名：原名追加「（已删）」后缀，冲突时递增序号.

    背景：DataField 有 uniq_table_field_name（table_id, name）唯一约束，
    软删除记录仍占用约束位 —— 删除字段后新建同名字段会触发
    IntegrityError。让位改名后原名字即可复用，调用方负责赋值与 commit。

    两条调用路径：
    - delete_field：软删除时同步让位，原名字立即可复用；
    - create_field：存量软删除字段占用目标名字时的兜底让位（修复历史数据）。

    Args:
        db: SQLAlchemy Session（用于查询表内已有字段名）.
        field: 待让位的软删除字段（须已持久化有 id，自身名字不参与判重）.

    Returns:
        分配的不冲突新名字.
    """
    taken = {
        f.name for f in db.query(DataField).filter(DataField.table_id == field.table_id, DataField.id != field.id).all()
    }
    base = f"{field.name}（已删）"
    candidate = base
    idx = 2
    while candidate in taken:
        candidate = f"{base} {idx}"
        idx += 1
    return candidate


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


def _ensure_required_fields_addable(engine: Any, dst_table: DataTable, plan: list[DataField]) -> None:
    """非空表无法新增 NOT NULL 物理列：提前抛 ValueError（路由层转 400），不落到 DDL 异常.

    SQLite / PostgreSQL 都要求 ADD COLUMN NOT NULL 自带非 NULL 默认值；克隆字段无法为
    存量行提供真实取值，用占位默认值会污染必填语义，因此明确拒绝并提示可空路径。
    """
    from cndb.plugins.tables.field_types import default_registry

    blocked = []
    for f in plan:
        ft = default_registry.get(f.field_type)
        if f.required and ft is not None and ft.has_physical_column:
            blocked.append(f.name)
    if not blocked:
        return
    if not _ddl.table_has_rows(engine, dst_table.db_table_name):
        return
    raise ValueError(
        f"目标表「{dst_table.name}」已有数据，无法引入必填字段（{'、'.join(blocked)}）；请先改为可空后再补齐数据"
    )


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

    _ensure_required_fields_addable(engine, dst_table, plan)

    # 阶段一：全部 DDL 先成功，再 ORM commit —— 避免孤儿 DataField（importer._auto_add_fields 同款事务策略）
    from cndb.plugins.tables.services.core.ddl import drop_column

    for f in plan:
        f.ensure_db_name()

    ddl_ok: list[DataField] = []  # 记录 DDL 成功的字段，失败时逆向清理
    try:
        for f in plan:
            _ddl.add_column(engine, dst_table, f)
            if f.is_unique:
                _ddl.add_unique_constraint(engine, dst_table, f)
            ddl_ok.append(f)
    except Exception:
        # 逆向清理已成功的 DDL 列
        for f in reversed(ddl_ok):
            import contextlib as _cl

            with _cl.suppress(Exception):
                if f.is_unique:
                    _ddl.drop_unique_constraint(engine, dst_table, f)
                drop_column(engine, dst_table, f)
        raise

    # 全部 DDL 成功 → 持久化 DataField 元数据
    for f in plan:
        db.add(f)
    db.commit()
    for f in plan:
        db.refresh(f)

    logger.info("[field_ops] 从源表克隆 %d 个字段到 %s", len(plan), dst_table.name)
    return list(plan)


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

    _ensure_required_fields_addable(engine, dst_table, plan)

    # 阶段一：全部 DDL 先成功，再 ORM commit —— 避免孤儿 DataField
    from cndb.plugins.tables.services.core.ddl import drop_column

    for f in plan:
        f.ensure_db_name()

    ddl_ok: list[DataField] = []
    try:
        for f in plan:
            _ddl.add_column(engine, dst_table, f)
            if f.is_unique:
                _ddl.add_unique_constraint(engine, dst_table, f)
            ddl_ok.append(f)
    except Exception:
        for f in reversed(ddl_ok):
            import contextlib as _cl

            with _cl.suppress(Exception):
                if f.is_unique:
                    _ddl.drop_unique_constraint(engine, dst_table, f)
                drop_column(engine, dst_table, f)
        raise

    for f in plan:
        db.add(f)
    db.commit()
    for f in plan:
        db.refresh(f)
    return list(plan), skipped


def generate_column_name() -> str:
    """生成唯一的物理列名（对外暴露 generate_db_column_name 的别名，便于字段克隆场景调用）."""
    return generate_db_column_name()


# ── 字段关联引入（lookup） ───────────────────────────


def _unique_dst_name(dst_table: DataTable, base: str) -> str:
    """在目标表上为 base 取不冲突的字段名（冲突时追加序号后缀）."""
    existing = {f.name for f in dst_table.fields if not f.trashed}
    if base not in existing:
        return base
    idx = 2
    while f"{base} {idx}" in existing:
        idx += 1
    return f"{base} {idx}"


def import_fields_as_lookup(
    engine: Any,
    db: Session,
    src_table: DataTable,
    dst_table: DataTable,
    src_fields: list[DataField],
    *,
    link_name: str | None = None,
    link_multiple: bool = True,
) -> tuple[list[DataField], list[str]]:
    """把源字段以"字段关联"方式引入目标表：自动建/复用 link 字段 + 每个源字段一个 lookup 字段.

    与 :func:`clone_fields_between_tables` 的复制语义不同，本函数建立**实时关联**：
    - link/lookup 类型的源字段不支持关联引入 → 跳过并说明（禁止递归）；
    - 目标表已有指向源表的 link 字段则复用，否则自动创建"关联 <源表名>"；
    - lookup 字段不落物理列，值在行读取时通过关联表实时解析；
    - 目标表已存在同名字段时跳过（与复制模式的 skip_conflicts 行为一致）。

    Args:
        engine: SQLAlchemy engine.
        db: 数据库会话.
        src_table: 源数据表（lookup 取值来源）.
        dst_table: 目标数据表（link/lookup 字段挂载方）.
        src_fields: 源字段列表（link/lookup 类型会被跳过）.
        link_name: 自建 link 字段名；None 时用默认名 "关联 <源表名>"，已有可复用 link 时忽略.
        link_multiple: 自建 link 字段是否多选（config.multiple）；单行业务表传 False 表示单选关联.

    Returns:
        (创建的 DataField 列表（link + lookup）, 跳过原因说明列表).
    """
    created: list[DataField] = []
    skipped: list[str] = []

    # 1. 过滤不支持关联引入的源字段
    eligible: list[DataField] = []
    for f in src_fields:
        if f.field_type in ("link", "lookup"):
            skipped.append(f"{f.name} — {f.field_type} 类型的源字段不支持关联引入")
        else:
            eligible.append(f)
    if not eligible:
        return [], skipped

    # 2. 复用或创建指向源表的 link 字段（DDL → commit，避免孤儿 metadata）
    link_field = next(
        (
            f
            for f in dst_table.active_fields()
            if f.field_type == "link" and (f.config or {}).get("target_table_id") == src_table.id
        ),
        None,
    )
    if link_field is None:
        link_field = DataField(
            table_id=dst_table.id,
            name=_unique_dst_name(dst_table, link_name or f"关联 {src_table.name}"),
            field_type="link",
            config={"target_table_id": src_table.id, "multiple": link_multiple},
            order=max((f.order for f in dst_table.fields if not f.trashed), default=-1) + 1,
        )
        link_field.ensure_db_name()
        # 先 DDL 创建关联表（失败则 link metadata 不残留，因为还没 commit）
        try:
            _ddl.create_link_table(engine, link_field)
        except Exception:
            logger.error("[field_ops] 创建 link 关联物理表失败: %s", link_field.name, exc_info=True)
            raise
        db.add(link_field)
        db.commit()
        db.refresh(link_field)
        created.append(link_field)
        logger.info("[field_ops] 自动创建关联字段 %r → 表 %s", link_field.name, src_table.name)

    # 3. 每个源字段创建一个 lookup 字段（批量 add + 单次 commit，lookup 不落物理列）
    next_order = max((f.order for f in dst_table.fields if not f.trashed), default=-1) + 1
    existing_names = {f.name for f in dst_table.fields if not f.trashed}
    lookups_to_add: list[DataField] = []
    for src in eligible:
        if src.name in existing_names:
            skipped.append(f"{src.name} — 目标表已存在同名字段，跳过")
            continue
        existing_names.add(src.name)
        lookup_field = DataField(
            table_id=dst_table.id,
            name=src.name,
            field_type="lookup",
            config={
                "source_table_id": src_table.id,
                "source_field_id": src.id,
                "via_link_field_id": link_field.id,
                "source_field_type": src.field_type,
            },
            order=next_order,
        )
        next_order += 1
        lookup_field.ensure_db_name()
        lookups_to_add.append(lookup_field)

    if lookups_to_add:
        try:
            for lf in lookups_to_add:
                db.add(lf)
            db.commit()
            for lf in lookups_to_add:
                db.refresh(lf)
            created.extend(lookups_to_add)
        except Exception:
            # lookup 无物理列，rollback 有效
            db.rollback()
            raise

    # 把本批 lookup 登记到 link 字段的 reference_fields —— 引用字段归属该关联字段，
    # 之后编辑 link 字段时「引用字段」列表即反映这些项（与 sync_link_reference_fields 口径一致）。
    _register_link_reference_fields(db, link_field)
    lookup_count = sum(1 for f in created if f.field_type == "lookup")
    logger.info(
        "[field_ops] 关联引入 %d 个 lookup 字段到 %s（link 字段: %s）",
        lookup_count,
        dst_table.name,
        link_field.name,
    )
    return created, skipped


# ── 关联字段的引用字段管理 ────────────────────────────


def _managed_lookups(db: Session, link_field: DataField) -> list[DataField]:
    """返回归属于某 link 字段名下的未回收 lookup 字段（via_link_field_id 指向它）."""
    candidates = (
        db.query(DataField)
        .filter(
            DataField.table_id == link_field.table_id,
            DataField.field_type == "lookup",
            DataField.trashed == False,  # noqa: E712
        )
        .all()
    )
    return [f for f in candidates if (f.config or {}).get("via_link_field_id") == link_field.id]


def _register_link_reference_fields(db: Session, link_field: DataField) -> None:
    """把 link 字段名下已有 lookup 的来源字段登记为 config.reference_fields（保序）."""
    lookups = sorted(_managed_lookups(db, link_field), key=lambda f: (f.order, f.id))
    ref_ids: list[int] = []
    for lf in lookups:
        source_id = (lf.config or {}).get("source_field_id")
        if isinstance(source_id, int) and source_id not in ref_ids:
            ref_ids.append(source_id)
    config = dict(link_field.config or {})
    if config.get("reference_fields") == ref_ids:
        return
    config["reference_fields"] = ref_ids
    link_field.config = config
    db.commit()


def sync_link_reference_fields(db: Session, link_field: DataField, target_table: DataTable) -> list[DataField]:
    """按 link 字段 config.reference_fields 同步其名下的 lookup 引用字段.

    引用字段在关联配置内管理（而非独立字段设置）：保存 link 字段时按配置对齐 ——
    - 配置中的每个目标字段 id 对应一个 lookup（复用同源已有项，缺失时新建）；
    - 配置中已移除、但仍挂在 link 下的 lookup 软删除让位，释放字段名；
    - 顺序按配置列表顺序写入 order，使字段列表折叠展示时顺序一致。

    Args:
        db: SQLAlchemy Session（本函数内 commit）.
        link_field: 已持久化（有 id）的 link 字段.
        target_table: link 字段关联的目标表.

    Returns:
        当前生效的引用 lookup 字段列表（按配置顺序）.
    """
    if link_field.id is None:  # pragma: no cover - 调用方保证已 commit 有 id
        return []

    managed = _managed_lookups(db, link_field)
    by_source: dict[int, DataField] = {}
    for lf in managed:
        source_id = (lf.config or {}).get("source_field_id")
        if isinstance(source_id, int):
            by_source.setdefault(source_id, lf)

    target_by_id = {f.id: f for f in target_table.active_fields()}
    ref_ids = list((link_field.config or {}).get("reference_fields") or [])

    used_names = {
        f.name
        for f in db.query(DataField)
        .filter(DataField.table_id == link_field.table_id, DataField.trashed == False)  # noqa: E712
        .all()
    }

    kept: list[DataField] = []
    created: list[DataField] = []
    for idx, ref_id in enumerate(ref_ids):
        src = target_by_id.get(ref_id)
        if src is None:
            continue  # 校验期已拒绝，这里防御性跳过
        order = (link_field.order or 0) + idx + 1
        existing = by_source.pop(ref_id, None)
        if existing is not None:
            existing.order = order
            cfg = dict(existing.config or {})
            cfg.update(
                {
                    "source_table_id": target_table.id,
                    "source_field_id": src.id,
                    "via_link_field_id": link_field.id,
                    "source_field_type": src.field_type,
                }
            )
            cfg.pop("broken", None)
            existing.config = cfg
            kept.append(existing)
            continue
        name = _unique_name_against(used_names, src.name)
        used_names.add(name)
        lf = DataField(
            table_id=link_field.table_id,
            name=name,
            field_type="lookup",
            config={
                "source_table_id": target_table.id,
                "source_field_id": src.id,
                "via_link_field_id": link_field.id,
                "source_field_type": src.field_type,
            },
            order=order,
        )
        lf.ensure_db_name()
        db.add(lf)
        created.append(lf)
        kept.append(lf)

    # 配置外仍挂在 link 下的 lookup 软删除让位（referenced 名字释放供复用）
    for stale in by_source.values():
        stale.trashed = True
        stale.name = rename_trashed_field_aside(db, stale)

    db.commit()
    for lf in created:
        db.refresh(lf)
    if created or by_source:
        logger.info(
            "[field_ops] 同步关联字段 %r 的引用字段：新建 %d，移除 %d",
            link_field.name,
            len(created),
            len(by_source),
        )
    return kept


def _unique_name_against(used: set[str], base: str) -> str:
    """在 used 名字集合上为 base 取不冲突名（冲突时追加序号后缀）."""
    if base not in used:
        return base
    idx = 2
    while f"{base} {idx}" in used:
        idx += 1
    return f"{base} {idx}"
