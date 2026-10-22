"""数据分析 AI 动作路由（ADR 0020 P3）.

- ``POST /{wid}/analytics/ai/suggest-template``：自然语言 → 模板配置建议（过
  ``normalize_config`` 校验，**不保存**）；
- ``POST /{wid}/analytics/ai/explain``：对汇总结果生成文字解读（只读）。
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, CndbError
from cndb.plugins.accounts.models import User
from cndb.plugins.analytics.schemas import TemplateConfig
from cndb.plugins.analytics.services import ai as ai_service
from cndb.plugins.analytics.services import recommend, templates
from cndb.plugins.llm.services import gateway as llm_gateway
from cndb.plugins.llm.services.errors import LlmError
from cndb.plugins.llm.services.gateway import LlmContext
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_workspace_permission,
    get_table_or_404,
)
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/analytics/ai", tags=["analytics"])


class SuggestTemplateRequest(BaseModel):
    """自然语言生成分析模板建议."""

    table_id: int = Field(description="分析目标表 id")
    question: str = Field(min_length=1, max_length=500, description="自然语言问题")


class ExplainRequest(BaseModel):
    """分析结论解读（只传汇总结果，不传整表）."""

    summary_rows: list[dict[str, Any]] = Field(
        min_length=1, max_length=ai_service.MAX_EXPLAIN_ROWS, description="分组汇总 / 统计结果行"
    )
    chart_type: str | None = Field(default=None, max_length=32)
    template_id: int | None = Field(default=None, description="可选：仅用于校验模板归属")


@router.post("/suggest-template")
def suggest_template(
    workspace_id: int,
    payload: SuggestTemplateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """根据问题与字段画像生成模板配置建议（只返回建议，不保存）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    table = get_table_or_404(payload.table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    recommendations = recommend.build_recommendations(db, table, current_user)
    user_content = ai_service.build_template_content(
        payload.question,
        table.name,
        recommendations.get("fields") or [],
    )

    try:
        result = llm_gateway.invoke(
            db,
            current_user,
            ai_service.SUGGEST_TEMPLATE,
            user_content=user_content,
            context=LlmContext(workspace_id=workspace_id, target_type="table", target_id=table.id),
        )
    except LlmError as exc:
        raise CndbError(str(exc), status_code=exc.status_code, code=exc.code) from exc

    # 机器校验：配置必须能构造 TemplateConfig 且通过公式 / 字段 / 聚合校验
    try:
        config_model = TemplateConfig.model_validate(result.parsed.config)
        normalized = templates.normalize_config(
            config_model,
            templates.table_field_names(db, workspace_id, table.id),
        )
    except Exception as exc:  # pydantic ValidationError / normalize_config 的 HTTPException
        raise CndbError(
            f"AI 生成的配置未通过校验：{exc}",
            status_code=422,
            code="llm_output_invalid",
        ) from exc

    return {
        "action": ai_service.SUGGEST_TEMPLATE.name,
        "run_id": result.run_id,
        "model": result.model,
        "usage": result.usage,
        "result": {
            "name": result.parsed.name,
            "description": result.parsed.description,
            "config": normalized,
            "warnings": result.parsed.warnings,
        },
    }


@router.post("/explain")
def explain(
    workspace_id: int,
    payload: ExplainRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """对统计 / 分组汇总结果生成文字解读（不写模板、不改数据）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    template_name: str | None = None
    if payload.template_id is not None:
        template = templates.get_template(db, workspace_id, payload.template_id)
        template_name = template.name
    if not payload.summary_rows:
        raise BadRequestError("没有可解读的汇总结果")
    user_content = ai_service.build_explain_content(
        payload.summary_rows,
        chart_type=payload.chart_type,
        template_name=template_name,
    )

    try:
        result = llm_gateway.invoke(
            db,
            current_user,
            ai_service.EXPLAIN,
            user_content=user_content,
            context=LlmContext(workspace_id=workspace_id, target_type="table", target_id=payload.template_id),
        )
    except LlmError as exc:
        raise CndbError(str(exc), status_code=exc.status_code, code=exc.code) from exc

    return {
        "action": ai_service.EXPLAIN.name,
        "run_id": result.run_id,
        "model": result.model,
        "usage": result.usage,
        "result": {
            "insight": result.parsed.insight,
            "caveats": result.parsed.caveats,
        },
    }


__all__ = ["ExplainRequest", "SuggestTemplateRequest", "router"]
