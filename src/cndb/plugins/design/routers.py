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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.errors import BadRequestError, CndbError, ConflictError, NotFoundError, PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.design.models import (
    CHANGE_TYPE_AUTO,
    CHANGE_TYPE_MANUAL,
    CHANGE_TYPE_REFRESH,
    CHANGE_TYPE_ROLLBACK,
    DesignDesign,
    DesignDesignref,
    DesignDesignVersion,
    DesignLibraryModule,
    DesignLibraryref,
    DesignLibraryVersion,
)
from cndb.plugins.design.schemas import (
    DesignContentSave,
    DesignCreate,
    DesignDependenciesResponse,
    DesignDependencyItem,
    DesignDetail,
    DesignDraftPayload,
    DesignDraftSave,
    DesignIRResponse,
    DesignLibraryDependencyItem,
    DesignListItem,
    DesignOutlineResult,
    DesignPublishRequest,
    DesignPublishResponse,
    DesignRefreshRequest,
    DesignUpdate,
    DesignVersionDetail,
    DesignVersionDiffResponse,
    DesignVersionItem,
    DiagnosticItem,
    LibraryFileItem,
    LibraryModuleDetail,
    LibraryModuleItem,
    LibraryModulePatch,
    LibraryPreviewRequest,
    LibraryVersionDetail,
    LibraryVersionItem,
    PreviewRequest,
    PreviewResponse,
)
from cndb.plugins.design.services.content import (
    add_version as _add_version,
)
from cndb.plugins.design.services.content import (
    dependency_tuples as _dependency_tuples,
)
from cndb.plugins.design.services.content import (
    latest_version as _latest_version,
)
from cndb.plugins.design.services.content import (
    persist_design_content,
)
from cndb.plugins.design.services.diff import design_diff
from cndb.plugins.design.services.drafts import (
    delete_all_drafts,
    discard_design_draft,
    draft_payload,
    save_design_draft,
)
from cndb.plugins.design.services.dsl.compile import IR_VERSION, CompileResult, compile_design
from cndb.plugins.design.services.files import (
    build_library_resolver,
    build_resolver,
    content_hash,
    direct_library_refs,
    direct_use_keys,
    latest_version_map,
    latest_version_number,
    library_grants,
    sync_refs,
)
from cndb.plugins.design.services.keys import generate_file_key
from cndb.plugins.design.services.library import (
    LibraryPublishError,
    can_manage_module,
    is_system_admin,
    list_library_modules,
    module_latest_versions,
    module_version,
    module_version_stats,
    module_versions,
    preview_library_version,
    publish_design,
)
from cndb.plugins.tables.services.core.access import check_workspace_permission
from cndb.plugins.workspaces.models import WorkspaceRole

router = APIRouter(prefix="/{workspace_id}/designs", tags=["design"])
library_router = APIRouter(prefix="/{workspace_id}/design-library", tags=["design-library"])


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
        library_resolver=build_library_resolver(db, workspace_id),
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
    sync_refs(db, design, direct_use_keys(design.content), direct_library_refs(design.content))
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
            library_resolver=build_library_resolver(db, workspace_id, granted_keys=library_grants(db, design.id)),
        )
    else:
        result: CompileResult = compile_design(
            payload.content,
            payload.overrides,
            library_resolver=build_library_resolver(db, workspace_id),
        )
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


