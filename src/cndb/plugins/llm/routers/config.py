"""个人「大模型连接」路由（ADR 0020 P0；原 ``/api/v1/accounts/llm-config`` 迁入）.

- ``GET  /config``：读取当前用户连接；**不返回 api_key 明文**，只给 ``has_api_key``；
  未配置时返回内置默认地址 / 模型与内置默认系统提示词。
- ``PUT  /config``：创建或更新当前用户连接；``api_key`` 非空才覆盖，
  ``clear_api_key=true`` 可显式清除；API Key 用 :func:`cndb.core.crypto.encrypt_secret` 加密入库。
- ``POST /config/test``：用当前用户连接 + 请求体里可选的未保存配置发一次最小模型请求，
  **不落库**；用于「个人设置 → 大模型」填完 Key 先测后存。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.crypto import encrypt_secret
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.llm.models import LlmUserConfig
from cndb.plugins.llm.services import client
from cndb.plugins.llm.services.connection import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    LlmConnection,
    find_user_config,
    load_connection,
)
from cndb.plugins.llm.services.prompts import DEFAULT_SYSTEM_PROMPT

router = APIRouter(prefix="/config", tags=["llm"])


# ── Schema ───────────────────────────────────────


class LlmConfigOut(BaseModel):
    """个人大模型连接（**不返回 api_key 明文**，只回 ``has_api_key``）."""

    configured: bool = False
    base_url: str
    model: str
    has_api_key: bool = False
    system_prompt: str = ""
    default_system_prompt: str = ""


class LlmConfigUpdate(BaseModel):
    """更新个人大模型连接（局部更新；``api_key`` 非空才覆盖，``clear_api_key`` 可清除）."""

    base_url: str | None = None
    model: str | None = None
    api_key: str | None = Field(default=None, description="非空才更新；留空保持原 Key 不变")
    clear_api_key: bool = Field(default=False, description="显式清除已保存的 API Key")
    system_prompt: str | None = Field(default=None, description="留空 / 空串表示使用内置默认系统提示词")


class ConnectionTestRequest(BaseModel):
    """个人大模型连通测试：未提供的字段回退当前用户连接，不落库."""

    base_url: str | None = Field(default=None, description="未保存的地址；留空回退个人连接 / 内置默认")
    model: str | None = Field(default=None, description="未保存的模型；留空回退个人连接 / 内置默认")
    api_key: str | None = Field(default=None, description="未保存的 API Key，仅用于本次测试")
    system_prompt: str | None = Field(default=None, description="未保存的系统提示词，仅用于本次测试")


class ConnectionTestResponse(BaseModel):
    ok: bool
    latency_ms: int = 0
    model: str = ""
    message: str = ""


# ── 辅助 ─────────────────────────────────────────


def _to_out(config: LlmUserConfig | None) -> LlmConfigOut:
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


def _validated_base_url(value: str | None) -> str | None:
    """校验并归一地址：必须是 http(s)，空串视为非法."""
    if value is None:
        return None
    base_url = value.strip()
    if not base_url:
        raise HTTPException(status_code=400, detail="大模型地址不能为空")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="大模型地址必须是 http/https URL")
    return base_url


def _validated_model(value: str | None) -> str | None:
    """校验模型名：非空（去空白后）."""
    if value is None:
        return None
    model = value.strip()
    if not model:
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    return model


# ── 路由 ─────────────────────────────────────────


@router.get("", response_model=LlmConfigOut)
def get_llm_config(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LlmConfigOut:
    """读取当前用户的个人大模型连接（API Key 只回「是否已配置」）."""
    return _to_out(find_user_config(db, current_user.id))


@router.put("", response_model=LlmConfigOut)
def update_llm_config(
    payload: LlmConfigUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LlmConfigOut:
    """创建或更新当前用户的个人大模型连接（地址 / 模型 / Key / 系统提示词覆盖）."""
    base_url = _validated_base_url(payload.base_url)
    model = _validated_model(payload.model)

    config = find_user_config(db, current_user.id)
    if config is None:
        config = LlmUserConfig(
            user_id=current_user.id,
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


@router.post("/test", response_model=ConnectionTestResponse)
def test_connection(
    payload: ConnectionTestRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ConnectionTestResponse:
    """用当前用户连接 + 请求体未保存的覆盖项测一次模型连通性（不落库、不写运行记录）.

    Key 优先级：请求体 ``api_key`` > 当前用户已保存 Key；都没有时不发请求、直接给配置提示。
    """
    base_url = _validated_base_url(payload.base_url)
    model = _validated_model(payload.model)
    saved = load_connection(db, current_user.id)

    effective = LlmConnection(
        base_url=base_url or saved.base_url,
        model=model or saved.model,
        api_key=(payload.api_key or "").strip() or saved.api_key,
        system_prompt=payload.system_prompt if payload.system_prompt is not None else saved.system_prompt,
        has_api_key=saved.has_api_key,
    )
    result = client.test_connection(effective)
    return ConnectionTestResponse(
        ok=result.ok,
        latency_ms=result.latency_ms,
        model=result.model,
        message=result.message,
    )


__all__ = [
    "ConnectionTestRequest",
    "ConnectionTestResponse",
    "LlmConfigOut",
    "LlmConfigUpdate",
    "router",
]
