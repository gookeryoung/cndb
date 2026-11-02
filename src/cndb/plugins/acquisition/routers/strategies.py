"""采集策略路由（``/api/v1/workspaces/{wid}/acquisition``，ADR 0085 §7）.

权限：读 = VIEWER；写 / 运行 = EDITOR（与 datasource 同步任务同口径）。
本期运行同步执行（受 ``iteration.budget.max_requests`` 约束），调度接入在 P2。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.acquisition.models import AcquisitionRound, AcquisitionRun, AcquisitionStrategy, RunTrigger
from cndb.plugins.acquisition.schemas import (
    ChannelCatalogResponse,
    ChannelOption,
    DiagnoseResponse,
    PreviewRequest,
    PreviewResponse,
    PreviewSample,
    ProviderOption,
    ResumeRequest,
    RoundOut,
    RuleDraftRequest,
    RuleDraftResponse,
    RuleValidateRequest,
    RuleValidateResponse,
    RunDetailResponse,
    RunListResponse,
    RunOut,
    StrategyCreate,
    StrategyListResponse,
    StrategyOut,
    StrategyUpdate,
)
from cndb.plugins.acquisition.services.channels import preset_catalog
from cndb.plugins.acquisition.services.rules.expr import RuleError
from cndb.plugins.acquisition.services.runner import (
    StrategyBusyError,
    execute_strategy,
    preview_strategy,
    resume_run,
)
from cndb.plugins.acquisition.services.validation import validate_strategy_payload
from cndb.plugins.datasource.models import DatasourceSyncJob
from cndb.plugins.datasource.providers.registry import list_providers
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/acquisition", tags=["acquisition"])

#: 视为「实质变更」的字段（变更即 rule_version +1 并回 draft）
_RULE_FIELDS = ("scope", "filter_rule", "targets", "iteration")


def _serialize_strategy(strategy: AcquisitionStrategy) -> StrategyOut:
    return StrategyOut(
        id=strategy.id,
        workspace_id=strategy.workspace_id,
        name=strategy.name,
        enabled=strategy.enabled,
        scope=dict(strategy.scope or {}),
        filter_rule=dict(strategy.filter_rule or {}),
        targets=list(strategy.targets or []),
        iteration=dict(strategy.iteration or {}),
        llm=dict(strategy.llm or {}),
        schedule=dict(strategy.schedule or {}),
        rule_version=strategy.rule_version,
        last_run_at=strategy.last_run_at,
        last_status=strategy.last_status,
        created_at=strategy.created_at,
        updated_at=strategy.updated_at,
    )


def _serialize_run(run: AcquisitionRun) -> RunOut:
    return RunOut(
        id=run.id,
        strategy_id=run.strategy_id,
        trigger=run.trigger,
        status=run.status,
        round_count=run.round_count,
        progress=run.progress,
        progress_message=run.progress_message,
        fetched=run.fetched,
        inserted=run.inserted,
        updated=run.updated,
        skipped=run.skipped,
        docs_created=run.docs_created,
        docs_updated=run.docs_updated,
        docs_skipped=run.docs_skipped,
        budget_used=dict(run.budget_used or {}),
        error_message=run.error_message,
        detail=dict(run.detail or {}),
        started_at=run.started_at,
        finished_at=run.finished_at,
        duration_ms=run.duration_ms,
    )


def _serialize_round(row: AcquisitionRound) -> RoundOut:
    return RoundOut(
        id=row.id,
        run_id=row.run_id,
        round_no=row.round_no,
        query=row.query,
        channels=list(row.channels or []),
        stats=dict(row.stats or {}),
        new_items=row.new_items,
        accumulated_items=row.accumulated_items,
        top_keywords=list(row.top_keywords or []),
        next_query=row.next_query,
        gap=dict(row.gap or {}),
        review_state=row.review_state,
        stop_reason=row.stop_reason,
        status=row.status,
        error_message=row.error_message,
        duration_ms=row.duration_ms,
    )


def _get_run(db: Session, workspace_id: int, run_id: int) -> AcquisitionRun:
    """取运行记录并校验其策略归属当前工作区."""
    run = db.get(AcquisitionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    strategy = db.get(AcquisitionStrategy, run.strategy_id)
    if strategy is None or strategy.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="运行记录不存在")
    return run


def _get_strategy(db: Session, workspace_id: int, strategy_id: int) -> AcquisitionStrategy:
    strategy = db.get(AcquisitionStrategy, strategy_id)
    if strategy is None or strategy.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="采集策略不存在")
    return strategy


def _assert_targets_in_workspace(db: Session, workspace_id: int, targets: list[dict[str, Any]]) -> None:
    """落点必须指向同工作区的表 / 文件夹（越权 / 跨工作区直接 400）."""
    from cndb.plugins.documents.models import Document

    for target in targets:
        kind = str(target.get("kind"))
        if kind == "table":
            table = db.get(DataTable, int(target["table_id"]))
            if table is None or table.workspace_id != workspace_id or getattr(table, "is_deleted", False):
                raise HTTPException(status_code=400, detail=f"目标表不存在或不属于当前工作区: {target['table_id']}")
            continue
        if kind == "document" and target.get("parent_id") is not None:
            parent = db.get(Document, int(target["parent_id"]))
            if (
                parent is None
                or parent.workspace_id != workspace_id
                or not parent.is_folder
                or getattr(parent, "is_deleted", False)
            ):
                raise HTTPException(
                    status_code=400, detail=f"目标文件夹不存在或不属于当前工作区: {target['parent_id']}"
                )


def _validate(
    db: Session,
    workspace_id: int,
    *,
    scope: dict[str, Any],
    filter_rule: dict[str, Any],
    targets: list[dict[str, Any]],
    iteration: dict[str, Any],
    schedule: dict[str, Any] | None = None,
) -> None:
    try:
        validate_strategy_payload(
            scope=scope,
            filter_rule=filter_rule,
            targets=targets,
            iteration=iteration,
            schedule=schedule,
        )
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _assert_targets_in_workspace(db, workspace_id, targets)


@router.get("/strategies", response_model=StrategyListResponse)
def list_strategies(
    workspace_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> StrategyListResponse:
    """列出工作区内的采集策略（按创建倒序）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)
    stmt = (
        select(AcquisitionStrategy)
        .where(AcquisitionStrategy.workspace_id == workspace_id)
        .order_by(AcquisitionStrategy.id.desc())
    )
    rows = list(db.execute(stmt).scalars())
    return StrategyListResponse(total=len(rows), strategies=[_serialize_strategy(row) for row in rows])


