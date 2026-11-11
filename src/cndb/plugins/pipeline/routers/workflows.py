"""流水线路由：定义 CRUD / 校验 / 检查目录 / 手动触发 / 运行历史 / 发现物."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, CndbError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.services.visibility import visible_document_ids
from cndb.plugins.issues.services import get_issue_detail
from cndb.plugins.pipeline.models import (
    ACTIVE_RUN_STATUSES,
    CHANGE_TYPE_MANUAL,
    CHANGE_TYPE_ROLLBACK,
    PipelineFinding,
    PipelineRun,
    PipelineWorkflow,
    PipelineWorkflowVersion,
)
from cndb.plugins.pipeline.schemas import (
    CheckInputResponse,
    CheckSpecResponse,
    FindingListResponse,
    FindingResponse,
    RunClearResponse,
    RunListResponse,
    RunResponse,
    RunSummary,
    ValidateRequest,
    ValidateResponse,
    WorkflowCreate,
    WorkflowResponse,
    WorkflowUpdate,
    WorkflowVersionDetail,
    WorkflowVersionDiff,
    WorkflowVersionItem,
)
from cndb.plugins.pipeline.services.checks.registry import (
    CHECK_DOMAINS,
    assert_steps_in_enabled_modules,
    domain_of,
    iter_check_specs,
    module_of_domain,
    prefix_of,
    workflow_domains,
)
from cndb.plugins.pipeline.services.dsl.parse import compile_workflow
from cndb.plugins.pipeline.services.errors import PipelineConflictError
from cndb.plugins.pipeline.services.issue_bridge import convert_finding_to_issue
from cndb.plugins.pipeline.services.runner import (
    create_run,
    run_pipeline_in_background,
)
from cndb.plugins.pipeline.services.versions import (
    add_workflow_version,
    get_workflow_version,
    workflow_diff,
)
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/pipelines", tags=["pipeline"])


def _require(db: Session, workspace_id: int, user: User, role: WorkspaceRole) -> None:
    """工作区级角色门槛检查（D10）."""
    check_workspace_permission(db, workspace_id, user, role)


def _enabled_modules(db: Session, workspace_id: int) -> list[str]:
    """工作区已启用模块集合（工作区不存在时回退全模块，权限层会先 404）."""
    ws = db.get(Workspace, workspace_id)
    return list(ws.modules) if ws is not None else ["tables", "documents", "design"]


def _normalize_domain(domain: str | None) -> str | None:
    """校验 ``domain`` 查询参数（None = 不过滤；未注册域 400）."""
    if domain is None:
        return None
    if module_of_domain(domain) is None:
        raise BadRequestError(f"未知检查域：{domain}（可用：{', '.join(CHECK_DOMAINS)}）")
    return domain


def _domain_enabled(db: Session, workspace_id: int, domain: str) -> bool:
    """域对应的工作区模块是否已启用（未启用时本域无任何可见对象）."""
    return module_of_domain(domain) in _enabled_modules(db, workspace_id)


def _workflows_in_domain(db: Session, workspace_id: int, domain: str | None) -> list[PipelineWorkflow]:
    """工作区内按动作域过滤的流水线（跨域编排同时属于多个域）.

    ``domain`` 所属模块未启用时返回空（该模块的页面不可达，不给历史规则入口）；
    ``domain=None`` 保持全量（集中管理 / 存量规则仍可运行，ADR 0080 边界 #3）。
    """
    if domain is not None and not _domain_enabled(db, workspace_id, domain):
        return []
    rows = (
        db.query(PipelineWorkflow)
        .filter(PipelineWorkflow.workspace_id == workspace_id)
        .order_by(PipelineWorkflow.updated_at.desc(), PipelineWorkflow.id.desc())
        .all()
    )
    if domain is None:
        return rows
    return [row for row in rows if domain in workflow_domains(row.compiled)]


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
    domain: Annotated[str | None, Query()] = None,
) -> list[WorkflowResponse]:
    """列出工作区内的流水线定义（按更新时间倒序；``domain`` 只返回含该域动作的规则）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    rows = _workflows_in_domain(db, workspace_id, _normalize_domain(domain))
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
    # 保存期拒绝已禁用域的动作（ADR 0080 C4）
    assert_steps_in_enabled_modules(ir, _enabled_modules(db, workspace_id))
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
    db.flush()
    # 新建成功即落 v1（ADR 0114 C2）
    add_workflow_version(db, workflow, current_user, content=payload.content, change_type=CHANGE_TYPE_MANUAL)
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
    # 校验期同样拒绝已禁用域的动作（400，ADR 0080 C4）
    assert_steps_in_enabled_modules(ir, _enabled_modules(db, workspace_id))
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
    domain: Annotated[str | None, Query()] = None,
) -> list[CheckSpecResponse]:
    """只读检查动作目录（``uses`` + 输入 schema，供 DSL 插入辅助）.

    ``domain`` 给定时只返回该域动作（数据表检查 / 文档检查页各取所需）；
    两类过滤叠加：域所属模块未启用的工作区目录始终为空。
    """
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    target = _normalize_domain(domain)
    enabled = set(_enabled_modules(db, workspace_id))
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
        if domain_of(spec.uses) in enabled and (target is None or prefix_of(spec.uses) == target)
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


