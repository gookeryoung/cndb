"""工作区数据流程（需求 0095）：模板驱动的表单式增删查改元数据.

设计口径：
- 只读元数据接口：返回「阶段 → 表单 → 字段 / 列表 / 搜索 / 分组 / 操作开关」，
  前端据此渲染表单式 CRUD；真正写操作复用既有 records API，权限 / 校验 /
  修改申请 / 行级权限口径不另建一套。
- 表单映射来自 ``Workspace.template_state``，模板改名 / 改标题不影响关联。
- 操作开关同时受模板 flow 配置与表级 ``EDIT_RECORDS`` 约束（取交集）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core.access import TableAction, check_workspace_permission, preload_table_access
from cndb.plugins.tables.services.core.record_counts import batch_record_counts
from cndb.plugins.workspaces.models import WorkspaceRole, WorkspaceTemplate
from cndb.plugins.workspaces.routers.deps import _get_workspace_or_404
from cndb.plugins.workspaces.schemas.templates import (
    DataFlowField,
    DataFlowFlow,
    DataFlowForm,
    DataFlowResponse,
    DataFlowStage,
    DataFlowStep,
)
from cndb.plugins.workspaces.services.templates import project_context
from cndb.plugins.workspaces.services.templates.engine import lifecycle_state
from cndb.plugins.workspaces.services.templates.spec import normalize_spec

router = APIRouter(prefix="/workspaces", tags=["workspace-data-flow"])


def _template_or_404(db: Session, workspace: Any) -> WorkspaceTemplate:
    if workspace.template_id is None:
        raise HTTPException(status_code=404, detail="该工作区未使用模板，数据流程不可用")
    template = db.get(WorkspaceTemplate, workspace.template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="工作区引用的模板已不存在")
    return template


def _mapped_tables(db: Session, workspace: Any) -> dict[str, DataTable]:
    state = workspace.template_state or {}
    result: dict[str, DataTable] = {}
    for key, table_id in (state.get("form_tables") or {}).items():
        if not isinstance(table_id, int):
            continue
        table = db.get(DataTable, table_id)
        if table is not None and table.workspace_id == workspace.id and table.trashed_at is None:
            result[str(key)] = table
    return result


def _resolve_project(
    db: Session, workspace: Any, spec: dict[str, Any], project_id: int | None
) -> tuple[int | None, str]:
    """解析当前项目上下文：工作区模式返回 (None, workspace)；项目模式返回 (pid, project).

    多项目未选择 → 422 ``project_required``；根表单 0 行 → 409 ``project_empty``；
    跨工作区 / 跨表 → 404（不泄露存在性）。
    """
    project = project_context.project_config(spec)
    if workspace.project_mode != "project" or project is None:
        return None, "workspace"
    table = project_context.root_table(db, workspace, spec)
    rows: list[dict[str, Any]] = []
    total = 0
    if table is not None:
        from cndb.plugins.tables.services.core.records import list_rows

        rows, total = list_rows(db.get_bind(), table, limit=2, db=db)
    if not total:
        raise HTTPException(
            status_code=409, detail={"code": "project_empty", "message": "工作区还没有项目，请先创建项目"}
        )
    if project_id is None:
        if total == 1:
            return int(rows[0]["id"]), "project"
        raise HTTPException(
            status_code=422,
            detail={"code": "project_required", "message": "当前工作区有多个项目，请先选择项目"},
        )
    try:
        return project_context.resolve_project_row(db, workspace, spec, project_id), "project"
    except project_context.ProjectContextError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _field_payload(field: Any) -> DataFlowField:
    return DataFlowField(
        name=field.name,
        field_type=field.field_type,
        required=bool(field.required),
        config=dict(field.config or {}),
        order=int(field.order or 0),
        hidden=bool(field.hidden),
        default_value=field.default_value,
    )


@router.get("/{workspace_id}/data-flow", response_model=DataFlowResponse)
def get_data_flow(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    project_id: Annotated[int | None, Query(ge=1)] = None,
) -> DataFlowResponse:
    """读取模板驱动的数据流程配置（成员可读；阶段 / 表单 / 字段 / 操作开关）.

    ``project_id``：项目模式下按项目过滤；单项目自动选中，多项目必填。
    """
    workspace = _get_workspace_or_404(workspace_id, db)
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    template = _template_or_404(db, workspace)

    spec = normalize_spec(template.spec)
    project_id, project_mode = _resolve_project(db, workspace, spec, project_id)
    forms_by_key = {f["key"]: f for f in spec.get("forms", [])}
    project = project_context.project_config(spec)
    root_form = project.get("root_form") if project else None
    mapped = _mapped_tables(db, workspace)
    tables = list(mapped.values())
    preload = preload_table_access(db, tables, current_user)
    counts: dict[int, int | None] = batch_record_counts(db, tables) if tables else {}
    lifecycle = lifecycle_state(db, workspace, template, project_id)
    gate_by_stage = {s["key"]: s for s in lifecycle["stages"]}

    # 表单 payload 一次构建，阶段与流程共用（同一表单可在多条流程中复用）
    form_payloads: dict[str, DataFlowForm] = {}
    for form_key, form in forms_by_key.items():
        table = mapped.get(form_key)
        if table is None:
            continue
        if not preload.check(db, table, current_user, TableAction.READ):
            continue
        can_edit = preload.check(db, table, current_user, TableAction.EDIT_RECORDS)
        flow = form.get("flow") or {}
        scope = project_context.form_scope(spec, form_key) if project_mode == "project" else "workspace"
        if project_mode == "project" and scope == "project":
            if form_key == root_form:
                record_count = 1 if project_id is not None else 0
            else:
                record_count = (
                    project_context.count_project_rows(
                        db, table, project_context.link_field_for(project, form_key), project_id
                    )
                    if project_id is not None
                    else 0
                )
        else:
            record_count = int(counts.get(table.id, 0) or 0)
        form_payloads[form_key] = DataFlowForm(
            key=form_key,
            name=form["name"],
            description=form.get("description", ""),
            scope=scope,
            project_link_field=(
                project_context.link_field_for(project, form_key)
                if project_mode == "project" and scope == "project"
                else None
            ),
            table_id=table.id,
            table_name=table.name,
            flow=flow,
            fields=[_field_payload(f) for f in table.active_fields()],
            record_count=record_count,
            can_create=bool(can_edit and flow.get("allow_create", True)),
            can_edit=bool(can_edit and flow.get("allow_edit", True)),
            can_delete=bool(can_edit and flow.get("allow_delete", True)),
        )

    stages: list[DataFlowStage] = []
    for stage in spec.get("stages", []):
        flow = gate_by_stage.get(stage["key"], {})
        stages.append(
            DataFlowStage(
                key=stage["key"],
                name=stage["name"],
                description=stage.get("description", ""),
                order=stage.get("order", 0),
                is_current=bool(flow.get("is_current")),
                is_completed=bool(flow.get("is_completed")),
                gate_satisfied=bool(flow.get("gate_satisfied")),
                forms=[form_payloads[k] for k in stage.get("forms", []) if k in form_payloads],
            )
        )

    def _flow_stats(steps: list[DataFlowStep]) -> tuple[int, int, int]:
        table_ids = {s.form.table_id for s in steps if s.form is not None and s.form.table_id is not None}
        by_table = {
            s.form.table_id: s.form.record_count for s in steps if s.form is not None and s.form.table_id is not None
        }
        record_total = sum(int(by_table.get(table_id, 0) or 0) for table_id in table_ids)
        return len(table_ids), len(steps), record_total

    stage_names = {stage["key"]: stage["name"] for stage in spec.get("stages", [])}

    def _resolve_flow_stage(flow: dict[str, Any], steps: list[DataFlowStep]) -> str | None:
        explicit = flow.get("stage")
        if explicit:
            return explicit
        # 未显式声明的旧流程：按步骤表单在 stages 中的归属推断（首个命中优先）
        for step in steps:
            form_key = step.form.key if step.form is not None else None
            if form_key is None:
                continue
            for stage in spec.get("stages", []):
                if form_key in stage.get("forms", []):
                    return stage["key"]
        return None

    flows: list[DataFlowFlow] = []
    if spec.get("flows"):
        for flow in spec["flows"]:
            steps = [
                DataFlowStep(
                    key=step["key"],
                    name=step["name"],
                    description=step.get("description", ""),
                    form=form_payloads.get(step["form"]) if step.get("form") else None,
                    documents=list(step.get("documents", [])),
                )
                for step in flow.get("steps", [])
            ]
            form_count, step_count, record_total = _flow_stats(steps)
            stage_key = _resolve_flow_stage(flow, steps)
            flows.append(
                DataFlowFlow(
                    key=flow["key"],
                    name=flow["name"],
                    description=flow.get("description", ""),
                    stage=stage_key,
                    stage_name=stage_names.get(stage_key) if stage_key else None,
                    steps=steps,
                    form_count=form_count,
                    step_count=step_count,
                    record_count=record_total,
                )
            )
    else:
        # 旧模板没有 flows：按阶段派生「一阶段一流程」，保证前端始终有多流程视图
        for stage in spec.get("stages", []):
            steps: list[DataFlowStep] = []
            for idx, form_key in enumerate(stage.get("forms", [])):
                payload = form_payloads.get(form_key)
                steps.append(
                    DataFlowStep(
                        key=f"{stage['key']}-{form_key}",
                        name=payload.name if payload is not None else form_key,
                        description=payload.description if payload is not None else "",
                        form=payload,
                        documents=list(stage.get("documents", [])) if idx == 0 else [],
                    )
                )
            if not steps:
                steps.append(
                    DataFlowStep(
                        key=f"{stage['key']}-steps",
                        name=stage["name"],
                        description=stage.get("description", ""),
                        form=None,
                        documents=list(stage.get("documents", [])),
                    )
                )
            form_count, step_count, record_total = _flow_stats(steps)
            flows.append(
                DataFlowFlow(
                    key=f"stage-{stage['key']}",
                    name=stage["name"],
                    description=stage.get("description", ""),
                    stage=stage["key"],
                    stage_name=stage["name"],
                    steps=steps,
                    form_count=form_count,
                    step_count=step_count,
                    record_count=record_total,
                )
            )

    return DataFlowResponse(
        template_id=template.id,
        template_name=template.name,
        template_version=workspace.template_version or template.version,
        current_version=template.version,
        current_stage=lifecycle.get("current_stage"),
        current_stage_index=int(lifecycle.get("current_stage_index", 0)),
        can_advance=bool(lifecycle.get("can_advance")),
        next_stage=lifecycle.get("next_stage"),
        stages=stages,
        flows=flows,
        project_id=project_id,
        project_mode=project_mode,
    )


__all__ = ["router"]
