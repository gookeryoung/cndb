"""数据表分组路由 —— 工作区级「表分组」（需求 0137）.

口径：
- 分组成员可读（VIEWER）；建组 / 改名 / 排序 / 删除要求 EDITOR。
- 表用 ``DataTable.group_id`` 归属分组，可空 = 未分组（默认）。
- 删除分组只把成员表回落为未分组，不删表；分组名工作区内唯一。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, TableGroup
from cndb.plugins.tables.schemas import TableGroupCreate, TableGroupResponse, TableGroupUpdate
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/table-groups", tags=["table-groups"])

_MAX_NAME_LEN = 80


def _clean_name(raw: str | None) -> str:
    name = (raw or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="分组名不能为空")
    if len(name) > _MAX_NAME_LEN:
        raise HTTPException(status_code=400, detail=f"分组名不能超过 {_MAX_NAME_LEN} 个字符")
    return name


def _get_group_or_404(db: Session, workspace_id: int, group_id: int) -> TableGroup:
    group = db.query(TableGroup).filter(TableGroup.id == group_id, TableGroup.workspace_id == workspace_id).first()
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    return group


def _ensure_unique_name(db: Session, workspace_id: int, name: str, *, exclude_id: int | None = None) -> None:
    query = db.query(TableGroup.id).filter(
        TableGroup.workspace_id == workspace_id,
        TableGroup.name == name,
    )
    if exclude_id is not None:
        query = query.filter(TableGroup.id != exclude_id)
    if query.first() is not None:
        raise HTTPException(status_code=400, detail=f"分组名已存在：{name}")


@router.get("", response_model=list[TableGroupResponse])
def list_table_groups(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TableGroup]:
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.VIEWER)
    return (
        db.query(TableGroup)
        .filter(TableGroup.workspace_id == workspace_id)
        .order_by(TableGroup.order, TableGroup.id)
        .all()
    )


@router.post("", response_model=TableGroupResponse, status_code=status.HTTP_201_CREATED)
def create_table_group(
    workspace_id: int,
    payload: TableGroupCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TableGroup:
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    name = _clean_name(payload.name)
    _ensure_unique_name(db, workspace_id, name)
    if payload.order is None:
        max_order = db.query(func.max(TableGroup.order)).filter(TableGroup.workspace_id == workspace_id).scalar()
        order = int(max_order or 0) + 1
    else:
        order = payload.order
    group = TableGroup(workspace_id=workspace_id, name=name, order=order)
    db.add(group)
    db.commit()
    db.refresh(group)
    return group


@router.post("/reorder", response_model=list[TableGroupResponse])
def reorder_table_groups(
    workspace_id: int,
    group_ids: list[int],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[TableGroup]:
    """按传入顺序重排分组（只影响传入的分组，未传的保持原 order）。"""
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    groups = db.query(TableGroup).filter(TableGroup.workspace_id == workspace_id, TableGroup.id.in_(group_ids)).all()
    by_id = {g.id: g for g in groups}
    for idx, gid in enumerate(group_ids):
        if gid in by_id:
            by_id[gid].order = idx
    db.commit()
    return (
        db.query(TableGroup)
        .filter(TableGroup.workspace_id == workspace_id)
        .order_by(TableGroup.order, TableGroup.id)
        .all()
    )


@router.patch("/{group_id}", response_model=TableGroupResponse)
def update_table_group(
    workspace_id: int,
    group_id: int,
    payload: TableGroupUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TableGroup:
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    group = _get_group_or_404(db, workspace_id, group_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data:
        name = _clean_name(data["name"])
        _ensure_unique_name(db, workspace_id, name, exclude_id=group.id)
        group.name = name
    if "order" in data and data["order"] is not None:
        group.order = int(data["order"])
    db.commit()
    db.refresh(group)
    return group


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_table_group(
    workspace_id: int,
    group_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.EDITOR)
    group = _get_group_or_404(db, workspace_id, group_id)
    # 显式回落未分组（不依赖数据库 FK 开关），再删分组
    db.query(DataTable).filter(
        DataTable.workspace_id == workspace_id,
        DataTable.group_id == group.id,
    ).update({DataTable.group_id: None}, synchronize_session=False)
    db.delete(group)
    db.commit()
    # 表列表缓存里的 group_id 已变化
    from cndb.plugins.tables.routers.tables import _invalidate_table_list_cache

    _invalidate_table_list_cache(workspace_id)


__all__ = ["router"]
