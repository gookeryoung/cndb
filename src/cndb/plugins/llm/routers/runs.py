"""调用记录：``GET /api/v1/llm/runs``（ADR 0020 P0）.

只返回**当前用户**的 ``llm_run`` 记录；不含提示词 / 输出全文，只含元数据与错误摘要。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.models import LlmRun

router = APIRouter(prefix="/runs", tags=["llm"])


def _serialize(run: LlmRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "action": run.action,
        "workspace_id": run.workspace_id,
        "model": run.model,
        "status": run.status,
        "latency_ms": run.latency_ms,
        "prompt_tokens": run.prompt_tokens,
        "completion_tokens": run.completion_tokens,
        "total_tokens": run.total_tokens,
        "error": run.error,
        "created_at": run.created_at,
    }


@router.get("")
def list_runs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, pattern="^(success|failed)$"),
) -> dict[str, Any]:
    """当前用户的调用记录（新记录在前）."""
    conditions = [LlmRun.user_id == current_user.id]
    if action:
        conditions.append(LlmRun.action == action)
    if status:
        conditions.append(LlmRun.status == status)
    total = int(db.execute(select(func.count()).select_from(LlmRun).where(*conditions)).scalar_one())
    rows = (
        db.execute(select(LlmRun).where(*conditions).order_by(LlmRun.id.desc()).limit(limit).offset(offset))
        .scalars()
        .all()
    )
    return {"items": [_serialize(run) for run in rows], "total": total}


__all__ = ["router"]
