"""用户偏好路由 —— 持久化每张表的激活视图等 per-user 状态."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, DataView

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/preferences", tags=["preferences"])


# ── Pydantic Schema ──


class ActiveViewUpsert(BaseModel):
    """设置某表激活视图的请求体."""

    model_config = ConfigDict(strict=True)

    active_view_id: int | None = Field(default=None, description="激活视图 ID，传 null 清除偏好")


class PreferencesResponse(BaseModel):
    """用户偏好完整响应."""

    model_config = ConfigDict(from_attributes=True)

    active_views: dict[str, int] = Field(default_factory=dict, description="每张表的激活视图映射: table_id -> view_id")


class ActiveViewResponse(BaseModel):
    """单表激活视图查询响应."""

    model_config = ConfigDict(from_attributes=True)

    table_id: int
    active_view_id: int | None


# ── 辅助函数 ──


def _ensure_authenticated(current_user: object | None) -> User:
    """确保用户已认证，否则抛 401."""
    if current_user is None or not isinstance(current_user, User):
        raise HTTPException(status_code=401, detail="未认证")
    return current_user


def _ensure_preferences(user: User) -> None:
    """确保 user.preferences 字段包含基础结构，缺失时自动补齐."""
    if not isinstance(user.preferences, dict):
        user.preferences = {"active_views": dict[str, int]()}
        flag_modified(user, "preferences")
    if "active_views" not in user.preferences:
        user.preferences["active_views"] = dict[str, int]()
        flag_modified(user, "preferences")


# ── 路由 ──


@router.get("", response_model=PreferencesResponse)
def get_preferences(
    current_user: Annotated[object | None, Depends(get_current_user)],
) -> dict[str, Any]:
    """获取当前用户所有偏好设置（含每张表的激活视图映射）."""
    user = _ensure_authenticated(current_user)
    _ensure_preferences(user)
    active_views = {str(k): int(v) for k, v in (user.preferences.get("active_views") or {}).items()}
    return {"active_views": active_views}


@router.get("/tables/{table_id}/active-view", response_model=ActiveViewResponse)
def get_table_active_view(
    table_id: int,
    current_user: Annotated[object | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """查询指定表当前用户的激活视图偏好."""
    user = _ensure_authenticated(current_user)
    # 表必须存在
    table = db.query(DataTable).filter(DataTable.id == table_id).first()
    if table is None:
        raise HTTPException(status_code=404, detail="表不存在")

    _ensure_preferences(user)
    active_view_id: int | None = None
    raw: dict[str, Any] = user.preferences.get("active_views") or {}
    # 统一用 str key 查
    raw_val = raw.get(str(table_id))
    if raw_val is not None:
        # 验证视图仍存在
        view = db.query(DataView).filter(DataView.id == int(raw_val), DataView.table_id == table_id).first()
        if view is not None:
            active_view_id = int(raw_val)
        else:
            # 视图已被删，清理孤立引用
            raw.pop(str(table_id), None)
            flag_modified(user, "preferences")
            db.commit()

    return {"table_id": table_id, "active_view_id": active_view_id}


@router.put("/tables/{table_id}/active-view", response_model=ActiveViewResponse)
def set_table_active_view(
    table_id: int,
    payload: ActiveViewUpsert,
    current_user: Annotated[object | None, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """设置或清除指定表的激活视图偏好.

    active_view_id 传 null 即清除偏好，让前端回退到默认逻辑.
    """
    user = _ensure_authenticated(current_user)
    # 表必须存在
    table = db.query(DataTable).filter(DataTable.id == table_id).first()
    if table is None:
        raise HTTPException(status_code=404, detail="表不存在")

    # 如果指定了 active_view_id，验证它确实属于这张表
    if payload.active_view_id is not None:
        view = (
            db.query(DataView)
            .filter(
                DataView.id == payload.active_view_id,
                DataView.table_id == table_id,
            )
            .first()
        )
        if view is None:
            raise HTTPException(status_code=400, detail="视图不存在或不属于此表")

    _ensure_preferences(user)
    active_views: dict[str, Any] = user.preferences.setdefault("active_views", {})

    if payload.active_view_id is None:
        # 清除偏好（key 统一用 str）
        active_views.pop(str(table_id), None)
    else:
        # 设置偏好
        active_views[str(table_id)] = payload.active_view_id

    # JSON 列 in-place 修改需要显式标记脏状态
    flag_modified(user, "preferences")
    db.commit()

    return {"table_id": table_id, "active_view_id": payload.active_view_id}
