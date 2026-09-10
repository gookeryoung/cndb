"""ApiToken 路由：签发 / 列表 / 撤销."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import ApiToken, User
from cndb.plugins.accounts.schemas.token import (
    ApiTokenCreateRequest,
    ApiTokenResponse,
    ApiTokenWithPlainResponse,
)

router = APIRouter(prefix="/tokens", tags=["tokens"])


@router.post("", response_model=ApiTokenWithPlainResponse, status_code=status.HTTP_201_CREATED)
def create_token(
    payload: ApiTokenCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiTokenWithPlainResponse:
    """签发新的 ApiToken.

    返回一次性明文，请调用方妥善保存——数据库中只存 SHA-256 摘要，无法回溯。
    """
    if current_user is None:
        raise HTTPException(status_code=401, detail="未认证")  # pragma: no cover - Depends 已保证非 None
    at_obj, token_plain = ApiToken.issue(db, current_user, payload.name)
    response = ApiTokenResponse.model_validate(at_obj)
    return ApiTokenWithPlainResponse(
        id=response.id,
        name=response.name,
        prefix=response.prefix,
        created_at=response.created_at,
        last_used_at=response.last_used_at,
        token=token_plain,
    )


@router.get("", response_model=list[ApiTokenResponse])
def list_tokens(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ApiToken]:
    """列出当前用户的所有 ApiToken（不含明文）."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未认证")  # pragma: no cover - Depends 已保证非 None
    return db.query(ApiToken).filter(ApiToken.user_id == current_user.id).order_by(ApiToken.created_at.desc()).all()


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_token(
    token_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """撤销指定 ApiToken."""
    if current_user is None:
        raise HTTPException(status_code=401, detail="未认证")  # pragma: no cover - Depends 已保证非 None
    at = db.query(ApiToken).filter(ApiToken.id == token_id, ApiToken.user_id == current_user.id).first()
    if at is None:
        raise HTTPException(status_code=404, detail="令牌不存在")
    db.delete(at)
    db.commit()