@router.post("/strategies", response_model=StrategyOut, status_code=201)
def create_strategy(
    workspace_id: int,
    payload: StrategyCreate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> StrategyOut:
    """新建策略（``enabled`` 默认 False，需先预览再启用）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    _validate(
        db,
        workspace_id,
        scope=payload.scope,
        filter_rule=payload.filter_rule,
        targets=payload.targets,
        iteration=payload.iteration,
        schedule=payload.schedule,
    )
    strategy = AcquisitionStrategy(
        workspace_id=workspace_id,
        created_by_id=user.id,
        name=payload.name.strip(),
        enabled=payload.enabled,
        scope=payload.scope,
        filter_rule=payload.filter_rule,
        targets=payload.targets,
        iteration=payload.iteration,
        llm=payload.llm,
        schedule=payload.schedule,
    )
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return _serialize_strategy(strategy)


@router.get("/strategies/{strategy_id}", response_model=StrategyOut)
def get_strategy(
    workspace_id: int,
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> StrategyOut:
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)
    return _serialize_strategy(_get_strategy(db, workspace_id, strategy_id))


@router.put("/strategies/{strategy_id}", response_model=StrategyOut)
def update_strategy(
    workspace_id: int,
    strategy_id: int,
    payload: StrategyUpdate,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> StrategyOut:
    """更新策略：实质规则变更 → ``rule_version`` +1 并回到未启用态（D3）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    strategy = _get_strategy(db, workspace_id, strategy_id)
    data = payload.model_dump(exclude_unset=True)

    scope = data.get("scope", dict(strategy.scope or {}))
    filter_rule = data.get("filter_rule", dict(strategy.filter_rule or {}))
    targets = data.get("targets", list(strategy.targets or []))
    iteration = data.get("iteration", dict(strategy.iteration or {}))
    schedule = data.get("schedule", dict(strategy.schedule or {}))
    _validate(
        db,
        workspace_id,
        scope=scope,
        filter_rule=filter_rule,
        targets=targets,
        iteration=iteration,
        schedule=schedule,
    )

    changed_rules = any(field in data for field in _RULE_FIELDS)
    if "name" in data:
        strategy.name = str(data["name"]).strip()
    strategy.scope = scope
    strategy.filter_rule = filter_rule
    strategy.targets = targets
    strategy.iteration = iteration
    if "llm" in data:
        strategy.llm = data["llm"] or {}
    if "schedule" in data:
        strategy.schedule = data["schedule"] or {}
    if "enabled" in data:
        strategy.enabled = bool(data["enabled"])
    if changed_rules:
        strategy.rule_version += 1
        strategy.enabled = False
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return _serialize_strategy(strategy)


@router.delete("/strategies/{strategy_id}", status_code=204)
def delete_strategy(
    workspace_id: int,
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> None:
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    strategy = _get_strategy(db, workspace_id, strategy_id)
    db.delete(strategy)
    db.commit()


@router.post("/strategies/{strategy_id}/run", response_model=RunOut)
def run_strategy(
    workspace_id: int,
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RunOut:
    """立即运行一次（同步执行，返回终态运行记录；租约被占用返回 409）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    strategy = _get_strategy(db, workspace_id, strategy_id)
    try:
        execution = execute_strategy(db, strategy, trigger=RunTrigger.MANUAL, user=user)
    except StrategyBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if execution.run is None:
        raise HTTPException(status_code=500, detail="运行记录缺失")
    return _serialize_run(execution.run)


@router.post("/strategies/{strategy_id}/preview", response_model=PreviewResponse)
def preview_strategy_route(
    workspace_id: int,
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    payload: PreviewRequest | None = None,
) -> PreviewResponse:
    """抓一次并筛选，不写表 / 不写台账 / 不落运行记录.

    请求体可带 ``query`` / ``filter_rule``：用编辑器当前（可能未保存）的检索式与筛选试算。
    """
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)
    strategy = _get_strategy(db, workspace_id, strategy_id)
    execution = preview_strategy(
        db,
        strategy,
        user=user,
        query=payload.query if payload else None,
        filter_rule=payload.filter_rule if payload else None,
    )
    return PreviewResponse(
        status=execution.status,
        collected=execution.collected,
        after_dedup=execution.after_dedup,
        after_filter=execution.after_filter,
        rejected_by=dict(execution.rejected_by),
        by_channel=dict(execution.by_channel),
        samples=[
            PreviewSample(
                title=str(item.get("title") or ""),
                url=str(item.get("url") or item.get("source_url") or ""),
                published_at=str(item.get("published_at") or ""),
                match_score=int(item.get("match_score") or 0),
            )
            for item in execution.samples
        ],
        channel_errors=execution.channel_errors,
    )


@router.get("/strategies/{strategy_id}/runs", response_model=RunListResponse)
def list_runs(
    workspace_id: int,
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = 20,
) -> RunListResponse:
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)
    _get_strategy(db, workspace_id, strategy_id)
    stmt = (
        select(AcquisitionRun)
        .where(AcquisitionRun.strategy_id == strategy_id)
        .order_by(AcquisitionRun.id.desc())
        .limit(max(1, min(limit, 100)))
    )
    rows = list(db.execute(stmt).scalars())
    return RunListResponse(total=len(rows), runs=[_serialize_run(row) for row in rows])


@router.get("/runs/{run_id}", response_model=RunDetailResponse)
def get_run(
    workspace_id: int,
    run_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RunDetailResponse:
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)
    run = _get_run(db, workspace_id, run_id)
    rounds = list(
        db.execute(
            select(AcquisitionRound).where(AcquisitionRound.run_id == run_id).order_by(AcquisitionRound.round_no)
        ).scalars()
    )
    return RunDetailResponse(run=_serialize_run(run), rounds=[_serialize_round(row) for row in rounds])


@router.post("/runs/{run_id}/resume", response_model=RunOut)
def resume_run_route(
    workspace_id: int,
    run_id: int,
    payload: ResumeRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RunOut:
    """复核后续跑：带关键词 / 检索式即「调整」，全空即「不调」直接进下一轮."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    run = _get_run(db, workspace_id, run_id)
    try:
        execution = resume_run(db, run, user=user, keywords=payload.keywords, query=payload.query)
    except StrategyBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuleError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if execution.run is None:
        raise HTTPException(status_code=500, detail="运行记录缺失")
    return _serialize_run(execution.run)


@router.get("/channels", response_model=ChannelCatalogResponse)
def list_channels(
    workspace_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ChannelCatalogResponse:
    """渠道目录：可引用的既有同步任务 + 渠道简写 + 已注册 provider（P3）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)
    jobs = (
        db.execute(
            select(DatasourceSyncJob)
            .where(DatasourceSyncJob.workspace_id == workspace_id)
            .order_by(DatasourceSyncJob.id)
        )
        .scalars()
        .all()
    )
    channels = [
        ChannelOption(
            value=f"job:{job.id}",
            label=f"{job.name}（{job.provider}）",
            kind="job",
            provider=job.provider,
            requires_key=bool(job.session_id),
            hint="复用既有同步任务的请求模板与凭证",
        )
        for job in jobs
    ]
    channels.extend(ChannelOption(**item) for item in preset_catalog())
    providers = [
        ProviderOption(
            name=str(item["name"]),
            label=str(item["label"]),
            params_schema=dict(item.get("params_schema") or {}),
            supports_paging=bool(item.get("supports_paging")),
        )
        for item in list_providers()
    ]
    return ChannelCatalogResponse(
        channels=channels,
        providers=providers,
        llm_actions=["keyword_refine", "rule_draft", "item_summary", "run_report", "failure_diagnose"],
    )


@router.post("/rule-drafts", response_model=RuleDraftResponse)
def create_rule_draft(
    workspace_id: int,
    payload: RuleDraftRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RuleDraftResponse:
    """自然语言需求 → 规则草案（只回草案，**不落策略、不自动启用**，ADR 0085 §5 A）."""
    from cndb.plugins.acquisition.services import ai as acquisition_ai
    from cndb.plugins.documents.models import Document

    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    jobs = (
        db.execute(
            select(DatasourceSyncJob)
            .where(DatasourceSyncJob.workspace_id == workspace_id)
            .order_by(DatasourceSyncJob.id)
        )
        .scalars()
        .all()
    )
    presets = preset_catalog()
    allowed_channels = [f"job:{job.id}" for job in jobs] + [str(item["value"]) for item in presets]

    tables = (
        db.execute(
            select(DataTable)
            .where(DataTable.workspace_id == workspace_id, DataTable.trashed_at.is_(None))
            .order_by(DataTable.id)
        )
        .scalars()
        .all()
    )
    folders = (
        db.execute(
            select(Document)
            .where(
                Document.workspace_id == workspace_id,
                Document.is_folder.is_(True),
                Document.is_deleted.is_(False),
            )
            .order_by(Document.id)
        )
        .scalars()
        .all()
    )
    context_lines = [
        *(f"表 id={table.id} 名称={table.name} 字段={table.name}" for table in tables),
        *(f"文件夹 id={folder.id} 名称={folder.title}" for folder in folders),
    ]

    draft, meta = acquisition_ai.draft_rules(
        db,
        user,
        description=payload.description,
        allowed_channels=allowed_channels,
        allowed_table_ids=[int(table.id) for table in tables],
        allowed_folder_ids=[int(folder.id) for folder in folders],
        context_lines=context_lines,
        workspace_id=workspace_id,
    )
    # 提示优先落点：模型没选时用请求里的 table_id / parent_id 兜底（仍是草案，由用户确认）
    table_ids = {int(table.id) for table in tables}
    folder_ids = {int(folder.id) for folder in folders}
    if not draft["targets"] and payload.table_id in table_ids:
        draft["targets"] = [{"kind": "table", "table_id": payload.table_id, "match_keys": list[str]()}]
    elif not draft["targets"] and payload.parent_id in folder_ids:
        draft["targets"] = [{"kind": "document", "parent_id": payload.parent_id}]

    return RuleDraftResponse(
        draft=draft,
        model=str(meta.get("model") or ""),
        run_id=meta.get("run_id"),
        degraded=str(meta.get("degraded") or ""),
        error=str(meta.get("error") or ""),
    )


@router.post("/runs/{run_id}/diagnose", response_model=DiagnoseResponse)
def diagnose_run_route(
    workspace_id: int,
    run_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DiagnoseResponse:
    """失败诊断（只读）：模型不可用 → 规则化文案（ADR 0085 §5 E）."""
    from cndb.plugins.acquisition.services import ai as acquisition_ai

    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)
    run = _get_run(db, workspace_id, run_id)
    rounds = db.execute(
        select(AcquisitionRound).where(AcquisitionRound.run_id == run.id).order_by(AcquisitionRound.round_no)
    ).scalars()
    payload = [
        {
            "round_no": row.round_no,
            "query": row.query,
            "stats": dict(row.stats or {}),
            "stop_reason": row.stop_reason,
        }
        for row in rounds
    ]
    text, meta = acquisition_ai.diagnose_run(
        db,
        user,
        run=run,
        rounds=payload,
        workspace_id=workspace_id,
    )
    return DiagnoseResponse(
        text=text,
        model=str(meta.get("model") or ""),
        run_id=meta.get("run_id"),
        degraded=str(meta.get("degraded") or ""),
    )


@router.post("/runs/{run_id}/cancel", response_model=RunOut)
def cancel_run(
    workspace_id: int,
    run_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RunOut:
    """取消运行：只在**轮边界**生效（不中断在途 HTTP，避免半批数据）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    run = _get_run(db, workspace_id, run_id)
    if run.status != "running":
        raise HTTPException(status_code=400, detail=f"只有运行中的任务可取消（当前 {run.status}）")
    run.detail = {**dict(run.detail or {}), "cancel_requested": True}
    run.progress_message = "已请求取消：本轮结束后停止"
    db.add(run)
    db.commit()
    db.refresh(run)
    return _serialize_run(run)


@router.post("/strategies/{strategy_id}/enable", response_model=StrategyOut)
def enable_strategy(
    workspace_id: int,
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> StrategyOut:
    """启用策略：启用前跑一次规则校验（规则不合法直接 400）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    strategy = _get_strategy(db, workspace_id, strategy_id)
    _validate(
        db,
        workspace_id,
        scope=dict(strategy.scope or {}),
        filter_rule=dict(strategy.filter_rule or {}),
        targets=list(strategy.targets or []),
        iteration=dict(strategy.iteration or {}),
        schedule=dict(strategy.schedule or {}),
    )
    strategy.enabled = True
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return _serialize_strategy(strategy)


@router.post("/strategies/{strategy_id}/disable", response_model=StrategyOut)
def disable_strategy(
    workspace_id: int,
    strategy_id: int,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> StrategyOut:
    """停用策略（调度不再触发；在途运行不受影响）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)
    strategy = _get_strategy(db, workspace_id, strategy_id)
    strategy.enabled = False
    db.add(strategy)
    db.commit()
    db.refresh(strategy)
    return _serialize_strategy(strategy)


@router.post("/rules/validate", response_model=RuleValidateResponse)
def validate_rules(
    workspace_id: int,
    payload: RuleValidateRequest,
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> RuleValidateResponse:
    """规则片段校验（不落库）；不合法返回 ``ok=false`` + 逐条错误."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)
    errors: list[str] = []
    try:
        _validate(
            db,
            workspace_id,
            scope=payload.scope,
            filter_rule=payload.filter_rule,
            targets=payload.targets,
            iteration=payload.iteration,
        )
    except HTTPException as exc:
        errors.append(str(exc.detail))
    return RuleValidateResponse(ok=not errors, errors=errors)


__all__ = ["router"]
