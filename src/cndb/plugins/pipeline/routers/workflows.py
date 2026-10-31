"""流水线路由：定义 CRUD / 校验 / 检查目录 / 手动触发 / 运行历史 / 发现物."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import CndbError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.issues.services import get_issue_detail
from cndb.plugins.pipeline.models import (
    PipelineFinding,
    PipelineRun,
    PipelineWorkflow,
)
from cndb.plugins.pipeline.schemas import (
    CheckInputResponse,
    CheckSpecResponse,
    FindingListResponse,
    FindingResponse,
    RunListResponse,
    RunResponse,
    RunSummary,
    ValidateRequest,
    ValidateResponse,
    WorkflowCreate,
    WorkflowResponse,
    WorkflowUpdate,
)
from cndb.plugins.pipeline.services.checks.registry import iter_check_specs
from cndb.plugins.pipeline.services.dsl.parse import compile_workflow
from cndb.plugins.pipeline.services.errors import PipelineConflictError
from cndb.plugins.pipeline.services.issue_bridge import convert_finding_to_issue
from cndb.plugins.pipeline.services.runner import (
    create_run,
    run_pipeline_in_background,
)
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/pipelines", tags=["pipeline"])


def _require(db: Session, workspace_id: int, user: User, role: WorkspaceRole) -> None:
    """工作区级角色门槛检查（D10）."""
    check_workspace_permission(db, workspace_id, user, role)


def _workflow_or_404(db: Session, workspace_id: int, workflow_id: int) -> PipelineWorkflow:
    """按工作区 + 定义 ID 取流水线（不存在 404）."""
    workflow = (
        db.query(PipelineWorkflow)
        .filter(PipelineWorkflow.id == workflow_id, PipelineWorkflow.workspace_id == workspace_id)
        .first()
    )
    if workflow is None:
        raise NotFoundError("流水线不存在", code="pipeline_not_found")
    return workflow


def _workflow_response(db: Session, workflow: PipelineWorkflow) -> WorkflowResponse:
    """补最近一次运行摘要后的定义响应."""
    response = WorkflowResponse.model_validate(workflow)
    last = db.query(PipelineRun).filter(PipelineRun.workflow_id == workflow.id).order_by(PipelineRun.id.desc()).first()
    if last is not None:
        response.last_run = RunSummary(
            id=last.id,
            status=last.status,
            trigger=last.trigger,
            stats=last.stats or {},
            created_at=last.created_at,
        )
    return response


def _run_response(db: Session, run: PipelineRun) -> RunResponse:
    """补定义名后的运行响应."""
    response = RunResponse.model_validate(run)
    workflow = db.get(PipelineWorkflow, run.workflow_id)
    response.workflow_name = workflow.name if workflow is not None else ""
    return response


def _assert_name_available(db: Session, workspace_id: int, name: str, *, exclude_id: int | None = None) -> None:
    """同工作区内定义名唯一（冲突 409）."""
    query = db.query(PipelineWorkflow).filter(
        PipelineWorkflow.workspace_id == workspace_id,
        PipelineWorkflow.name == name,
    )
    if exclude_id is not None:
        query = query.filter(PipelineWorkflow.id != exclude_id)
    if query.first() is not None:
        raise PipelineConflictError(f"同名流水线已存在：{name}")


@router.get("", response_model=list[WorkflowResponse])
def list_workflows(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkflowResponse]:
    """列出工作区内的流水线定义（按更新时间倒序）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    rows = (
        db.query(PipelineWorkflow)
        .filter(PipelineWorkflow.workspace_id == workspace_id)
        .order_by(PipelineWorkflow.updated_at.desc(), PipelineWorkflow.id.desc())
        .all()
    )
    return [_workflow_response(db, row) for row in rows]


