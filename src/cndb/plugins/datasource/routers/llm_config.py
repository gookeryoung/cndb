"""工作区级「大模型连接」路由（ADR 0019）.

- ``GET  /{wid}/datasource/llm-config``：读取连接（VIEWER）；**不返回 api_key 明文**，
  只给 ``has_api_key``；未配置时返回内置默认地址 / 模型与内置默认系统提示词。
- ``PUT  /{wid}/datasource/llm-config``：创建或更新（EDITOR）；``api_key`` 非空才覆盖，
  ``clear_api_key=true`` 可显式清除；API Key 用 :func:`cndb.core.crypto.encrypt_secret` 加密入库。

任务侧只需填写用户提示词，地址 / 模型 / Key / 系统提示词默认值都从这里继承。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.crypto import encrypt_secret
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.datasource.models import DatasourceLlmConfig
from cndb.plugins.datasource.providers.llm_prompt import DEFAULT_SYSTEM_PROMPT
from cndb.plugins.datasource.schemas import LlmConfigOut, LlmConfigUpdate
from cndb.plugins.datasource.services.connection import DEFAULT_BASE_URL, DEFAULT_MODEL
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/datasource", tags=["datasource"])


def _config_for(db: Session, workspace_id: int) -> DatasourceLlmConfig | None:
    return db.execute(
        select(DatasourceLlmConfig).where(DatasourceLlmConfig.workspace_id == workspace_id)
    ).scalar_one_or_none()


def _to_out(config: DatasourceLlmConfig | None) -> LlmConfigOut:
    """连接 → 响应；未配置时回内置默认值（前端可直接展示 / 编辑）."""
    if config is None:
        return LlmConfigOut(
            configured=False,
            base_url=DEFAULT_BASE_URL,
            model=DEFAULT_MODEL,
            has_api_key=False,
            system_prompt="",
            default_system_prompt=DEFAULT_SYSTEM_PROMPT,
        )
    return LlmConfigOut(
        configured=True,
        base_url=config.base_url,
        model=config.model,
        has_api_key=bool((config.api_key or "").strip()),
        system_prompt=config.system_prompt or "",
        default_system_prompt=DEFAULT_SYSTEM_PROMPT,
    )


@router.get("/llm-config", response_model=LlmConfigOut)
def get_llm_config(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LlmConfigOut:
    """读取工作区大模型连接（API Key 只回「是否已配置」）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return _to_out(_config_for(db, workspace_id))


@router.put("/llm-config", response_model=LlmConfigOut)
def update_llm_config(
    workspace_id: int,
    payload: LlmConfigUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LlmConfigOut:
    """创建或更新工作区大模型连接（地址 / 模型 / Key / 系统提示词覆盖）."""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)

    base_url = payload.base_url.strip() if payload.base_url is not None else None
    if base_url is not None:
        if not base_url:
            raise HTTPException(status_code=400, detail="大模型地址不能为空")
        if not base_url.startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="大模型地址必须是 http/https URL")
    model = payload.model.strip() if payload.model is not None else None
    if model is not None and not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")

    config = _config_for(db, workspace_id)
    if config is None:
        config = DatasourceLlmConfig(
            workspace_id=workspace_id,
            created_by=current_user.id,
            base_url=base_url or DEFAULT_BASE_URL,
            model=model or DEFAULT_MODEL,
            api_key="",
            system_prompt="",
        )
    else:
        if base_url is not None:
            config.base_url = base_url
        if model is not None:
            config.model = model
    api_key = (payload.api_key or "").strip()
    if api_key:
        config.api_key = encrypt_secret(api_key)
    elif payload.clear_api_key:
        config.api_key = ""
    if payload.system_prompt is not None:
        # 空串 = 不覆盖，运行期回退内置默认系统提示词
        config.system_prompt = payload.system_prompt.strip()

    db.add(config)
    db.commit()
    db.refresh(config)
    return _to_out(config)


__all__ = ["router"]
