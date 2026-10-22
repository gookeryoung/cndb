"""datasource 同步任务路由：CRUD + 立即运行 + 抓取预览 + 运行历史.

权限：读操作（列表 / 详情 / 预览 / 运行历史）要求工作区 VIEWER，
写操作（新建 / 修改 / 删除 / 立即运行）要求 EDITOR。

手动运行同样走 DB 租约，避免和内置调度器 / cron 撞车（ADR 0006 I4）；
租约被占用返回 409，而不是排队等。
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.crypto import decrypt_secrets
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import DatasourceSession, DatasourceSyncJob, DatasourceSyncRun, RunTrigger
from cndb.plugins.datasource.providers.base import ProviderError
from cndb.plugins.datasource.providers.llm_prompt import test_llm_connection, validate_llm_request_spec
from cndb.plugins.datasource.providers.registry import get_provider
from cndb.plugins.datasource.schemas import (
    ConnectionTestRequest,
    ConnectionTestResponse,
    PreviewRequest,
    PreviewResponse,
    RunResponse,
    SyncJobCreate,
    SyncJobListResponse,
    SyncJobOut,
    SyncJobUpdate,
    SyncRunListResponse,
    SyncRunOut,
)
from cndb.plugins.datasource.services.connection import (
    load_llm_connection,
    resolve_request_spec_defaults,
)
from cndb.plugins.datasource.services.cursor import CursorConfig
from cndb.plugins.datasource.services.runner import (
    execute_job,
    preview_job,
    request_spec_from_payload,
    validate_request_spec,
)
from cndb.plugins.datasource.services.schedule import ScheduleConfig
from cndb.plugins.datasource.services.scheduler import LEASE_TTL_SECONDS, acquire_lease, release_lease
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/datasource", tags=["datasource"])


# ── 校验 ─────────────────────────────────────────


def _job_or_404(db: Session, workspace_id: int, job_id: int) -> DatasourceSyncJob:
    job = db.get(DatasourceSyncJob, job_id)
    if job is None or job.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="同步任务不存在")
    return job


def _validate_table(db: Session, workspace_id: int, table_id: int | None) -> DataTable | None:
    if table_id is None:
        return None
    table = db.get(DataTable, table_id)
    if table is None or table.workspace_id != workspace_id:
        raise HTTPException(status_code=400, detail=f"目标表不存在: {table_id}")
    return table


def _session_api_key(session: DatasourceSession | None) -> str:
    """读取会话里的 api_key（解密失败按未配置处理，交给上层给出配置提示）."""
    if session is None:
        return ""
    try:
        return str(decrypt_secrets(session.secrets).get("api_key") or "").strip()
    except ValueError:
        return ""


def _validate_job_config(
    db: Session,
    workspace_id: int,
    *,
    provider: str,
    request_spec: dict[str, Any],
    table_id: int | None,
    cursor: dict[str, Any],
    schedule: dict[str, Any],
    match_keys: list[str],
    entrant_param: str | None = None,
    session_id: int | None = None,
) -> dict[str, Any]:
    """创建 / 更新时逐项校验，返回补齐连接默认值后的 ``request_spec``.

    ADR 0019：``llm_prompt`` 任务的地址 / 模型从工作区「大模型连接」继承，
    因此先补默认值再走既有 RequestSpec / LLM 校验；API Key 允许来自会话或工作区连接。
    """
    session: DatasourceSession | None = None
    if session_id is not None:
        session = db.get(DatasourceSession, session_id)
        if session is None or session.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail=f"凭证会话不存在: {session_id}")

    filled = dict(request_spec or {})
    connection = None
    if provider == "llm_prompt":
        connection = load_llm_connection(db, workspace_id)
        filled = resolve_request_spec_defaults(filled, connection)

    try:
        get_provider(provider)
        validate_request_spec(filled)
        CursorConfig.from_dict(cursor)
        ScheduleConfig.from_dict(schedule)
        if provider == "llm_prompt":
            validate_llm_request_spec(
                filled,
                entrant_param=entrant_param,
                schedule=schedule,
                match_keys=match_keys,
            )
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if provider == "llm_prompt" and not _session_api_key(session) and not (connection and connection.has_api_key):
        raise HTTPException(
            status_code=400,
            detail="请先在「大模型连接」配置 API Key",
        )

    table = _validate_table(db, workspace_id, table_id)
    if table is not None and match_keys:
        field_names = {row[0] for row in db.execute(select(DataField.name).where(DataField.table_id == table.id))}
        missing = [key for key in match_keys if key not in field_names]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"幂等键必须是目标表字段，未找到: {', '.join(missing)}",
            )
    return filled


# ── CRUD ─────────────────────────────────────────


@router.get("/sync-jobs", response_model=SyncJobListResponse)
def list_sync_jobs(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SyncJobListResponse:
    """列出工作区内的同步任务（按 id 升序）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    jobs = list(
        db.execute(
            select(DatasourceSyncJob)
            .where(DatasourceSyncJob.workspace_id == workspace_id)
            .order_by(DatasourceSyncJob.id)
        ).scalars()
    )
    return SyncJobListResponse(total=len(jobs), jobs=[SyncJobOut.from_model(job) for job in jobs])


