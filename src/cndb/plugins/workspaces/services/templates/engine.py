"""模板实例化 / 影响预览 / 生命周期门禁（需求 0094 C3-C5）.

核心口径（非破坏性）：

- 模板同步**只做增量**：缺表建表、缺字段加列、缺文档建占位文档；
  模板里删掉的表 / 字段 / 文档一律保留，仅脱离模板管理；
- 字段类型切换不做自动 DDL，只报 breaking，要求调用方 ``force`` 确认；
- 当前阶段被模板删除时，工作区回落到第一阶段，同样需要 ``force``；
- 所有映射写在 ``Workspace.template_state``（form key → table id / doc key → doc id），
  因此模板改名、文档改标题都不会破坏已有工作区的关联。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable, ensure_default_view
from cndb.plugins.tables.services.core.record_counts import batch_record_counts
from cndb.plugins.workspaces.services.templates.diff import SEVERITY_BREAKING, SEVERITY_INFO, SEVERITY_WARN

#: 预览详情最多返回的工作区条数（聚合计数不受此限制）
IMPACT_DETAIL_LIMIT = 200


class GateError(ValueError):
    """阶段门禁未通过（路由层转 409，detail 携带逐项检查结果）."""

    def __init__(self, message: str, details: dict[str, Any]) -> None:
        super().__init__(message)
        self.details = details


# ── 状态与映射 ─────────────────────────────────────


def _state(ws: Any) -> dict[str, Any]:
    """读取模板状态并做浅拷贝（容器全复制）.

    必须复制 ``history`` 列表：若与 ORM 持有的 JSON 共享同一个 list，
    append 会原地改掉 SQLAlchemy 记录的“旧值”，赋值后判等 → UPDATE 丢失。
    """
    raw = ws.template_state or {}
    return {
        **raw,
        "form_tables": dict(raw.get("form_tables") or {}),
        "documents": dict(raw.get("documents") or {}),
        "history": list(raw.get("history") or []),
    }


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def _stage_by_key(spec: dict[str, Any], key: str | None) -> dict[str, Any] | None:
    for stage in spec.get("stages", []):
        if stage["key"] == key:
            return stage
    return None


def _first_stage(spec: dict[str, Any]) -> dict[str, Any] | None:
    stages = spec.get("stages", [])
    return stages[0] if stages else None


def _resolve_config(config: dict[str, Any], form_tables: dict[str, DataTable]) -> dict[str, Any]:
    """把模板里的 ``target_form`` 解析成物理 ``target_table_id``（link / lookup 用）."""
    resolved = dict(config or {})
    target_form = resolved.pop("target_form", None)
    if isinstance(target_form, str) and target_form in form_tables:
        resolved["target_table_id"] = form_tables[target_form].id
    return resolved


def _field_needs_ddl(field_type: str) -> bool:
    """是否需要为新增字段执行 DDL（lookup 无物理列且无关联表，直接跳过）."""
    ft = default_registry.get(field_type)
    if ft is None:
        return False
    return bool(ft.has_physical_column) or field_type == "link"


def _row_counts(db: Session, tables: list[DataTable]) -> dict[int, int]:
    if not tables:
        return {}
    counts = batch_record_counts(db, tables)
    result: dict[int, int] = {}
    for table in tables:
        if table.id in counts:
            result[table.id] = int(counts[table.id] or 0)
            continue
        try:
            result[table.id] = int(db.execute(text(f'SELECT COUNT(*) FROM "{table.db_table_name}"')).scalar() or 0)
        except Exception:  # pragma: no cover - 物理表缺失时按 0 处理
            result[table.id] = 0
    return result


# ── 文档占位 ───────────────────────────────────────


def _find_stage_for_doc(spec: dict[str, Any], doc_key: str) -> dict[str, Any] | None:
    for stage in spec.get("stages", []):
        if doc_key in stage.get("documents", []):
            return stage
    return None


def _ensure_stage_folder(db: Session, ws: Any, user: Any, stage_name: str) -> Any:
    from cndb.plugins.documents.models import Document

    folder = (
        db.query(Document)
        .filter(
            Document.workspace_id == ws.id,
            Document.title == stage_name,
            Document.is_folder.is_(True),
            Document.is_deleted.is_(False),
        )
        .order_by(Document.id)
        .first()
    )
    if folder is not None:
        return folder
    from cndb.plugins.documents.services.content import create_document

    return create_document(db, ws.id, user, title=stage_name, is_folder=True)


def _document_alive(db: Session, ws_id: int, doc_id: Any) -> bool:
    from cndb.plugins.documents.models import Document

    if not isinstance(doc_id, int):
        return False
    doc = db.get(Document, doc_id)
    return bool(doc is not None and doc.workspace_id == ws_id and not doc.is_deleted and not doc.is_folder)


# ── 模板同步（增量、幂等） ────────────────────────


def apply_spec_to_workspace(
    db: Session,
    ws: Any,
    spec: dict[str, Any],
    user: Any,
    *,
    template: Any = None,
    version: int | None = None,
) -> dict[str, Any]:
    """把规格增量同步到工作区；返回本次新建的表 / 字段 / 文档计数.

    调用方需保证 ``spec`` 已通过 ``normalize_spec``。函数内部会 commit，
    因为 SQLite 下列 DDL 前必须释放 flush 打开的事务（与备份导入同口径）。
    """
    from cndb.plugins.tables.services.core.ddl import (
        add_column,
        add_unique_constraint,
        create_table,
    )

    state = _state(ws)
    engine = db.get_bind()
    form_tables: dict[str, DataTable] = {}
    created_tables = 0
    added_fields = 0
    created_documents = 0

    # 1) 先解析已有映射，再把缺的表建出来
    new_table_keys: set[str] = set()
    for form_index, form in enumerate(spec.get("forms", [])):
        mapped = state["form_tables"].get(form["key"])
        table = db.get(DataTable, mapped) if isinstance(mapped, int) else None
        if table is not None and (table.workspace_id != ws.id or table.trashed_at is not None):
            table = None
        if table is None:
            table = DataTable(
                workspace_id=ws.id,
                owner_id=user.id,
                name=form["name"],
                description=form.get("description", ""),
                order=form_index + 1,
            )
            table.ensure_db_name()
            db.add(table)
            db.flush()
            state["form_tables"][form["key"]] = table.id
            new_table_keys.add(form["key"])
            created_tables += 1
        form_tables[form["key"]] = table

    db.flush()
    db.commit()  # SQLite：DDL 前释放 flush 事务

    # 2) 字段：新表一次建全，已有表只补缺（不改旧字段的类型 / 必填）
    for form in spec.get("forms", []):
        table = form_tables[form["key"]]
        table_is_new = form["key"] in new_table_keys
        existing = {f.name: f for f in table.active_fields()}
        new_fields: list[DataField] = []
        for idx, field_spec in enumerate(form.get("fields", [])):
            if field_spec["name"] in existing:
                continue
            field = DataField(
                table_id=table.id,
                name=field_spec["name"],
                field_type=field_spec["type"],
                config=_resolve_config(field_spec.get("config", {}), form_tables),
                required=bool(field_spec.get("required", False)),
                is_unique=bool(field_spec.get("is_unique", False)),
                default_value=field_spec.get("default_value"),
                hidden=bool(field_spec.get("hidden", False)),
                order=idx,
            )
            field.ensure_db_name()
            db.add(field)
            new_fields.append(field)
            added_fields += 1
        db.flush()
        if table_is_new:
            db.commit()
            db.refresh(table)
            create_table(engine, table)
            ensure_default_view(db, table, owner_id=user.id, commit=False)
            db.commit()
        else:
            db.commit()
            rows = _row_counts(db, [table]).get(table.id, 0)
            for field in new_fields:
                if not _field_needs_ddl(field.field_type):
                    continue
                # 非空表新增「必填」列：SQLite / PostgreSQL 都要求默认值，而模板无法为
                # 存量行编造值。物理列先按可空加，元数据保持 required=True（写路径仍校验），
                # 与影响预览里的「存量行待补值」一致，不阻塞模板更新。
                was_required = bool(field.required)
                if was_required and rows > 0:
                    field.required = False
                    db.add(field)
                    db.commit()
                add_column(engine, table, field)
                if field.is_unique:
                    add_unique_constraint(engine, table, field)
                if was_required:
                    field.required = True
                    db.add(field)
                    db.commit()
            db.commit()

    # 3) link / lookup 的 target_form → target_table_id（建表后回填）
    for form in spec.get("forms", []):
        table = form_tables[form["key"]]
        for field in table.active_fields():
            config = dict(field.config or {})
            if "target_form" not in config:
                continue
            field.config = _resolve_config(config, form_tables)
            db.add(field)
    db.commit()

    # 4) 文档占位：已有占位且未删除则不动，避免覆盖用户正文
    for rule in spec.get("documents", []):
        if _document_alive(db, ws.id, state["documents"].get(rule["key"])):
            continue
        stage = _find_stage_for_doc(spec, rule["key"])
        parent_id = None
        if stage is not None:
            parent_id = _ensure_stage_folder(db, ws, user, stage["name"]).id
        from cndb.plugins.documents.services.content import create_document

        doc = create_document(
            db,
            ws.id,
            user,
            title=rule["title"],
            content=rule.get("content", "") or f"# {rule['title']}\n",
            parent_id=parent_id,
        )
        state["documents"][rule["key"]] = doc.id
        created_documents += 1

    # 5) 模板引用与阶段回填（阶段被删时回落到第一阶段）
    stage_keys = [s["key"] for s in spec.get("stages", [])]
    if template is not None:
        ws.template_id = template.id
        ws.template_version = version if version is not None else template.version
    old_stage = ws.template_stage
    if old_stage not in stage_keys:
        first = _first_stage(spec)
        ws.template_stage = first["key"] if first else None
        if ws.template_stage and old_stage != ws.template_stage:
            state["history"].append(
                {
                    "from": old_stage,
                    "to": ws.template_stage,
                    "at": _now(),
                    "by": getattr(user, "id", None),
                    "reason": "模板同步：原阶段已不存在，回落到第一阶段",
                    "forced": False,
                }
            )
    ws.template_state = state
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return {
        "created_tables": created_tables,
        "added_fields": added_fields,
        "created_documents": created_documents,
    }


# ── 影响预览 ───────────────────────────────────────


def _table_map(db: Session, ws: Any, state: dict[str, Any]) -> dict[str, DataTable]:
    result: dict[str, DataTable] = {}
    for key, table_id in state.get("form_tables", {}).items():
        if not isinstance(table_id, int):
            continue
        table = db.get(DataTable, table_id)
        if table is not None and table.workspace_id == ws.id and table.trashed_at is None:
            result[key] = table
    return result


def preview_impact(db: Session, template: Any, new_spec: dict[str, Any]) -> dict[str, Any]:
    """预览模板更新对**已有工作区**的影响（只读，不落库）."""
    from cndb.plugins.workspaces.models import Workspace

    old_spec = template.spec or {}
    old_forms = {f["key"]: f for f in old_spec.get("forms", [])}
    new_forms = {f["key"]: f for f in new_spec.get("forms", [])}
    old_docs = {d["key"]: d for d in old_spec.get("documents", [])}
    new_docs = {d["key"]: d for d in new_spec.get("documents", [])}
    new_stage_keys = {s["key"] for s in new_spec.get("stages", [])}

    workspaces = db.query(Workspace).filter(Workspace.template_id == template.id).order_by(Workspace.id).all()
    agg = {
        "workspace_count": len(workspaces),
        "affected_workspaces": 0,
        "tables_to_create": 0,
        "fields_to_add": 0,
        "required_fields_needing_backfill": 0,
        "documents_to_create": 0,
        "rows_missing_required": 0,
        "stages_fallback": 0,
        "fields_type_conflict": 0,
        "orphan_forms": 0,
        "orphan_fields": 0,
        "orphan_documents": 0,
    }
    details: list[dict[str, Any]] = []
    requires_force = False

    for ws in workspaces:
        state = _state(ws)
        tables = _table_map(db, ws, state)
        changes: list[dict[str, Any]] = []
        ws_force = False
        counts = _row_counts(db, list(tables.values()))

        # 新增表单 / 字段
        for key, form in new_forms.items():
            table = tables.get(key)
            if table is None:
                agg["tables_to_create"] += 1
                changes.append(
                    {
                        "kind": "table_create",
                        "severity": SEVERITY_INFO,
                        "message": f"将新建数据表「{form['name']}」（{len(form.get('fields', []))} 个字段）",
                    }
                )
                continue
            existing = {f.name: f for f in table.active_fields()}
            for field_spec in form.get("fields", []):
                old_field = next(
                    (f for f in old_forms.get(key, {}).get("fields", []) if f["name"] == field_spec["name"]),
                    None,
                )
                current = existing.get(field_spec["name"])
                if current is None:
                    agg["fields_to_add"] += 1
                    if field_spec.get("required"):
                        agg["required_fields_needing_backfill"] += 1
                        rows = counts.get(table.id, 0)
                        agg["rows_missing_required"] += rows
                        changes.append(
                            {
                                "kind": "required_field_added",
                                "severity": SEVERITY_WARN,
                                "message": (
                                    f"表「{table.name}」新增必填字段「{field_spec['name']}」，"
                                    f"{rows} 条存量行需要补值（不会阻塞保存）"
                                ),
                            }
                        )
                    else:
                        changes.append(
                            {
                                "kind": "field_added",
                                "severity": SEVERITY_INFO,
                                "message": f"表「{table.name}」新增字段「{field_spec['name']}」",
                            }
                        )
                    continue
                if old_field is not None and old_field.get("type") != field_spec.get("type"):
                    agg["fields_type_conflict"] += 1
                    ws_force = True
                    changes.append(
                        {
                            "kind": "field_type_conflict",
                            "severity": SEVERITY_BREAKING,
                            "message": (
                                f"表「{table.name}」字段「{field_spec['name']}」类型 "
                                f"{current.field_type} → {field_spec.get('type')}，需人工迁移（模板不会自动改列）"
                            ),
                        }
                    )

        # 模板移除的表单 / 字段：只提示保留
        for key, form in old_forms.items():
            if key in new_forms:
                continue
            if key in tables:
                agg["orphan_forms"] += 1
                changes.append(
                    {
                        "kind": "form_orphaned",
                        "severity": SEVERITY_WARN,
                        "message": f"数据表「{form['name']}」已从模板移除，表和 {counts.get(tables[key].id, 0)} 条数据保留",
                    }
                )
        for key, form in new_forms.items():
            table = tables.get(key)
            if table is None:
                continue
            existing_names = {f.name for f in table.active_fields()}
            for old_field in old_forms.get(key, {}).get("fields", []):
                if old_field["name"] in existing_names and not any(
                    f["name"] == old_field["name"] for f in form.get("fields", [])
                ):
                    agg["orphan_fields"] += 1
                    changes.append(
                        {
                            "kind": "field_orphaned",
                            "severity": SEVERITY_WARN,
                            "message": f"表「{table.name}」字段「{old_field['name']}」已移出模板，列与数据保留",
                        }
                    )

        # 文档规则
        for key, rule in new_docs.items():
            if _document_alive(db, ws.id, state["documents"].get(key)):
                continue
            agg["documents_to_create"] += 1
            changes.append(
                {
                    "kind": "document_create",
                    "severity": SEVERITY_INFO,
                    "message": f"将创建文档占位「{rule['title']}」",
                }
            )
        for key, rule in old_docs.items():
            if key in new_docs:
                continue
            if _document_alive(db, ws.id, state["documents"].get(key)):
                agg["orphan_documents"] += 1
                changes.append(
                    {
                        "kind": "document_orphaned",
                        "severity": SEVERITY_WARN,
                        "message": f"文档「{rule['title']}」已移出模板，文档与正文保留",
                    }
                )

        # 当前阶段被删除 → 回落第一阶段
        if ws.template_stage and ws.template_stage not in new_stage_keys:
            agg["stages_fallback"] += 1
            ws_force = True
            changes.append(
                {
                    "kind": "stage_fallback",
                    "severity": SEVERITY_BREAKING,
                    "message": f"当前阶段「{ws.template_stage}」已被模板删除，将回落到第一阶段",
                }
            )

        needs_force = ws_force
        if changes:
            agg["affected_workspaces"] += 1
        requires_force = requires_force or needs_force
        if len(details) < IMPACT_DETAIL_LIMIT:
            details.append(
                {
                    "workspace_id": ws.id,
                    "workspace_name": ws.name,
                    "template_version": ws.template_version,
                    "current_stage": ws.template_stage,
                    "requires_force": needs_force,
                    "changes": changes,
                }
            )

    return {
        "template_id": template.id,
        "template_version": template.version,
        "summary": agg,
        "workspaces": details,
        "truncated": len(details) < len(workspaces),
        "requires_force": requires_force,
    }


# ── 生命周期与门禁 ─────────────────────────────────


def lifecycle_state(db: Session, ws: Any, template: Any) -> dict[str, Any]:
    """计算工作区当前生命周期：阶段列表 + 当前阶段门禁逐项状态."""
    spec = template.spec or {}
    state = _state(ws)
    tables = _table_map(db, ws, state)
    counts = _row_counts(db, list(tables.values()))
    stages = spec.get("stages", [])
    current_key = (
        ws.template_stage if _stage_by_key(spec, ws.template_stage) else (stages[0]["key"] if stages else None)
    )
    forms_by_key = {f["key"]: f for f in spec.get("forms", [])}
    docs_by_key = {d["key"]: d for d in spec.get("documents", [])}

    result_stages: list[dict[str, Any]] = []
    current_index = next((i for i, s in enumerate(stages) if s["key"] == current_key), 0)
    for index, stage in enumerate(stages):
        form_checks = []
        for key in stage.get("forms", []):
            table = tables.get(key)
            row_count = counts.get(table.id, 0) if table is not None else 0
            form_checks.append(
                {
                    "key": key,
                    "name": forms_by_key.get(key, {}).get("name", key),
                    "required": True,
                    "table_exists": table is not None,
                    "row_count": row_count,
                    "satisfied": table is not None and row_count >= 1,
                }
            )
        doc_checks = []
        for key in stage.get("documents", []):
            rule = docs_by_key.get(key, {})
            exists = _document_alive(db, ws.id, state["documents"].get(key))
            doc_checks.append(
                {
                    "key": key,
                    "title": rule.get("title", key),
                    "required": bool(rule.get("required", True)),
                    "exists": exists,
                    "satisfied": exists or not bool(rule.get("required", True)),
                }
            )
        satisfied = all(c["satisfied"] for c in form_checks + doc_checks)
        result_stages.append(
            {
                "key": stage["key"],
                "name": stage["name"],
                "description": stage.get("description", ""),
                "order": stage.get("order", index + 1),
                "is_current": stage["key"] == current_key,
                "is_completed": index < current_index,
                "gate_satisfied": satisfied,
                "forms": form_checks,
                "documents": doc_checks,
            }
        )
    current = result_stages[current_index] if result_stages else None
    next_stage = result_stages[current_index + 1] if result_stages and current_index + 1 < len(result_stages) else None
    return {
        "template_id": template.id,
        "template_name": template.name,
        "template_version": ws.template_version or template.version,
        "current_version": template.version,
        "current_stage": current_key,
        "current_stage_index": current_index,
        "stage_count": len(result_stages),
        "can_advance": bool(current and current["gate_satisfied"] and next_stage),
        "next_stage": {"key": next_stage["key"], "name": next_stage["name"]} if next_stage else None,
        "stages": result_stages,
        "history": state.get("history", []),
        "version_mismatch": bool(ws.template_version and ws.template_version != template.version),
    }


def advance_stage(
    db: Session,
    ws: Any,
    template: Any,
    user: Any,
    *,
    target_stage: str | None = None,
    force: bool = False,
    reason: str = "",
) -> dict[str, Any]:
    """推进到下一阶段（或显式目标阶段）；门禁未通过时抛 :class:`GateError`."""
    state = lifecycle_state(db, ws, template)
    stages = state["stages"]
    keys = [s["key"] for s in stages]
    if not stages:
        raise GateError("模板未定义阶段", {"reason": "no_stage"})
    current_index = state["current_stage_index"]
    if target_stage is None:
        if current_index + 1 >= len(stages):
            raise GateError("当前已是最后一个阶段", {"reason": "last_stage"})
        target = stages[current_index + 1]
    else:
        if target_stage not in keys:
            raise GateError(f"阶段不存在：{target_stage}", {"reason": "unknown_stage", "target_stage": target_stage})
        target_index = keys.index(target_stage)
        if target_index <= current_index:
            raise GateError("只能推进到后续阶段", {"reason": "backward", "target_stage": target_stage})
        target = stages[target_index]

    current = stages[current_index]
    if not current["gate_satisfied"] and not force:
        raise GateError(
            f"阶段「{current['name']}」门禁未通过，补齐表单 / 文档或强制推进",
            {"reason": "gate", "stage": current, "can_advance": state["can_advance"]},
        )
    old_stage = ws.template_stage
    ws.template_stage = target["key"]
    state_data = _state(ws)
    state_data["history"].append(
        {
            "from": old_stage,
            "to": target["key"],
            "at": _now(),
            "by": getattr(user, "id", None),
            "reason": reason,
            "forced": bool(force and not current["gate_satisfied"]),
        }
    )
    ws.template_state = state_data
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return lifecycle_state(db, ws, template)


__all__ = [
    "IMPACT_DETAIL_LIMIT",
    "GateError",
    "advance_stage",
    "apply_spec_to_workspace",
    "lifecycle_state",
    "preview_impact",
]
