"""design 插件路由：设计文件库 CRUD / IR 快照 / 版本 / 引用（ADR 0079 §3、ADR 0083、ADR 0086 §4）.

权限口径（D6）：全部端点要求工作区成员（读）；写端点（POST / PUT / DELETE）
owner / editor，viewer 403（ADR 0047 统一文案）。preview 是**无写副作用的
即时编译**（边界 #1），按读语义对成员开放（viewer 可在只读态查看渲染）。

版本口径（D7）：创建即落 v1，每次保存原文落新版本（number 单调递增）。

文件库口径（ADR 0086）：详情移除 ``compiled``（D10，唯一破坏性变更），打开走
``GET /{id}/ir`` + ETag；保存按工作区 resolver 编译 ``use`` 引用并写依赖闭包；
被引用文件保存后沿反向引用图置 ``dependencies_stale``（D6）；删除被引用文件
409（D3）；历史恢复按版本依赖快照编译（I5）。
"""

from __future__ import annotations

import dataclasses
import re
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, ConflictError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.design.models import (
    CHANGE_TYPE_AUTO,
    CHANGE_TYPE_MANUAL,
    CHANGE_TYPE_REFRESH,
    CHANGE_TYPE_ROLLBACK,
    DesignDesign,
    DesignDesignref,
    DesignDesignVersion,
)
from cndb.plugins.design.schemas import (
    DesignContentSave,
    DesignCreate,
    DesignDependenciesResponse,
    DesignDependencyItem,
    DesignDetail,
    DesignIRResponse,
    DesignListItem,
    DesignOutlineResult,
    DesignRefreshRequest,
    DesignUpdate,
    DesignVersionDetail,
    DesignVersionDiffResponse,
    DesignVersionItem,
    DiagnosticItem,
    PreviewRequest,
    PreviewResponse,
)
from cndb.plugins.design.services.diff import design_diff
from cndb.plugins.design.services.dsl.compile import IR_VERSION, CompileResult, compile_design
from cndb.plugins.design.services.files import (
    build_resolver,
    compile_design_file,
    content_hash,
    direct_use_keys,
    latest_version_map,
    latest_version_number,
    mark_referrers_stale,
    sync_refs,
)
from cndb.plugins.design.services.keys import generate_file_key
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
    """独立编译原文，失败抛 400（诊断并入 detail，行 / 列定位；I2 拒绝落库）.

    仅用于无文件身份的只读派生（旧快照大纲兜底）；保存 / 预览 / 恢复一律走
    ``_compile_for_design``（带工作区 resolver）。
    """
    result = compile_design(content)
    if not result.ok:
        raise BadRequestError(
            "；".join(f"第{d.line}行第{d.col}列：{d.message}" for d in result.diagnostics) or "编译失败",
            code="design_compile_failed",
        )
    return result.ir or {"version": IR_VERSION, "nodes": [], "outline": {"children": []}}


def _compile_for_design(
    db: Session,
    design: DesignDesign,
    content: str | None = None,
    *,
    pinned: dict[str, int] | None = None,
) -> CompileResult:
    """以设计文件身份编译（kind / file_id / 工作区 resolver），失败 400."""
    result = compile_design_file(db, design, content, pinned=pinned)
    if not result.ok:
        raise BadRequestError(
            "；".join(f"第{d.line}行第{d.col}列：{d.message}" for d in result.diagnostics) or "编译失败",
            code="design_compile_failed",
        )
    return result


def _design_outline(design: DesignDesign) -> tuple[dict[str, Any], Literal["compiled", "content"]]:
    """取设计装配大纲：快照优先，历史快照（IR v1 无 outline）按原文即时编译派生.

    只读口径（ADR 0083 D5）：content 派生不落库、不计数版本；content 派生失败
    按保存端点同口径 400（原文落库时已编译通过，此处失败说明定义已不可编译）。
    """
    compiled = design.compiled or {}
    outline = compiled.get("outline") if isinstance(compiled, dict) else None
    if isinstance(outline, dict) and isinstance(outline.get("children"), list):
        return {"children": outline["children"]}, "compiled"
    ir = _compile_or_400(design.content)
    derived = ir.get("outline") if isinstance(ir.get("outline"), dict) else None
    children = derived.get("children") if isinstance(derived, dict) else None
    return {"children": children if isinstance(children, list) else []}, "content"