@router.post("", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
def create_workflow(
    workspace_id: int,
    payload: WorkflowCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowResponse:
    """新建流水线（保存期编译校验，DSL 非法返回 400）."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    ir = compile_workflow(payload.content, fallback_name=payload.name or "")
    _assert_name_available(db, workspace_id, ir.name)
    workflow = PipelineWorkflow(
        workspace_id=workspace_id,
        name=ir.name,
        content=payload.content,
        compiled=ir.to_dict(),
        enabled=payload.enabled,
        created_by_id=current_user.id,
    )
    db.add(workflow)
    db.commit()
    db.refresh(workflow)
    return _workflow_response(db, workflow)


@router.post("/validate", response_model=ValidateResponse)
def validate_workflow(
    workspace_id: int,
    payload: ValidateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ValidateResponse:
    """纯编译校验（不落库，编辑器实时校验用）."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    try:
        ir = compile_workflow(payload.content, fallback_name=payload.name or "")
    except CndbError as exc:
        return ValidateResponse(ok=False, error=exc.detail)
    return ValidateResponse(
        ok=True,
        name=ir.name,
        job_count=len(ir.jobs),
        step_count=sum(len(job.steps) for job in ir.jobs),
    )


@router.get("/checks", response_model=list[CheckSpecResponse])
def list_checks(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[CheckSpecResponse]:
    """只读检查动作目录（``uses`` + 输入 schema，供 DSL 插入辅助）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return [
        CheckSpecResponse(
            uses=spec.uses,
            title=spec.title,
            category=spec.category,
            severity=spec.default_severity,
            target_types=list(spec.target_types),
            inputs=[
                CheckInputResponse(
                    name=item.name,
                    type=item.type,
                    description=item.description,
                    required=item.required,
                    default=item.default,
                )
                for item in spec.inputs
            ],
        )
        for spec in iter_check_specs()
    ]


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowResponse:
    """流水线详情（含编译产物与最近一次运行）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return _workflow_response(db, _workflow_or_404(db, workspace_id, workflow_id))


@router.put("/{workflow_id}", response_model=WorkflowResponse)
def update_workflow(
    workspace_id: int,
    workflow_id: int,
    payload: WorkflowUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowResponse:
    """更新流水线（内容变更时重新编译，失败 400 且不落库）."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    workflow = _workflow_or_404(db, workspace_id, workflow_id)
    target_name = payload.name if payload.name is not None else workflow.name
    if payload.content is not None:
        ir = compile_workflow(payload.content, fallback_name=target_name)
        target_name = ir.name
        workflow.content = payload.content
        workflow.compiled = ir.to_dict()
    _assert_name_available(db, workspace_id, target_name, exclude_id=workflow.id)
    workflow.name = target_name
    if payload.enabled is not None:
        workflow.enabled = payload.enabled
    db.commit()
    db.refresh(workflow)
    return _workflow_response(db, workflow)


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workflow(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除流水线（级联清理运行与发现物）."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    workflow = _workflow_or_404(db, workspace_id, workflow_id)
    run_ids = select(PipelineRun.id).where(PipelineRun.workflow_id == workflow.id)
    db.execute(delete(PipelineFinding).where(PipelineFinding.run_id.in_(run_ids)))
    db.execute(delete(PipelineRun).where(PipelineRun.workflow_id == workflow.id))
    db.delete(workflow)
    db.commit()


@router.post("/{workflow_id}/run", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
def trigger_run(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RunResponse:
    """手动触发（202；同流水线已有活跃运行时 409）."""
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    workflow = _workflow_or_404(db, workspace_id, workflow_id)
    run = create_run(db, workflow)
    factory = sessionmaker(bind=db.get_bind(), autocommit=False, autoflush=False)
    run_pipeline_in_background(factory, run.id)
    return _run_response(db, run)


@router.get("/{workflow_id}/runs", response_model=RunListResponse)
def list_runs(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RunListResponse:
    """运行历史（按创建时间倒序，分页）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    workflow = _workflow_or_404(db, workspace_id, workflow_id)
    query = db.query(PipelineRun).filter(PipelineRun.workflow_id == workflow.id)
    total = query.count()
    rows = query.order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc()).offset(offset).limit(limit).all()
    return RunListResponse(total=total, items=[_run_response(db, run) for run in rows])


def _run_from_workspace(db: Session, workspace_id: int, run_id: int) -> PipelineRun:
    """按工作区 + 运行 ID 取运行（不存在 404）."""
    run = db.query(PipelineRun).filter(PipelineRun.id == run_id, PipelineRun.workspace_id == workspace_id).first()
    if run is None:
        raise NotFoundError("运行记录不存在", code="pipeline_run_not_found")
    return run


def _finding_response(finding: PipelineFinding) -> FindingResponse:
    """发现物 ORM → 响应."""
    return FindingResponse.model_validate(finding)


def _build_run_router() -> APIRouter:
    """运行详情 / 发现物路由（独立前缀 ``/{workspace_id}/pipeline-runs``）."""
    run_router = APIRouter(prefix="/{workspace_id}/pipeline-runs", tags=["pipeline"])

    @run_router.get("/{run_id}", response_model=RunResponse)
    def get_run(
        workspace_id: int,
        run_id: int,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> RunResponse:
        """运行详情（job / step 结论树 + finding 计数）."""
        _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
        return _run_response(db, _run_from_workspace(db, workspace_id, run_id))

    @run_router.get("/{run_id}/findings", response_model=FindingListResponse)
    def list_findings(
        workspace_id: int,
        run_id: int,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        severity: Annotated[str | None, Query()] = None,
        target_type: Annotated[str | None, Query()] = None,
        check: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> FindingListResponse:
        """发现物列表（按严重度 / 目标类型 / 检查动作过滤，分页）."""
        _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
        run = _run_from_workspace(db, workspace_id, run_id)
        query = db.query(PipelineFinding).filter(PipelineFinding.run_id == run.id)
        if severity:
            query = query.filter(PipelineFinding.severity == severity)
        if target_type:
            query = query.filter(PipelineFinding.target_type == target_type)
        if check:
            query = query.filter(PipelineFinding.check == check)
        total = query.count()
        rows = query.order_by(PipelineFinding.id).offset(offset).limit(limit).all()
        return FindingListResponse(total=total, items=[_finding_response(row) for row in rows])

    @run_router.post("/{run_id}/findings/{finding_id}/issue", status_code=status.HTTP_201_CREATED)
    def create_issue_from_finding(
        workspace_id: int,
        run_id: int,
        finding_id: int,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> dict[str, Any]:
        """把表目标发现物一键转成所属数据表的问题（非表目标 400）."""
        _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
        issue = convert_finding_to_issue(db, workspace_id, run_id, finding_id, current_user)
        return get_issue_detail(db, issue)

    return run_router


runs_router = _build_run_router()

__all__ = ["router", "runs_router"]
