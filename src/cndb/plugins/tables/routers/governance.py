"""数据治理路由：重复检测 / 合并 / 清洗（全部异步任务化）.

端点：
- POST /{workspace_id}/tables/{table_id}/governance/detect          — 创建重复检测任务
- POST /{workspace_id}/tables/{table_id}/governance/merge           — 创建合并任务
- POST /{workspace_id}/tables/{table_id}/governance/clean           — 创建清洗任务（preview=True 只预览）
- GET  /{workspace_id}/tables/{table_id}/governance/tasks/{task_id} — 查询任务状态/进度
- GET  /{workspace_id}/tables/{table_id}/governance/tasks/{task_id}/report — 获取任务报告

所有端点要求 TableAction.MANAGE_DATA 权限（默认 ADMIN）。
"""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import GovernanceTask
from cndb.plugins.tables.schemas import (
    CleanRequest,
    DetectRequest,
    GovernanceTaskOut,
    MergeRequest,
)
from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404
from cndb.plugins.tables.services.governance.tasks import (
    GovernanceTaskError,
    create_governance_task,
    run_governance_task_in_background,
)

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/governance", tags=["governance"])


def _create_and_dispatch(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    *,
    kind: str,
    config: dict[str, Any],
) -> GovernanceTaskOut:
    """创建治理任务并提交后台执行（三类任务的公共流程）."""
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.MANAGE_DATA)

    try:
        task = create_governance_task(
            db,
            table=table,
            user_id=current_user.id if current_user else None,
            kind=kind,
            config=config,
        )
    except GovernanceTaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 后台线程执行：用请求 session 的 bind 保证连接到同一个数据库
    engine = db.get_bind()
    bg_session_factory = sessionmaker(bind=engine)
    run_governance_task_in_background(bg_session_factory, task.id)

    return GovernanceTaskOut.model_validate(task)


@router.post("/detect", response_model=GovernanceTaskOut)
def create_detect_task(
    workspace_id: int,
    table_id: int,
    payload: DetectRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceTaskOut:
    """创建重复检测任务（精确匹配）."""
    return _create_and_dispatch(
        workspace_id,
        table_id,
        current_user,
        db,
        kind="detect",
        config=payload.model_dump(),
    )


@router.post("/merge", response_model=GovernanceTaskOut)
def create_merge_task(
    workspace_id: int,
    table_id: int,
    payload: MergeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceTaskOut:
    """创建合并任务（人工确认后的分组 + 保留策略）."""
    return _create_and_dispatch(
        workspace_id,
        table_id,
        current_user,
        db,
        kind="merge",
        config=payload.model_dump(),
    )


@router.post("/clean", response_model=GovernanceTaskOut)
def create_clean_task(
    workspace_id: int,
    table_id: int,
    payload: CleanRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceTaskOut:
    """创建清洗任务（preview=True 只生成预览报告，不写库）."""
    return _create_and_dispatch(
        workspace_id,
        table_id,
        current_user,
        db,
        kind="clean",
        config=payload.model_dump(),
    )


def _get_task_or_404(
    table_id: int,
    workspace_id: int,
    task_id: int,
    current_user: User | None,
    db: Session,
) -> GovernanceTask:
    """校验表权限并取任务；任务不存在或不属于此表一律 404."""
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.MANAGE_DATA)
    task = db.get(GovernanceTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.table_id != table.id:
        raise HTTPException(status_code=404, detail="任务不属于此表")
    return task


@router.get("/tasks/{task_id}", response_model=GovernanceTaskOut)
def get_governance_task(
    workspace_id: int,
    table_id: int,
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> GovernanceTaskOut:
    """查询治理任务状态与进度."""
    task = _get_task_or_404(table_id, workspace_id, task_id, current_user, db)
    return GovernanceTaskOut.model_validate(task)


@router.get("/tasks/{task_id}/report")
def get_governance_task_report(
    workspace_id: int,
    table_id: int,
    task_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """获取治理任务报告（JSON 解析后返回）."""
    task = _get_task_or_404(table_id, workspace_id, task_id, current_user, db)
    report: Any = None
    if task.report:
        try:
            report = json.loads(task.report)
        except ValueError:
            report = task.report
    return {"task_id": task.id, "status": task.status, "report": report}


__all__ = ["router"]