def _assert_title_available(
    db: Session,
    workspace_id: int,
    title: str,
    *,
    folder: str = "",
    exclude_id: int | None = None,
) -> None:
    """同工作区同目录内设计名唯一（含软删项；冲突 409，ADR 0086 D1 唯一键）."""
    query = db.query(DesignDesign).filter(
        DesignDesign.workspace_id == workspace_id,
        DesignDesign.title == title,
        DesignDesign.folder == folder,
    )
    if exclude_id is not None:
        query = query.filter(DesignDesign.id != exclude_id)
    if query.first() is not None:
        raise ConflictError(f"同名设计已存在：{title}", code="design_title_conflict")


def _validate_folder(folder: str) -> str:
    """目录规范化（ADR 0086 §5）：仅 a/b 相对形态，拒绝绝对路径 / .. / 反斜杠 / 控制字符."""
    cleaned = folder.strip()
    if not cleaned:
        return ""
    if len(cleaned) > 200 or cleaned.startswith("/") or re.search(r"[\x00-\x1f\\]", cleaned) or ".." in cleaned:
        raise BadRequestError(
            "目录仅支持 a/b 形式的相对路径，禁止绝对路径、..、反斜杠与控制字符",
            code="design_folder_invalid",
        )
    if any(segment in ("", ".") for segment in cleaned.split("/")):
        raise BadRequestError("目录段不能为空或 .", code="design_folder_invalid")
    return cleaned


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
    change_type: str,
    comment: str = "",
    dependencies: list[dict[str, Any]] | None = None,
) -> int:
    """为设计落一个新版本，返回版本号（D7：每次保存落一版；I5 依赖闭包）.

    ``change_type`` 必填（I1 单一落版入口 / I4 类型不可伪造）：四类来源由调用
    方显式传入，``refresh`` / ``rollback`` 仅服务端端点赋值（ADR 0113）。
    """
    number = latest_version_number(db, design.id) + 1
    db.add(
        DesignDesignVersion(
            design_id=design.id,
            workspace_id=design.workspace_id,
            version_number=number,
            change_type=change_type,
            content=content,
            compiled=compiled,
            dependencies=[dict(item) for item in (dependencies or [])],
            comment=comment,
            created_by_id=user.id,
        )
    )
    return number


def _latest_version(db: Session, design_id: int) -> DesignDesignVersion | None:
    """取设计最新版本行（无版本返回 None；保存去重与主动提升用，ADR 0113 §2）."""
    return (
        db.query(DesignDesignVersion)
        .filter(DesignDesignVersion.design_id == design_id)
        .order_by(DesignDesignVersion.version_number.desc())
        .first()
    )


def _dependency_tuples(result: CompileResult) -> list[dict[str, Any]]:
    """CompileResult.dependencies → 可 JSON 化的闭包列表."""
    return [
        {
            "file_id": item.file_id,
            "file_key": item.file_key,
            "version_number": item.version_number,
            "content_hash": item.content_hash,
        }
        for item in result.dependencies
    ]


def _detail(db: Session, design: DesignDesign, *, version_number: int | None = None) -> DesignDetail:
    """ORM → 详情响应（``version_number`` 缺省取当前最新版本号；D10 无 compiled）."""
    response = DesignDetail.model_validate(design)
    response.version_number = latest_version_number(db, design.id) if version_number is None else version_number
    response.content_hash = content_hash(design.content)
    return response


def _referrers(db: Session, design: DesignDesign) -> list[DesignDesign]:
    """引用当前设计且未软删的设计清单（删除阻断用，D3）."""
    return (
        db.query(DesignDesign)
        .join(DesignDesignref, DesignDesignref.design_id == DesignDesign.id)
        .filter(
            DesignDesignref.target_design_id == design.id,
            DesignDesign.workspace_id == design.workspace_id,
            DesignDesign.is_deleted.is_(False),
            DesignDesign.id != design.id,
        )
        .all()
    )


