"""design 插件路由：设计 CRUD / 即时编译 / 版本列表（ADR 0079 §3）.

权限口径（D6）：全部端点要求工作区成员（读）；写端点（POST / PUT / DELETE）
owner / editor，viewer 403（ADR 0047 统一文案）。preview 是**无写副作用的
即时编译**（边界 #1），按读语义对成员开放（viewer 可在只读态查看渲染）。

版本口径（D7）：创建即落 v1，每次保存原文落新版本（number 单调递增）。
"""

from __future__ import annotations

import dataclasses
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, ConflictError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
from cndb.plugins.design.schemas import (
    DesignContentSave,
    DesignCreate,
    DesignDetail,
    DesignListItem,
    DesignUpdate,
    DesignVersionItem,
    DiagnosticItem,
    PreviewRequest,
    PreviewResponse,
)
from cndb.plugins.design.services.dsl.compile import CompileResult, compile_design
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/designs", tags=["design"])


def _require_member(db: Session, workspace_id: int, user: User) -> None:
    """读门槛：工作区成员（viewer 可读，ADR 0079 D6）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.VIEWER)


def _require_editor(db: Session, workspace_id: int, user: User) -> None:
    """写门槛：owner / editor（viewer 403，ADR 0047 统一文案）."""
    check_workspace_permission(db, workspace_id, user, WorkspaceRole.EDITOR)


def _design_or_404(db: Session, workspace_id: int, design_id: int) -> DesignDesign:
    """按工作区 + 设计 ID 取未软删的设计（不存在 / 已软删 404）."""
    design = (
        db.query(DesignDesign)
        .filter(
            DesignDesign.id == design_id,
            DesignDesign.workspace_id == workspace_id,
            DesignDesign.is_deleted.is_(False),
        )
        .first()
    )
    if design is None:
        raise NotFoundError("设计不存在", code="design_not_found")
    return design


def _compile_or_400(content: str) -> dict[str, Any]:
    """编译原文，失败抛 400（诊断并入 detail，行 / 列定位；I2 拒绝落库）.

    编辑器 gutter 的结构化诊断由 preview 端点承载；此处 detail 为
    人读的拼接文案，保持 ``{detail, code}`` 统一错误契约不破.
    """
    result = compile_design(content)
    if not result.ok:
        raise BadRequestError(
            "；".join(f"第{d.line}行第{d.col}列：{d.message}" for d in result.diagnostics) or "编译失败",
            code="design_compile_failed",
        )
    return result.ir or {"version": 1, "nodes": []}


def _assert_title_available(db: Session, workspace_id: int, title: str, *, exclude_id: int | None = None) -> None:
    """同工作区内设计名唯一（含软删项；冲突 409）."""
    query = db.query(DesignDesign).filter(
        DesignDesign.workspace_id == workspace_id,
        DesignDesign.title == title,
    )
    if exclude_id is not None:
        query = query.filter(DesignDesign.id != exclude_id)
    if query.first() is not None:
        raise ConflictError(f"同名设计已存在：{title}", code="design_title_conflict")


def _latest_version_number(db: Session, design_id: int) -> int:
    """该设计当前最大版本号（无版本返回 0）."""
    number = (
        db.query(func.max(DesignDesignVersion.version_number))
        .filter(DesignDesignVersion.design_id == design_id)
        .scalar()
    )
    return int(number or 0)


def _version_count_map(db: Session, design_ids: list[int]) -> dict[int, int]:
    """批量统计版本数（列表页展示用，单次分组查询）."""
    if not design_ids:
        return {}
    rows = (
        db.query(DesignDesignVersion.design_id, func.count(DesignDesignVersion.id))
        .filter(DesignDesignVersion.design_id.in_(design_ids))
        .group_by(DesignDesignVersion.design_id)
        .all()
    )
    return {int(design_id): int(count) for design_id, count in rows}


def _add_version(
    db: Session,
    design: DesignDesign,
    user: User,
    *,
    content: str,
    compiled: dict[str, Any],
    comment: str = "",
) -> int:
    """为设计落一个新版本，返回版本号（D7：每次保存落一版）."""
    number = _latest_version_number(db, design.id) + 1
    db.add(
        DesignDesignVersion(
            design_id=design.id,
            workspace_id=design.workspace_id,
            version_number=number,
            content=content,
            compiled=compiled,
            comment=comment,
            created_by_id=user.id,
        )
    )
    return number


def _detail(db: Session, design: DesignDesign, *, version_number: int | None = None) -> DesignDetail:
    """ORM → 详情响应（``version_number`` 缺省取当前最新版本号）."""
    response = DesignDetail.model_validate(design)
    response.version_number = _latest_version_number(db, design.id) if version_number is None else version_number
    return response


@router.get("", response_model=list[DesignListItem])
def list_designs(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q_title: Annotated[str | None, Query(max_length=200)] = None,
) -> list[DesignListItem]:
    """设计列表（过滤软删，按更新时间倒序）."""
    _require_member(db, workspace_id, current_user)
    query = db.query(DesignDesign).filter(
        DesignDesign.workspace_id == workspace_id,
        DesignDesign.is_deleted.is_(False),
    )
    if q_title:
        query = query.filter(DesignDesign.title.contains(q_title))
    rows = query.order_by(DesignDesign.updated_at.desc(), DesignDesign.id.desc()).all()
    counts = _version_count_map(db, [row.id for row in rows])
    items: list[DesignListItem] = []
    for row in rows:
        item = DesignListItem.model_validate(row)
        item.version_count = counts.get(row.id, 0)
        items.append(item)
    return items


@router.post("", response_model=DesignDetail, status_code=status.HTTP_201_CREATED)
def create_design(
    workspace_id: int,
    payload: DesignCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDetail:
    """新建设计：原文必经编译（失败 400），创建即落 v1 版本（D7）."""
    _require_editor(db, workspace_id, current_user)
    ir = _compile_or_400(payload.content)
    _assert_title_available(db, workspace_id, payload.title)
    design = DesignDesign(
        workspace_id=workspace_id,
        title=payload.title,
        content=payload.content,
        compiled=ir,
        description=payload.description,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(design)
    db.flush()
    number = _add_version(db, design, current_user, content=payload.content, compiled=ir)
    db.commit()
    db.refresh(design)
    return _detail(db, design, version_number=number)


@router.post("/preview", response_model=PreviewResponse)
def preview_design(
    workspace_id: int,
    payload: PreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PreviewResponse:
    """即时编译（不落库、不计版本；参数面板改参重编译共用，D3）."""
    _require_member(db, workspace_id, current_user)
    result: CompileResult = compile_design(payload.content, payload.overrides)
    return PreviewResponse(
        ok=result.ok,
        ir=result.ir,
        diagnostics=[DiagnosticItem(**dataclasses.asdict(item)) for item in result.diagnostics],
    )


@router.get("/{design_id}", response_model=DesignDetail)
def get_design(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDetail:
    """设计详情（含原文与 IR 快照；成员可读）."""
    _require_member(db, workspace_id, current_user)
    return _detail(db, _design_or_404(db, workspace_id, design_id))


@router.put("/{design_id}", response_model=DesignDetail)
def update_design(
    workspace_id: int,
    design_id: int,
    payload: DesignUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDetail:
    """改名 / 描述（不触发重编译与版本）."""
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    if payload.title is not None and payload.title != design.title:
        _assert_title_available(db, workspace_id, payload.title, exclude_id=design.id)
        design.title = payload.title
    if payload.description is not None:
        design.description = payload.description
    design.updated_by_id = current_user.id
    db.commit()
    db.refresh(design)
    return _detail(db, design)


@router.put("/{design_id}/content", response_model=DesignDetail)
def save_design_content(
    workspace_id: int,
    design_id: int,
    payload: DesignContentSave,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDetail:
    """保存原文：编译通过才更新 ``content``/``compiled`` 并落新版本（失败旧 IR 不动，边界 #2）."""
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    ir = _compile_or_400(payload.content)
    design.content = payload.content
    design.compiled = ir
    design.updated_by_id = current_user.id
    number = _add_version(db, design, current_user, content=payload.content, compiled=ir, comment=payload.comment)
    db.commit()
    db.refresh(design)
    return _detail(db, design, version_number=number)


@router.delete("/{design_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_design(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """软删设计（列表与详情均不可见；回收站 UI 不在本期范围）."""
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    design.is_deleted = True
    design.updated_by_id = current_user.id
    db.commit()


@router.get("/{design_id}/versions", response_model=list[DesignVersionItem])
def list_design_versions(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DesignVersionItem]:
    """版本列表（按版本号倒序；回看 / 恢复端点属 P2）."""
    _require_member(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    rows = (
        db.query(DesignDesignVersion)
        .filter(DesignDesignVersion.design_id == design.id)
        .order_by(DesignDesignVersion.version_number.desc())
        .all()
    )
    return [DesignVersionItem.model_validate(row) for row in rows]


__all__ = ["router"]
