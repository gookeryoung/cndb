"""关联字段数据读写：关联物理表的多对多维护与行摘要输出.

读写约定（对齐旧项目 cndb.tables.links）：
- 写入：行数据中的 link 字段值（目标行 id 列表）同步到关联表（DELETE + 批量 INSERT 替换语义）；
- 读取：行响应中 link 字段输出摘要列表 [{"id", "value"}]，value 取目标行前几个字段的首个非空值。
- db 会话可选：提供 Session 时做目标行存在性校验与摘要解析；不提供时跳过校验、摘要回退 "#id"。

本模块不依赖 records（避免循环导入），目标行摘要独立按需查询。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from sqlalchemy import MetaData, Table, inspect, select, text

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import Session

# 摘要取值最多考察目标表前 N 个非关联字段（首个非空值即作为摘要）
_SUMMARY_FIELD_LIMIT = 3

LINK_FIELD_TYPE = "link"


def is_link_field(field: DataField) -> bool:
    """判断字段是否为关联字段."""
    return field.field_type == LINK_FIELD_TYPE


def link_fields(table: DataTable) -> list[DataField]:
    """返回表中全部未回收的关联字段."""
    return [f for f in table.active_fields() if is_link_field(f)]


# ── 写入 ─────────────────────────────────────────────


def set_links(
    engine: Engine,
    field: DataField,
    row_id: int,
    target_ids: Sequence[int],
    db: Session | None = None,
) -> None:
    """替换一行的关联集合：先清空再批量写入；提供 db 时校验目标行存在（越界 id 拒绝写入）.

    物理写入独立提交（不与调用方行写入同事务）；目标行不存在时抛 ValueError.
    """
    ids = list(dict.fromkeys(target_ids))
    if db is not None and ids:
        ensure_link_targets_exist(engine, field, ids, db)
    link_table = _get_link_sa_table(engine, field.link_table_name)
    with engine.begin() as conn:
        conn.execute(link_table.delete().where(link_table.c.row_id == row_id))
        if not ids:
            return
        conn.execute(
            link_table.insert(),
            [{"row_id": row_id, "target_row_id": target_id} for target_id in ids],
        )


def clear_row_links(engine: Engine, table: DataTable, row_ids: Sequence[int]) -> None:
    """清理一批行的全部关联记录（行硬删除时调用，防止悬挂引用）."""
    ids = list(dict.fromkeys(row_ids))
    if not ids:
        return
    for field in link_fields(table):
        if not link_table_exists(engine, field.link_table_name):
            continue
        link_table = _get_link_sa_table(engine, field.link_table_name)
        with engine.begin() as conn:
            conn.execute(link_table.delete().where(link_table.c.row_id.in_(ids)))


# ── 读取 ─────────────────────────────────────────────


def load_links(engine: Engine, field: DataField, row_ids: Sequence[int]) -> dict[int, list[int]]:
    """读取多行的关联集合：返回 row_id -> 目标行 id 列表（保关联表写入顺序）."""
    ids = list(dict.fromkeys(row_ids))
    if not ids:
        return {}
    link_table = _get_link_sa_table(engine, field.link_table_name)
    with engine.connect() as conn:
        rows = conn.execute(
            select(link_table.c.row_id, link_table.c.target_row_id)
            .where(link_table.c.row_id.in_(ids))
            .order_by(link_table.c.id)
        ).all()
    mapping: dict[int, list[int]] = {}
    for row_id, target_id in rows:
        mapping.setdefault(int(row_id), []).append(int(target_id))
    return mapping


def attach_links(
    engine: Engine, table: DataTable, rows: list[dict[str, Any]], db: Session | None = None
) -> list[dict[str, Any]]:
    """为行响应附加关联字段的摘要值；无关联字段或空结果时原样返回.

    db 为 None 时摘要无法解析目标行内容，回退为 "#<id>" 占位。
    """
    fields = link_fields(table)
    if not fields or not rows:
        return rows
    row_ids = [int(row["id"]) for row in rows]
    for field in fields:
        mapping = load_links(engine, field, row_ids)
        all_targets = [target_id for targets in mapping.values() for target_id in targets]
        summaries = _target_summaries(engine, field, all_targets, db=db)
        for row in rows:
            targets = mapping.get(int(row["id"]), [])
            row[str(field.name)] = [
                {"id": target_id, "value": summaries.get(target_id, f"#{target_id}")} for target_id in targets
            ]
    return rows


# ── 反向引用 ─────────────────────────────────────────


def find_back_references(
    db: Session,
    engine: Engine,
    target_table: DataTable,
    target_row_id: int,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """查找哪些表的哪些 link 字段引用了目标行.

    遍历全局全部 link 字段（不限制工作区，跨工作区关联天然支持），
    用关联表反向查询 target_row_id 是否出现在 target_row_id 列；
    返回 [{table_name, table_id, workspace_id, field_name, row_id, summary}] 列表，
    按 table_name + row_id 排序。limit 限制每张表最多返回行数.
    """
    candidates = (
        db.query(DataField)
        .filter(DataField.field_type == LINK_FIELD_TYPE, DataField.trashed == False)  # noqa: E712
        .all()
    )
    ref_fields = [f for f in candidates if f.config and f.config.get("target_table_id") == target_table.id]
    if not ref_fields:
        return []

    results: list[dict[str, Any]] = []
    for field in ref_fields:
        if not link_table_exists(engine, field.link_table_name):
            continue
        link_table = _get_link_sa_table(engine, field.link_table_name)
        with engine.connect() as conn:
            row_id_rows = conn.execute(
                select(link_table.c.row_id)
                .where(link_table.c.target_row_id == target_row_id)
                .order_by(link_table.c.id)
                .limit(limit)
            ).all()
        row_ids = [int(r[0]) for r in row_id_rows]
        if not row_ids:
            continue
        source_table = db.get(DataTable, field.table_id)
        if source_table is None:
            continue
        summary_fields = _summary_fields(source_table)
        for rid, summary in _row_summaries(engine, source_table, summary_fields, row_ids).items():
            results.append(
                {
                    "table_name": source_table.name,
                    "table_id": source_table.id,
                    "workspace_id": source_table.workspace_id,
                    "field_name": field.name,
                    "row_id": rid,
                    "summary": summary,
                }
            )

    def _sort_key(it: dict[str, Any]) -> tuple[str, int]:
        return str(it["table_name"]), int(it["row_id"])

    results.sort(key=_sort_key)
    return results


# ── 内部辅助 ─────────────────────────────────────────


def _get_link_sa_table(engine: Engine, name: str) -> Table:
    """反射获取关联物理表的 sa.Table（不存在时抛错，指向 DDL 未执行的编程错误）."""
    metadata = MetaData()
    metadata.reflect(bind=engine, only=[name])
    if name not in metadata.tables:
        raise RuntimeError(f"关联物理表 {name} 不存在，请先通过 DDL 引擎创建")
    return metadata.tables[name]


def _target_data_table(db: Session, field: DataField) -> DataTable | None:
    """解析关联字段的目标表元数据（config 保存期校验保证存在）."""
    target_id = (field.config or {}).get("target_table_id")
    if target_id is None:
        return None
    return db.get(DataTable, target_id)


def ensure_link_targets_exist(engine: Engine, field: DataField, ids: list[int], db: Session) -> None:
    """校验关联目标行在目标物理表中存在（越界 id 拒绝写入）.

    主行 INSERT/UPDATE 之前调用，避免主行已提交但 link 写入失败留下孤儿主行。
    """
    target = _target_data_table(db, field)
    if target is None:
        raise ValueError(f"字段 {field.name} 的关联目标表不存在")
    sa_table = _get_sa_table_by_name(engine, target.db_table_name)
    with engine.connect() as conn:
        rows = conn.execute(select(sa_table.c.id).where(sa_table.c.id.in_(ids))).all()
    existing = {int(r[0]) for r in rows}
    missing = [str(i) for i in ids if i not in existing]
    if missing:
        raise ValueError(f"字段 {field.name} 关联的目标行不存在: {', '.join(missing)}")


def _get_sa_table_by_name(engine: Engine, db_table_name: str) -> Table:
    metadata = MetaData()
    metadata.reflect(bind=engine, only=[db_table_name])
    if db_table_name not in metadata.tables:
        raise RuntimeError(f"物理表 {db_table_name} 不存在")
    return metadata.tables[db_table_name]


def _summary_fields(table: DataTable) -> list[DataField]:
    """摘要只考察前几个非关联字段（避免宽表全列查询）."""
    result: list[DataField] = []
    for f in table.active_fields():
        ft = default_registry.get(f.field_type)
        if ft is not None and ft.has_physical_column:
            result.append(f)
        if len(result) >= _SUMMARY_FIELD_LIMIT:
            break
    return result


def _target_summaries(
    engine: Engine,
    field: DataField,
    target_ids: Sequence[int],
    db: Session | None = None,
) -> dict[int, str]:
    """批量生成目标行摘要：id -> 首个非空字段值（回退 #id）."""
    ids = list(dict.fromkeys(target_ids))
    if not ids:
        return {}
    if db is None:
        return {target_id: f"#{target_id}" for target_id in ids}
    target = _target_data_table(db, field)
    if target is None:
        return {target_id: f"#{target_id}" for target_id in ids}
    return _row_summaries(engine, target, _summary_fields(target), ids)