@router.get("", response_model=list[DesignListItem])
def list_designs(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q_title: Annotated[str | None, Query(max_length=200)] = None,
    kind: Annotated[Literal["part", "assembly"] | None, Query()] = None,
    folder: Annotated[str | None, Query(max_length=200)] = None,
) -> list[DesignListItem]:
    """设计文件列表（过滤软删，按更新时间倒序；支持 kind / folder / q_title 过滤）."""
    _require_member(db, workspace_id, current_user)
    query = db.query(DesignDesign).filter(
        DesignDesign.workspace_id == workspace_id,
        DesignDesign.is_deleted.is_(False),
    )
    if q_title:
        query = query.filter(DesignDesign.title.contains(q_title))
    if kind:
        query = query.filter(DesignDesign.kind == kind)
    if folder:
        query = query.filter(DesignDesign.folder == folder)
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
    """新建设计文件：原文必经编译（失败 400），创建即落 v1（D7）；part 同口径."""
    _require_editor(db, workspace_id, current_user)
    folder = _validate_folder(payload.folder)
    # 先编译后落行：失败库内零残留（I2）
    result = compile_design(
        payload.content,
        file_kind=payload.kind,
        resolver=build_resolver(db, workspace_id),
    )
    if not result.ok:
        raise BadRequestError(
            "；".join(f"第{d.line}行第{d.col}列：{d.message}" for d in result.diagnostics) or "编译失败",
            code="design_compile_failed",
        )
    assert result.ir is not None
    _assert_title_available(db, workspace_id, payload.title, folder=folder)
    design = DesignDesign(
        workspace_id=workspace_id,
        title=payload.title,
        kind=payload.kind,
        folder=folder,
        file_key=generate_file_key(db, workspace_id, payload.title, preferred=payload.file_key or ""),
        content=payload.content,
        compiled=result.ir,
        dependencies=_dependency_tuples(result),
        description=payload.description,
        created_by_id=current_user.id,
        updated_by_id=current_user.id,
    )
    db.add(design)
    db.flush()
    number = _add_version(
        db,
        design,
        current_user,
        content=payload.content,
        compiled=result.ir,
        change_type=CHANGE_TYPE_MANUAL,
        dependencies=_dependency_tuples(result),
    )
    sync_refs(db, design, direct_use_keys(design.content))
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
    """即时编译（不落库、不计版本；参数面板改参重编译共用，D3）.

    带 ``design_id`` 时按该文件身份解析 ``use`` 引用（ADR 0086 §4）。
    """
    _require_member(db, workspace_id, current_user)
    if payload.design_id is not None:
        design = _design_or_404(db, workspace_id, payload.design_id)
        result = compile_design(
            payload.content,
            payload.overrides,
            file_kind=design.kind,
            file_id=design.id,
            resolver=build_resolver(db, workspace_id),
        )
    else:
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
    """设计文件详情（原文 + 文件身份；**不含** compiled，D10）."""
    _require_member(db, workspace_id, current_user)
    return _detail(db, _design_or_404(db, workspace_id, design_id))


