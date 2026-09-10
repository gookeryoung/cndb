"""ApiToken 相关 Pydantic schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ApiTokenCreateRequest(BaseModel):
    """签发 ApiToken 请求体."""

    model_config = ConfigDict(strict=True)

    name: str = Field(min_length=1, max_length=150, description="令牌名称")


class ApiTokenResponse(BaseModel):
    """ApiToken 列表/详情响应（不含明文）."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None


class ApiTokenWithPlainResponse(ApiTokenResponse):
    """签发 ApiToken 响应（包含一次性明文）."""

    token: str = Field(description="令牌明文，仅此一次返回，请妥善保存")