@router.post("/sync-jobs", response_model=SyncJobOut, status_code=201)
def create_sync_job(
    workspace_id: int,
    payload: SyncJobCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SyncJobOut:
    """新建同步任务（可带 ``run_immediately`` 立刻跑一次）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    request_spec = _validate_job_config(
        db,
        workspace_id,
        provider=payload.provider,
        request_spec=payload.request_spec,
        table_id=payload.table_id,
        cursor=payload.cursor,
        schedule=payload.schedule,
        match_keys=payload.match_keys,
        entrant_param=payload.entrant_param,
        session_id=payload.session_id,
    )
    job = DatasourceSyncJob(
        workspace_id=workspace_id,
        created_by=current_user.id,
        name=payload.name,
        provider=payload.provider,
        table_id=payload.table_id,
        request_spec=request_spec,
        parser=payload.parser,
        entrant_param=payload.entrant_param,
        entrant_keys=payload.entrant_keys,
        match_keys=payload.match_keys,
        field_mapping=payload.field_mapping,
        cursor=payload.cursor,
        schedule=payload.schedule,
        enabled=payload.enabled,
        session_id=payload.session_id,
        rate_limit_ms=payload.rate_limit_ms,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    if payload.run_immediately:
        execute_job(db, job, trigger=RunTrigger.MANUAL, user=current_user)
        db.refresh(job)
    return SyncJobOut.from_model(job)


@router.get("/sync-jobs/{job_id}", response_model=SyncJobOut)
def get_sync_job(
    workspace_id: int,
    job_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SyncJobOut:
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return SyncJobOut.from_model(_job_or_404(db, workspace_id, job_id))


@router.put("/sync-jobs/{job_id}", response_model=SyncJobOut)
def update_sync_job(
    workspace_id: int,
    job_id: int,
    payload: SyncJobUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SyncJobOut:
    """局部更新（启停、改调度 / 映射 / 幂等键）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    job = _job_or_404(db, workspace_id, job_id)

    provider = payload.provider if payload.provider is not None else job.provider
    request_spec = payload.request_spec if payload.request_spec is not None else (job.request_spec or {})
    cursor = payload.cursor if payload.cursor is not None else (job.cursor or {})
    schedule = payload.schedule if payload.schedule is not None else (job.schedule or {})
    match_keys = payload.match_keys if payload.match_keys is not None else (job.match_keys or [])
    entrant_param = payload.entrant_param if payload.entrant_param is not None else job.entrant_param
    table_id = payload.table_id if payload.table_id is not None else job.table_id
    session_id = payload.session_id if payload.session_id is not None else job.session_id
    request_spec = _validate_job_config(
        db,
        workspace_id,
        provider=provider,
        request_spec=request_spec,
        table_id=table_id,
        cursor=cursor,
        schedule=schedule,
        match_keys=match_keys,
        entrant_param=entrant_param,
        session_id=session_id,
    )

    for field_name in (
        "name",
        "provider",
        "table_id",
        "parser",
        "entrant_param",
        "entrant_keys",
        "match_keys",
        "field_mapping",
        "cursor",
        "schedule",
        "enabled",
        "session_id",
        "rate_limit_ms",
    ):
        value = getattr(payload, field_name)
        if value is not None:
            setattr(job, field_name, value)
    # 连接默认值补齐后的 request_spec 一并持久化（llm_prompt 任务只保留提示词也能运行）
    job.request_spec = request_spec
    db.add(job)
    db.commit()
    db.refresh(job)
    return SyncJobOut.from_model(job)


@router.delete("/sync-jobs/{job_id}", status_code=204)
def delete_sync_job(
    workspace_id: int,
    job_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """删除任务及其运行历史（目标表数据保留）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    job = _job_or_404(db, workspace_id, job_id)
    db.query(DatasourceSyncRun).filter(DatasourceSyncRun.job_id == job.id).delete()
    db.delete(job)
    db.commit()


# ── 运行 / 预览 / 历史 ───────────────────────────


@router.post("/test-connection", response_model=ConnectionTestResponse)
def test_connection(
    workspace_id: int,
    payload: ConnectionTestRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectionTestResponse:
    """大模型 API 连通测试：用未保存的配置发一次最小请求，不落库、不写运行记录.

    ADR 0019：地址 / 模型 / Key 缺省时回退工作区「大模型连接」，因此不传凭证会话也能测。
    """
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)

    session: DatasourceSession | None = None
    if payload.session_id is not None:
        session = db.get(DatasourceSession, payload.session_id)
        if session is None or session.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail=f"凭证会话不存在: {payload.session_id}")

    connection = load_llm_connection(db, workspace_id)
    filled = resolve_request_spec_defaults(payload.request_spec, connection)
    try:
        validate_request_spec(filled)
        spec = request_spec_from_payload(filled)
    except (ProviderError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        secrets: dict[str, str] = decrypt_secrets(session.secrets) if session is not None else {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # 会话 Key 优先，其次工作区连接 Key（都不是则 test_llm_connection 返回明确提示）
    api_key = str(secrets.get("api_key") or "").strip() or connection.api_key

    result = test_llm_connection(
        spec,
        api_key=api_key,
        session_headers=session.headers if session is not None else None,
    )
    return ConnectionTestResponse(
        ok=result.ok,
        latency_ms=result.latency_ms,
        model=result.model,
        message=result.message,
    )


@router.post("/sync-jobs/{job_id}/run", response_model=RunResponse)
def run_sync_job(
    workspace_id: int,
    job_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> RunResponse:
    """立即运行一次（同步执行；单飞由 DB 租约保证，抢占失败返回 409）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    job = _job_or_404(db, workspace_id, job_id)
    owner = f"api:{current_user.id}:{job_id}"
    now = dt.datetime.now(dt.UTC)
    if not acquire_lease(db, job.id, owner, now=now, ttl_seconds=LEASE_TTL_SECONDS):
        raise HTTPException(status_code=409, detail="该任务正在运行中（租约被占用），请稍后再试")
    try:
        execution = execute_job(db, job, trigger=RunTrigger.MANUAL, user=current_user, now=now)
    finally:
        release_lease(db, job.id, owner)
    db.refresh(job)
    return RunResponse(job=SyncJobOut.from_model(job), run=SyncRunOut.from_model(execution.run))


@router.post("/sync-jobs/{job_id}/preview", response_model=PreviewResponse)
def preview_sync_job(
    workspace_id: int,
    job_id: int,
    payload: PreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PreviewResponse:
    """抓一次预览：不落库、不推进游标、不写运行记录."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    job = _job_or_404(db, workspace_id, job_id)
    session = db.get(DatasourceSession, job.session_id) if job.session_id else None
    result = preview_job(job, limit=payload.limit, session=session, db=db)
    return PreviewResponse(
        status=result.status,
        total=result.total,
        columns=result.columns,
        plans=result.plans,
        succeeded=result.succeeded,
        cursor_from=result.cursor_from,
        cursor_to=result.cursor_to,
        rows=result.rows,
        failures=result.failures,
        normalize_failures=result.normalize_failures,
        suggested_match_keys=result.suggested_match_keys,
    )


@router.get("/sync-jobs/{job_id}/runs", response_model=SyncRunListResponse)
def list_sync_runs(
    workspace_id: int,
    job_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SyncRunListResponse:
    """运行历史（按开始时间倒序）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    job = _job_or_404(db, workspace_id, job_id)
    total = db.execute(
        select(func.count()).select_from(DatasourceSyncRun).where(DatasourceSyncRun.job_id == job.id)
    ).scalar_one()
    runs = list(
        db.execute(
            select(DatasourceSyncRun)
            .where(DatasourceSyncRun.job_id == job.id)
            .order_by(DatasourceSyncRun.started_at.desc())
            .limit(limit)
            .offset(offset)
        ).scalars()
    )
    return SyncRunListResponse(total=int(total), runs=[SyncRunOut.from_model(run) for run in runs])


__all__ = ["router"]