def _row_summaries(
    engine: Engine,
    table: DataTable,
    summary_fields: list[DataField],
    row_ids: Sequence[int],
) -> dict[int, str]:
    """按摘要字段批量读取行，产出 id -> 首个非空值（回退 #id）."""
    ids = list(dict.fromkeys(row_ids))
    if not ids:
        return {}
    sa_table = _get_sa_table_by_name(engine, table.db_table_name)
    columns = [sa_table.c.id, *[sa_table.c[f.db_column_name] for f in summary_fields]]
    with engine.connect() as conn:
        db_rows = conn.execute(select(*columns).where(sa_table.c.id.in_(ids))).all()
    summaries: dict[int, str] = {}
    for db_row in db_rows:
        row_id = int(db_row[0])
        value: str | None = None
        for offset, item in enumerate(summary_fields, start=1):
            ft = default_registry.get(item.field_type)
            if ft is None:  # pragma: no cover - 注册表内置完整
                continue
            raw = db_row[offset]
            try:
                normalized = ft.validate_value(raw, item.config) if raw is not None else None
            except Exception:
                normalized = None
            if normalized is not None and str(normalized).strip() != "":
                value = str(normalized)
                break
        summaries[row_id] = value if value is not None else f"#{row_id}"
    return summaries


def link_table_exists(engine: Engine, name: str) -> bool:
    """检查关联物理表是否存在."""
    return name in inspect(engine).get_table_names()


def _unused_text_import_guard() -> None:  # pragma: no cover - 保持 text 引用供方言调试
    text("SELECT 1")


__all__ = [
    "LINK_FIELD_TYPE",
    "attach_links",
    "clear_row_links",
    "find_back_references",
    "is_link_field",
    "link_fields",
    "link_table_exists",
    "load_links",
    "set_links",
]