@router.get("/{workflow_id}/versions", response_model=list[WorkflowVersionItem])
def list_workflow_versions(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[WorkflowVersionItem]:
    """版本列表（版本号倒序，不含原文；成员可读）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    workflow = _workflow_or_404(db, workspace_id, workflow_id)
    rows = (
        db.query(PipelineWorkflowVersion)
        .filter(PipelineWorkflowVersion.workflow_id == workflow.id)
        .order_by(PipelineWorkflowVersion.version_number.desc())
        .all()
    )
    return [WorkflowVersionItem.model_validate(row) for row in rows]


@router.get("/{workflow_id}/versions/{version_number}", response_model=WorkflowVersionDetail)
def get_workflow_version_detail(
    workspace_id: int,
    workflow_id: int,
    version_number: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowVersionDetail:
    """单版详情（含 DSL 原文；成员可读）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    workflow = _workflow_or_404(db, workspace_id, workflow_id)
    return WorkflowVersionDetail.model_validate(get_workflow_version(db, workflow, version_number))


@router.get("/{workflow_id}/diff", response_model=WorkflowVersionDiff)
def diff_workflow_versions(
    workspace_id: int,
    workflow_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    base: Annotated[int, Query(ge=1)],
    head: Annotated[int, Query(ge=1)],
) -> WorkflowVersionDiff:
    """两版对比（unified diff + 增删行数；成员可读）."""
    _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    workflow = _workflow_or_404(db, workspace_id, workflow_id)
    return WorkflowVersionDiff(**workflow_diff(db, workflow, base, head))


@router.post("/{workflow_id}/versions/{version_number}/restore", response_model=WorkflowResponse)
def restore_workflow_version(
    workspace_id: int,
    workflow_id: int,
    version_number: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WorkflowResponse:
    """按历史原文恢复（重新编译后写回内容 / 编译产物 / 名称，保留启用状态）.

    失败零写入（I5）：DSL 非法 400，名称冲突 409；成功落一条 ``rollback`` 版本。
    """
    _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    workflow = _workflow_or_404(db, workspace_id, workflow_id)
    version = get_workflow_version(db, workflow, version_number)
    ir = compile_workflow(version.content, fallback_name=workflow.name)
    assert_steps_in_enabled_modules(ir, _enabled_modules(db, workspace_id))
    _assert_name_available(db, workspace_id, ir.name, exclude_id=workflow.id)
    workflow.content = version.content
    workflow.compiled = ir.to_dict()
    workflow.name = ir.name
    add_workflow_version(
        db,
        workflow,
        current_user,
        content=version.content,
        change_type=CHANGE_TYPE_ROLLBACK,
        comment=f"恢复自 v{version_number}",
    )
    db.commit()
    db.refresh(workflow)
    return _workflow_response(db, workflow)


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
    new_content = payload.content
    content_changed = new_content is not None and new_content != workflow.content
    if new_content is not None:
        ir = compile_workflow(new_content, fallback_name=target_name)
        # 更新期拒绝已禁用域的动作（ADR 0080 C4）
        assert_steps_in_enabled_modules(ir, _enabled_modules(db, workspace_id))
        target_name = ir.name
        workflow.content = new_content
        workflow.compiled = ir.to_dict()
    _assert_name_available(db, workspace_id, target_name, exclude_id=workflow.id)
    workflow.name = target_name
    if payload.enabled is not None:
        workflow.enabled = payload.enabled
    if new_content is not None and content_changed:
        # 仅内容实际变化时落版；只切 enabled 不产生版本（ADR 0114 §4）
        add_workflow_version(db, workflow, current_user, content=new_content, change_type=CHANGE_TYPE_MANUAL)
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
    # 版本行显式清理（ADR 0114 §4.8）
    db.execute(delete(PipelineWorkflowVersion).where(PipelineWorkflowVersion.workflow_id == workflow.id))
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


def _workspace_run_filters(
    db: Session,
    workspace_id: int,
    workflow_id: int | None,
    domain: str | None,
) -> list[Any]:
    """运行历史的统一过滤条件（列表与清空共用，避免两处口径漂移）.

    ``workflow_id`` 与 ``domain`` 同时给定时取交集；``domain`` 未注册直接 400。
    """
    filters: list[Any] = [PipelineRun.workspace_id == workspace_id]
    target = _normalize_domain(domain)
    if target is not None:
        workflow_ids = [row.id for row in _workflows_in_domain(db, workspace_id, target)]
        filters.append(PipelineRun.workflow_id.in_(workflow_ids))
    if workflow_id is not None:
        filters.append(PipelineRun.workflow_id == workflow_id)
    return filters


def _finding_response(finding: PipelineFinding) -> FindingResponse:
    """发现物 ORM → 响应."""
    return FindingResponse.model_validate(finding)


#: document/sensitive 返回的上下文 detail 键（不可见文档必须裁剪）
_CONTEXT_DETAIL_KEYS = ("document_title", "snippet", "match", "match_start", "match_end")


def _redact_hidden_finding_context(
    db: Session,
    workspace_id: int,
    current_user: User,
    items: list[FindingResponse],
) -> list[FindingResponse]:
    """按文档可见性裁剪命中上下文：他人草稿 / 归档文档不对普通成员暴露正文片段."""
    document_ids = {
        int(item.target_id)
        for item in items
        if item.target_type == "document" and item.target_id is not None and item.detail
    }
    if not document_ids:
        return items
    visible = visible_document_ids(db, workspace_id, current_user, document_ids)
    hidden = document_ids - visible
    if not hidden:
        return items
    redacted: list[FindingResponse] = []
    for item in items:
        detail = dict(item.detail or {})
        if (
            item.target_type == "document"
            and item.target_id in hidden
            and any(key in detail for key in _CONTEXT_DETAIL_KEYS)
        ):
            for key in _CONTEXT_DETAIL_KEYS:
                detail.pop(key, None)
            detail["redacted"] = True
            item = item.model_copy(update={"detail": detail})
        redacted.append(item)
    return redacted


def _build_run_router() -> APIRouter:
    """运行详情 / 发现物路由（独立前缀 ``/{workspace_id}/pipeline-runs``）."""
    run_router = APIRouter(prefix="/{workspace_id}/pipeline-runs", tags=["pipeline"])

    @run_router.get("", response_model=RunListResponse)
    def list_workspace_runs(
        workspace_id: int,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        workflow_id: Annotated[int | None, Query()] = None,
        domain: Annotated[str | None, Query()] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> RunListResponse:
        """工作区运行历史（默认全部规则；``workflow_id`` / ``domain`` 可选过滤，按创建时间倒序分页）."""
        _require(db, workspace_id, current_user, WorkspaceRole.VIEWER)
        filters = _workspace_run_filters(db, workspace_id, workflow_id, domain)
        query = db.query(PipelineRun).filter(*filters)
        total = query.count()
        rows = query.order_by(PipelineRun.created_at.desc(), PipelineRun.id.desc()).offset(offset).limit(limit).all()
        return RunListResponse(total=total, items=[_run_response(db, run) for run in rows])

    @run_router.delete("", response_model=RunClearResponse)
    def clear_runs(
        workspace_id: int,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
        workflow_id: Annotated[int | None, Query()] = None,
        domain: Annotated[str | None, Query()] = None,
    ) -> RunClearResponse:
        """清空运行历史（过滤口径与列表一致；范围内有活跃运行时整体拒绝 409）."""
        _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
        filters = _workspace_run_filters(db, workspace_id, workflow_id, domain)
        active = db.query(PipelineRun).filter(*filters, PipelineRun.status.in_(ACTIVE_RUN_STATUSES)).count()
        if active:
            raise PipelineConflictError(f"还有 {active} 条运行正在进行中，结束后才能清空")
        deleted = db.query(PipelineRun).filter(*filters).count()
        run_ids = select(PipelineRun.id).where(*filters)
        db.execute(delete(PipelineFinding).where(PipelineFinding.run_id.in_(run_ids)))
        db.execute(delete(PipelineRun).where(*filters))
        db.commit()
        return RunClearResponse(deleted=deleted)

    @run_router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_run(
        workspace_id: int,
        run_id: int,
        current_user: Annotated[User, Depends(get_current_user)],
        db: Annotated[Session, Depends(get_db)],
    ) -> None:
        """删除单条运行（活跃运行 409；检查发现物一并删除）."""
        _require(db, workspace_id, current_user, WorkspaceRole.EDITOR)
        run = _run_from_workspace(db, workspace_id, run_id)
        if run.status in ACTIVE_RUN_STATUSES:
            raise PipelineConflictError("运行正在进行中，结束后才能删除")
        db.execute(delete(PipelineFinding).where(PipelineFinding.run_id == run.id))
        db.delete(run)
        db.commit()

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
        items = _redact_hidden_finding_context(db, workspace_id, current_user, [_finding_response(row) for row in rows])
        return FindingListResponse(total=total, items=items)

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