@router.get("/{design_id}/draft", response_model=DesignDraftPayload | None)
def get_design_draft(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any] | None:
    """读取本人草稿（成员可读，但只返回自己的草稿；无草稿 / 与最新版相同返回 null）."""
    _require_member(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    return draft_payload(db, design, current_user)


@router.put("/{design_id}/draft", response_model=DesignDraftPayload | None)
def put_design_draft(
    workspace_id: int,
    design_id: int,
    payload: DesignDraftSave,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any] | None:
    """保存本人草稿：不编译、不落版本；到期时顺带落 ``auto`` 检查点（C4）."""
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    return save_design_draft(
        db,
        design,
        current_user,
        content=payload.content,
        base_version_number=payload.base_version_number,
    )


@router.delete("/{design_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
def delete_design_draft(
    workspace_id: int,
    design_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """丢弃本人草稿（幂等，恒 204）."""
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    discard_design_draft(db, design, current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{design_id}/content", response_model=DesignDetail)
def save_design_content(
    workspace_id: int,
    design_id: int,
    payload: DesignContentSave,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignDetail:
    """手动保存原文：编译通过才落 ``manual`` 版本（ADR 0125 C3 / D4）.

    去重与主动提升（ADR 0113 §2 / D7）：内容与最新版一致时不新增版本；
    最新版为 ``auto`` 检查点时把该行提升为 ``manual``。成功后删除本人草稿。
    """
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    latest = _latest_version(db, design.id)
    if latest is not None and latest.content == payload.content:
        if latest.change_type == CHANGE_TYPE_AUTO:
            latest.change_type = CHANGE_TYPE_MANUAL
            if payload.comment:
                latest.comment = payload.comment
        discard_design_draft(db, design, current_user)
        db.refresh(design)
        return _detail(db, design, version_number=latest.version_number)
    number = persist_design_content(
        db,
        design,
        current_user,
        content=payload.content,
        change_type=CHANGE_TYPE_MANUAL,
        comment=payload.comment,
    )
    discard_design_draft(db, design, current_user)
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
    """依赖刷新（D6）：以当前最新依赖重编译并落新版本，清 ``dependencies_stale``.

    原文未变，不沿反向引用图重复置陈旧标记；成功后清空该设计全部草稿（ADR 0125 D9）。
    """
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    number = persist_design_content(
        db,
        design,
        current_user,
        content=design.content,
        change_type=CHANGE_TYPE_REFRESH,
        comment=payload.comment or "依赖更新",
        propagate_stale=False,
    )
    design.dependencies_stale = False
    delete_all_drafts(db, design.id)
    db.commit()
    db.refresh(design)
    return _detail(db, design, version_number=number)


@router.post("/{design_id}/publish", response_model=DesignPublishResponse)
def publish_design_module(
    workspace_id: int,
    design_id: int,
    payload: DesignPublishRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DesignPublishResponse:
    """发布为复用模块 / 新版本（editor+，ADR 0118 §4 / D1-D3）.

    发布前编译并快照依赖闭包；失败 400 且不落半成品版本。模块内部禁止再
    使用 ``lib:`` 引用（MVP 边界）。
    """
    _require_editor(db, workspace_id, current_user)
    design = _design_or_404(db, workspace_id, design_id)
    try:
        module, version = publish_design(
            db,
            design,
            current_user,
            visibility=payload.visibility,
            name=payload.name,
            description=payload.description,
            comment=payload.comment,
        )
    except LibraryPublishError as exc:
        raise BadRequestError(
            f"第{exc.line}行第{exc.col}列：{exc.message}",
            code="design_publish_failed",
        ) from exc
    db.commit()
    return DesignPublishResponse(
        module_id=module.id,
        module_key=module.module_key,
        version_number=version.version_number,
        visibility=module.visibility,
        name=module.name,
    )


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
    library_rows = (
        db.query(DesignLibraryModule, DesignLibraryVersion)
        .select_from(DesignLibraryref)
        .join(DesignLibraryModule, DesignLibraryModule.id == DesignLibraryref.module_id)
        .join(DesignLibraryVersion, DesignLibraryVersion.id == DesignLibraryref.module_version_id)
        .filter(DesignLibraryref.design_id == design.id)
        .all()
    )
    stats = module_version_stats(db, [module.id for module, _version in library_rows])
    return DesignDependenciesResponse(
        design_id=design.id,
        items=[_item(row) for row in targets],
        library_items=[
            DesignLibraryDependencyItem(
                module_id=module.id,
                module_key=module.module_key,
                name=module.name,
                version_number=version.version_number,
                latest_version=stats.get(module.id, (0, 0))[1],
                has_update=version.version_number < stats.get(module.id, (0, 0))[1],
                visibility=module.visibility,
                is_archived=module.is_archived,
                owner_workspace_id=module.owner_workspace_id,
                bundle_hash=version.bundle_hash,
            )
            for module, version in library_rows
        ],
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
    granted_library_keys: set[tuple[str, int]] = set()
    for item in version.dependencies or []:
        if not isinstance(item, dict) or not item.get("file_key") or not item.get("version_number"):
            continue
        if item.get("source") == "library":
            granted_library_keys.add((str(item["file_key"]), int(item["version_number"])))
        else:
            pinned[str(item["file_key"])] = int(item["version_number"])
    missing = [key for key in pinned if build_resolver(db, workspace_id, pinned=pinned)(key) is None]
    if missing:
        raise BadRequestError(
            f"依赖快照缺失，无法按历史复现编译：{'、'.join(missing)}",
            code="design_dependency_missing",
        )
    library_resolver = build_library_resolver(db, workspace_id, granted_keys=frozenset(granted_library_keys))
    missing_library = [
        f"{key}@v{version_number}"
        for key, version_number in sorted(granted_library_keys)
        if library_resolver(key, version_number) is None
    ]
    if missing_library:
        raise BadRequestError(
            f"复用模块依赖缺失，无法按历史复现编译：{'、'.join(missing_library)}",
            code="design_library_dependency_missing",
        )
    number = persist_design_content(
        db,
        design,
        current_user,
        content=version.content,
        change_type=CHANGE_TYPE_ROLLBACK,
        comment=f"恢复自 v{version_number}",
        pinned=pinned or None,
        granted_library_keys=frozenset(granted_library_keys),
    )
    delete_all_drafts(db, design.id)
    db.commit()
    db.refresh(design)
    return _detail(db, design, version_number=number)


def _library_visible(module: DesignLibraryModule, workspace_id: int) -> bool:
    """浏览可见性：公开模块，或当前工作区自己发布的模块（归档不改变可见性，ADR 0118 §5）."""
    return module.visibility == "public" or module.owner_workspace_id == workspace_id


def _library_granted(db: Session, workspace_id: int, design_id: int | None, module_id: int) -> bool:
    """既有引用授权：该设计已落库引用此模块时放行跨工作区私有 / 归档模块的只读查看."""
    if design_id is None:
        return False
    return (
        db.query(DesignLibraryref.id)
        .join(DesignDesign, DesignDesign.id == DesignLibraryref.design_id)
        .filter(
            DesignLibraryref.design_id == design_id,
            DesignLibraryref.module_id == module_id,
            DesignDesign.workspace_id == workspace_id,
        )
        .first()
        is not None
    )


def _library_module_or_404(
    db: Session,
    workspace_id: int,
    module_id: int,
    *,
    design_id: int | None = None,
) -> DesignLibraryModule:
    """取可见模块（无权与不存在统一 404，不泄露私有 / 归档原因）."""
    module = db.query(DesignLibraryModule).filter(DesignLibraryModule.id == module_id).first()
    if module is None or not (
        _library_visible(module, workspace_id) or _library_granted(db, workspace_id, design_id, module_id)
    ):
        raise NotFoundError("复用模块不存在", code="design_library_module_not_found")
    return module


def _library_version_or_404(db: Session, module: DesignLibraryModule, version_number: int) -> DesignLibraryVersion:
    version = module_version(db, module.id, version_number)
    if version is None:
        raise NotFoundError("复用模块版本不存在", code="design_library_version_not_found")
    return version


def _can_manage_library(db: Session, module: DesignLibraryModule, user: User) -> bool:
    """模块管理权限：系统管理员，或所有者工作区 owner（owner_workspace_id 为空仅管理员）."""
    if can_manage_module(user):
        return True
    if module.owner_workspace_id is None:
        return False
    try:
        check_workspace_permission(db, module.owner_workspace_id, user, WorkspaceRole.OWNER)
    except (HTTPException, CndbError):
        return False
    return True


def _require_library_manager(db: Session, module: DesignLibraryModule, user: User) -> None:
    if _can_manage_library(db, module, user):
        return
    raise PermissionDeniedError(
        "仅模块所有者工作区的拥有者或系统管理员可修改模块",
        code="design_library_forbidden",
    )


def _library_version_item(version: DesignLibraryVersion) -> LibraryVersionItem:
    return LibraryVersionItem(
        id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
        bundle_hash=version.bundle_hash,
        comment=version.comment,
        created_by_id=version.created_by_id,
        created_at=version.created_at,
    )


def _library_module_item(
    module: DesignLibraryModule,
    stats: dict[int, tuple[int, int]],
    latest: DesignLibraryVersion | None,
) -> LibraryModuleItem:
    count, latest_number = stats.get(module.id, (0, 0))
    return LibraryModuleItem(
        id=module.id,
        module_key=module.module_key,
        name=module.name,
        description=module.description,
        visibility=module.visibility,
        owner_workspace_id=module.owner_workspace_id,
        is_archived=module.is_archived,
        version_count=count,
        latest_version=latest_number,
        params=list(latest.params) if latest is not None else [],
        updated_at=module.updated_at,
    )


@library_router.get("/modules", response_model=list[LibraryModuleItem])
def list_library(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    visibility: Annotated[Literal["public", "workspace"] | None, Query()] = None,
    owned_only: Annotated[bool, Query()] = False,
    include_archived: Annotated[bool, Query()] = False,
) -> list[LibraryModuleItem]:
    """模块库浏览：公开 + 当前工作区发布；``include_archived`` 仅所有者工作区 owner（ADR 0118 §5）."""
    _require_member(db, workspace_id, current_user)
    if include_archived and not is_system_admin(current_user):
        check_workspace_permission(db, workspace_id, current_user, WorkspaceRole.OWNER)
    modules = list_library_modules(
        db,
        workspace_id,
        q=q,
        visibility=visibility,
        owned_only=owned_only,
        include_archived=include_archived,
    )
    stats = module_version_stats(db, [module.id for module in modules])
    latest = module_latest_versions(db, [module.id for module in modules])
    return [_library_module_item(module, stats, latest.get(module.id)) for module in modules]


@library_router.get("/modules/{module_id}", response_model=LibraryModuleDetail)
def get_library_module(
    workspace_id: int,
    module_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    design_id: Annotated[int | None, Query(description="既有引用所在设计（私有 / 归档授权）")] = None,
) -> LibraryModuleDetail:
    """模块详情 + 版本列表 + 参数签名；无权 404（ADR 0118 §5）."""
    _require_member(db, workspace_id, current_user)
    module = _library_module_or_404(db, workspace_id, module_id, design_id=design_id)
    versions = module_versions(db, module.id)
    latest = versions[0] if versions else None
    stats = {module.id: (len(versions), versions[0].version_number if versions else 0)}
    item = _library_module_item(module, stats, latest)
    return LibraryModuleDetail(
        **item.model_dump(),
        versions=[_library_version_item(version) for version in versions],
        can_manage=_can_manage_library(db, module, current_user),
    )


@library_router.get("/modules/{module_id}/versions/{version_number}", response_model=LibraryVersionDetail)
def get_library_version(
    workspace_id: int,
    module_id: int,
    version_number: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    design_id: Annotated[int | None, Query(description="既有引用所在设计（私有 / 归档授权）")] = None,
) -> LibraryVersionDetail:
    """版本详情：根原文 + 依赖包元数据（不回传依赖全文，ADR 0118 §6）."""
    _require_member(db, workspace_id, current_user)
    module = _library_module_or_404(db, workspace_id, module_id, design_id=design_id)
    version = _library_version_or_404(db, module, version_number)
    return LibraryVersionDetail(
        **_library_version_item(version).model_dump(),
        content=version.content,
        params=list(version.params),
        files=[
            LibraryFileItem(
                file_key=str(item.get("file_key", "")),
                kind=str(item.get("kind", "part")),
                content_hash=str(item.get("content_hash", "")),
            )
            for item in version.files
        ],
    )


@library_router.post("/modules/{module_id}/versions/{version_number}/preview", response_model=PreviewResponse)
def preview_library_module_version(
    workspace_id: int,
    module_id: int,
    version_number: int,
    payload: LibraryPreviewRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    design_id: Annotated[int | None, Query(description="既有引用所在设计（私有 / 归档授权）")] = None,
) -> PreviewResponse:
    """只读预览模块版本（参数覆盖，无落库，与设计预览同口径）."""
    _require_member(db, workspace_id, current_user)
    module = _library_module_or_404(db, workspace_id, module_id, design_id=design_id)
    version = _library_version_or_404(db, module, version_number)
    result = preview_library_version(version, payload.overrides)
    return PreviewResponse(
        ok=result.ok,
        ir=result.ir,
        diagnostics=[DiagnosticItem(**dataclasses.asdict(item)) for item in result.diagnostics],
    )


@library_router.patch("/modules/{module_id}", response_model=LibraryModuleDetail)
def patch_library_module(
    workspace_id: int,
    module_id: int,
    payload: LibraryModulePatch,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> LibraryModuleDetail:
    """改名称 / 描述 / 可见性 / 归档；仅所有者工作区 owner 或系统管理员（ADR 0118 §5）."""
    _require_member(db, workspace_id, current_user)
    module = _library_module_or_404(db, workspace_id, module_id)
    _require_library_manager(db, module, current_user)
    if payload.visibility == "workspace" and module.owner_workspace_id is None:
        raise BadRequestError(
            "所有者工作区已移除，私有模块无法恢复可见性",
            code="design_library_owner_missing",
        )
    if payload.name is not None:
        module.name = payload.name
    if payload.description is not None:
        module.description = payload.description
    if payload.visibility is not None:
        module.visibility = payload.visibility
    if payload.is_archived is not None:
        module.is_archived = payload.is_archived
    module.updated_by_id = current_user.id
    db.commit()
    db.refresh(module)
    versions = module_versions(db, module.id)
    latest = versions[0] if versions else None
    stats = {module.id: (len(versions), versions[0].version_number if versions else 0)}
    item = _library_module_item(module, stats, latest)
    return LibraryModuleDetail(
        **item.model_dump(),
        versions=[_library_version_item(version) for version in versions],
        can_manage=_can_manage_library(db, module, current_user),
    )


__all__ = ["library_router", "router"]