@router.get("/{design_id}/ir")
def get_design_ir(
    workspace_id: int,
    design_id: int,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """IR 快照直用（C7 / I6）：ETag = ``content_hash-version``，命中 If-None-Match 回 304."""
    _require_member(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    version_number = latest_version_number(db, design.id)
    etag = f'"{content_hash(design.content)}-{version_number}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})
    payload = DesignIRResponse(
        design_id=design.id,
        version_number=version_number,
        content_hash=content_hash(design.content),
        ir=design.compiled or {"version": IR_VERSION, "nodes": [], "outline": {"children": []}},
    )
    return Response(
        content=payload.model_dump_json(),
        media_type="application/json",
        headers={"ETag": etag},
    )


@router.put("/{design_id}", response_model=DesignDetail)
def update_design(
    workspace_id: int,
    design_id: int,
    payload: DesignUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDetail:
    """改名 / 描述 / 目录（不触发重编译与版本；file_key 不可改，ADR 0086 §4）."""
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    new_folder = design.folder
    if payload.folder is not None:
        new_folder = _validate_folder(payload.folder)
        if new_folder != design.folder and payload.title is None:
            _assert_title_available(db, workspace_id, design.title, folder=new_folder, exclude_id=design.id)
    if payload.title is not None and payload.title != design.title:
        _assert_title_available(db, workspace_id, payload.title, folder=new_folder, exclude_id=design.id)
        design.title = payload.title
    if payload.description is not None:
        design.description = payload.description
    design.folder = new_folder
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
    """保存原文：按文件身份编译（resolver 解析 use），写依赖闭包并同步引用索引.

    成功后沿反向引用图把直接 / 传递引用方置 ``dependencies_stale``（D6）。

    去重与主动提升（ADR 0113 §2 / D7）：内容与最新版一致时 —— ``auto`` 不落版；
    ``manual`` 且最新版为 ``auto`` 时把该行提升为 ``manual``（不新增版本），其余
    不落版直接返回当前详情。
    """
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    latest = _latest_version(db, design.id)
    if latest is not None and latest.content == payload.content:
        if payload.change_type == CHANGE_TYPE_MANUAL and latest.change_type == CHANGE_TYPE_AUTO:
            latest.change_type = CHANGE_TYPE_MANUAL
            if payload.comment:
                latest.comment = payload.comment
            db.commit()
            db.refresh(design)
        return _detail(db, design, version_number=latest.version_number)
    result = _compile_for_design(db, design, payload.content)
    assert result.ir is not None
    design.content = payload.content
    design.compiled = result.ir
    design.dependencies = _dependency_tuples(result)
    design.updated_by_id = current_user.id
    number = _add_version(
        db,
        design,
        current_user,
        content=payload.content,
        compiled=result.ir,
        change_type=payload.change_type,
        comment=payload.comment,
        dependencies=_dependency_tuples(result),
    )
    sync_refs(db, design, [item.file_key for item in result.dependencies])
    mark_referrers_stale(db, design.id)
    db.commit()
    db.refresh(design)
    return _detail(db, design, version_number=number)


@router.post("/{design_id}/refresh", response_model=DesignDetail)
def refresh_design(
    workspace_id: int,
    design_id: int,
    payload: DesignRefreshRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDetail:
    """依赖刷新（D6）：以当前最新依赖重编译并落新版本，清 ``dependencies_stale``."""
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    result = _compile_for_design(db, design)
    assert result.ir is not None
    design.compiled = result.ir
    design.dependencies = _dependency_tuples(result)
    design.dependencies_stale = False
    design.updated_by_id = current_user.id
    number = _add_version(
        db,
        design,
        current_user,
        content=design.content,
        compiled=result.ir,
        change_type=CHANGE_TYPE_REFRESH,
        comment=payload.comment or "依赖更新",
        dependencies=_dependency_tuples(result),
    )
    sync_refs(db, design, direct_use_keys(design.content))
    db.commit()
    db.refresh(design)
    return _detail(db, design, version_number=number)


@router.get("/{design_id}/dependencies", response_model=DesignDependenciesResponse)
def get_design_dependencies(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDependenciesResponse:
    """当前直接引用（items）与引用方清单（referrers），成员可读（ADR 0086 §4）."""
    _require_member(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    versions = latest_version_map(db, [design.id])

    def _item(row: DesignDesign) -> DesignDependencyItem:
        return DesignDependencyItem(
            design_id=row.id,
            file_key=row.file_key,
            title=row.title,
            folder=row.folder,
            kind=row.kind,
            version_number=versions.get(row.id, 0),
            dependencies_stale=row.dependencies_stale,
        )

    targets = (
        db.query(DesignDesign)
        .join(DesignDesignref, DesignDesignref.target_design_id == DesignDesign.id)
        .filter(
            DesignDesignref.design_id == design.id,
            DesignDesign.workspace_id == design.workspace_id,
            DesignDesign.is_deleted.is_(False),
        )
        .all()
    )
    return DesignDependenciesResponse(
        design_id=design.id,
        items=[_item(row) for row in targets],
        referrers=[_item(row) for row in _referrers(db, design)],
    )


@router.delete("/{design_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_design(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """软删设计（被未删除文件引用时 409 并返回引用方；不提供强制断链，D3）."""
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    referrers = _referrers(db, design)
    if referrers:
        names = "、".join(row.title for row in referrers)
        raise ConflictError(
            f"设计被其他文件引用，无法删除：{names}",
            code="design_file_referenced",
        )
    design.is_deleted = True
    design.updated_by_id = current_user.id
    db.commit()


@router.get("/{design_id}/outline", response_model=DesignOutlineResult)
def get_design_outline(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignOutlineResult:
    """装配大纲（ADR 0083 D4）：组件 / 分组 / 零件树 + 1 基源位置，成员可读."""
    _require_member(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    outline, source = _design_outline(design)
    return DesignOutlineResult(
        design_id=design.id,
        version_number=latest_version_number(db, design.id),
        outline=outline,
        source=source,
    )


@router.get("/{design_id}/versions", response_model=list[DesignVersionItem])
def list_design_versions(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DesignVersionItem]:
    """版本列表（按版本号倒序；不含原文，回看走单版本端点）."""
    _require_member(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    rows = (
        db.query(DesignDesignVersion)
        .filter(DesignDesignVersion.design_id == design.id)
        .order_by(DesignDesignVersion.version_number.desc())
        .all()
    )
    return [DesignVersionItem.model_validate(row) for row in rows]


def _version_or_404(db: Session, design: DesignDesign, version_number: int) -> DesignDesignVersion:
    """取指定版本（不存在 404；软删设计的版本随设计 404）."""
    version = (
        db.query(DesignDesignVersion)
        .filter(
            DesignDesignVersion.design_id == design.id,
            DesignDesignVersion.version_number == version_number,
        )
        .first()
    )
    if version is None:
        raise NotFoundError("设计版本不存在", code="design_version_not_found")
    return version


@router.get("/{design_id}/versions/{version_number}", response_model=DesignVersionDetail)
def get_design_version(
    workspace_id: int,
    design_id: int,
    version_number: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignVersionDetail:
    """版本回看：该版原文、IR 快照与依赖闭包快照（成员可读，ADR 0079 D7 / 0086 I5）."""
    _require_member(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    version = _version_or_404(db, design, version_number)
    detail = DesignVersionDetail.model_validate(version)
    detail.dependencies = list(version.dependencies or [])
    return detail


@router.get("/{design_id}/diff", response_model=DesignVersionDiffResponse)
def get_design_version_diff(
    workspace_id: int,
    design_id: int,
    base: Annotated[int, Query(ge=1, description="基准版本号")],
    head: Annotated[int, Query(ge=1, description="目标版本号")],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignVersionDiffResponse:
    """两版本对比（成员可读）：unified diff + 增删行数 + 结构变化摘要（ADR 0113 §3）."""
    _require_member(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    return DesignVersionDiffResponse(**design_diff(db, design, base, head))


@router.post("/{design_id}/versions/{version_number}/restore", response_model=DesignDetail)
def restore_design_version(
    workspace_id: int,
    design_id: int,
    version_number: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDetail:
    """恢复历史版：按版本依赖快照编译并落新版本（editor 权限，D7 / I5）.

    快照依赖（file_key → version）逐一核对存在性，缺失 400
    ``design_dependency_missing``（不静默取最新）；快照为空的历史版本按
    当前最新依赖编译（v13 之前的存量版本无闭包）。
    """
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    version = _version_or_404(db, design, version_number)
    pinned: dict[str, int] = {}
    for item in version.dependencies or []:
        if isinstance(item, dict) and item.get("file_key") and item.get("version_number"):
            pinned[str(item["file_key"])] = int(item["version_number"])
    missing = [key for key in pinned if build_resolver(db, workspace_id, pinned=pinned)(key) is None]
    if missing:
        raise BadRequestError(
            f"依赖快照缺失，无法按历史复现编译：{'、'.join(missing)}",
            code="design_dependency_missing",
        )
    result = _compile_for_design(db, design, version.content, pinned=pinned or None)
    assert result.ir is not None
    design.content = version.content
    design.compiled = result.ir
    design.dependencies = _dependency_tuples(result)
    design.updated_by_id = current_user.id
    number = _add_version(
        db,
        design,
        current_user,
        content=version.content,
        compiled=result.ir,
        change_type=CHANGE_TYPE_ROLLBACK,
        comment=f"恢复自 v{version_number}",
        dependencies=_dependency_tuples(result),
    )
    sync_refs(db, design, [item.file_key for item in result.dependencies])
    mark_referrers_stale(db, design.id)
    db.commit()
    db.refresh(design)
    return _detail(db, design, version_number=number)


__all__ = ["router"]
