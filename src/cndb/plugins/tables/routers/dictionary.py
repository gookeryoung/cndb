"""数据表字段字典导出路由（ADR 0188）.

端点（全部只读，`GET`）：

- ``GET /{wid}/tables/{tid}/dictionary?format=md|xlsx|json|docx|pdf``  单表字段字典
- ``GET /{wid}/tables/dictionary?table_ids=1,2&format=...``            工作区合订
- ``GET /{wid}/tables/{tid}/dictionary/score``                        标准符合度指标

口径（ADR 0188）：

- 权限：``TableAction.READ``；无读权 404（不提示存在性）；
- 可见性同源（I3）：字段集合一律经 ``get_hidden_field_names`` 裁剪，不另写裁剪；
- 不含行数据（I2）：只读 ``DataField`` 元数据，不碰物理表；
- 审计（C9）：写 ``core_event("table.dictionary_export")``，detail 只记定位与计数。

路由注册顺序：静态段 ``/dictionary`` 必须在 ``/{table_id}`` 之前 —— 但本模块挂在
``/tables`` 前缀下且路径首段是 ``dictionary`` / ``{table_id}/dictionary``，
``/tables/dictionary`` 与 ``/tables/{table_id}`` 的歧义由 ``routers/__init__.py``
的挂载顺序解决（dictionary 先于 tables）。
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.core.events import TARGET_TABLE, record_event
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog, DataField, DataTable, TableGroup, TablePermission
from cndb.plugins.tables.routers.bulk_export import _build_export_filename
from cndb.plugins.tables.services.core.access import (
    TableAction,
    get_hidden_field_names,
    get_table_or_404,
)
from cndb.plugins.tables.services.core.row_access import row_rules_active
from cndb.plugins.tables.services.dictionary import (
    build_document,
    build_table_dictionary,
    compute_schema_hash,
    compute_score,
    document_to_dict,
    render_markdown,
    render_xlsx,
)
from cndb.plugins.tables.services.dictionary.build import CHANGE_LOG_LIMIT
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/{workspace_id}/tables", tags=["dictionary"])

#: 支持的格式 → (媒体类型, 扩展名)
_FORMATS: dict[str, tuple[str, str]] = {
    "md": ("text/markdown; charset=utf-8", ".md"),
    "xlsx": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "json": ("application/json", ".json"),
    "docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "pdf": ("application/pdf", ".pdf"),
}

#: 格式别名（前端 / 用户习惯写法）
_FORMAT_ALIASES: dict[str, str] = {
    "markdown": "md",
    "word": "docx",
    "excel": "xlsx",
}


def _normalize_format(fmt: str) -> str:
    """格式名归一化；不支持的值 400."""
    normalized = _FORMAT_ALIASES.get((fmt or "").strip().lower(), (fmt or "").strip().lower())
    if normalized not in _FORMATS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的字典格式: {fmt}，可选 {'/'.join(_FORMATS)}",
        )
    return normalized


def _hidden_by_field(db: Session, table: DataTable, user: User) -> tuple[set[str], dict[str, list[str]]]:
    """当前用户不可见字段集合 + 字段名 → 隐藏角色列表（可见性列渲染用）.

    隐藏口径只有一个来源：``TablePermission.hidden_fields``（角色 → 字段名列表）。
    这里把它反转为「字段 → 角色」，供文档「可见性」列展示「对 viewer 隐藏」。
    """
    hidden = get_hidden_field_names(db, table, user)
    perm = db.query(TablePermission).filter(TablePermission.table_id == table.id).first()
    by_field: dict[str, list[str]] = {}
    if perm is not None and isinstance(perm.hidden_fields, dict):
        for role, names in perm.hidden_fields.items():
            if not isinstance(names, list):
                continue
            for name in names:
                if isinstance(name, str):
                    by_field.setdefault(name, []).append(str(role))
    return hidden, by_field


def _visible_fields(db: Session, table: DataTable, user: User) -> list[DataField]:
    """该表对当前用户可见的字段（按展示顺序）."""
    hidden, _ = _hidden_by_field(db, table, user)
    return [f for f in table.active_fields() if f.name not in hidden]


def _table_names(db: Session, workspace_id: int) -> dict[int, str]:
    """工作区内表 id → 表名（含回收站表：字段可能仍指向它，导出要能显示名字）."""
    rows = db.query(DataTable.id, DataTable.name).filter(DataTable.workspace_id == workspace_id).all()
    return {row[0]: row[1] for row in rows}


def _field_names(fields: list[DataField]) -> dict[int, str]:
    """字段 id → 字段名（用于 link / lookup 的 id 解析）."""
    return {f.id: f.name for f in fields}


def _group_names(db: Session, workspace_id: int) -> dict[int, str]:
    """分组 id → 分组名."""
    rows = db.query(TableGroup.id, TableGroup.name).filter(TableGroup.workspace_id == workspace_id).all()
    return {row[0]: row[1] for row in rows}


def _table_owner_name(db: Session, table: DataTable) -> str | None:
    """表负责人显示名：优先表 owner，回退工作区 owner（与前端「负责人」口径一致）."""
    if table.owner is not None and getattr(table.owner, "username", None):
        return str(table.owner.username)
    owner_member = (
        db.query(WorkspaceMember)
        .filter(
            WorkspaceMember.workspace_id == table.workspace_id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
        .first()
    )
    if owner_member is not None and owner_member.user is not None:
        return str(owner_member.user.username)
    return None


def _change_log(db: Session, table_id: int) -> list[dict[str, str]]:
    """最近字段级变更记录（`tables_auditlog`）.

    当前字段级动作（create / update / delete field）**尚未写审计**，因此绝大多数表
    会返回空列表 —— 渲染层如实输出「暂无字段级变更记录」，不伪造。
    """
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.table_id == table_id, AuditLog.action.like("field%"))
        .order_by(AuditLog.id.desc())
        .limit(CHANGE_LOG_LIMIT)
        .all()
    )
    result: list[dict[str, str]] = []
    for entry in entries:
        actor = db.get(User, entry.actor_id) if entry.actor_id else None
        created = getattr(entry, "created_at", None)
        detail: dict[str, object] = entry.detail if isinstance(entry.detail, dict) else {}
        result.append(
            {
                "at": created.strftime("%Y-%m-%d %H:%M") if isinstance(created, dt.datetime) else "—",
                "action": str(entry.action),
                "actor": str(getattr(actor, "username", "") or "—"),
                "detail": str(detail.get("field_name") or detail.get("summary") or "—"),
            }
        )
    return result


def _views_brief(table: DataTable) -> list[dict[str, Any]]:
    """视图摘要（名字 / 类型 / 是否默认）—— 字典里用于说明「这张表怎么看」."""
    return [
        {
            "name": v.name,
            "view_type": str(v.view_type),
            "is_default": bool(v.is_default),
        }
        for v in sorted(table.views, key=lambda v: (v.order, v.id))
    ]


def _build_for_tables(
    db: Session,
    workspace: Workspace,
    tables: list[DataTable],
    user: User,
    *,
    include_internal: bool,
) -> Any:
    """把一组表组装成 DictionaryDocument（单表 / 合订共用）."""
    table_names = _table_names(db, workspace.id)
    groups = _group_names(db, workspace.id)
    entries = []
    hash_fields: dict[int, list[DataField]] = {}
    for table in tables:
        visible = _visible_fields(db, table, user)
        hash_fields[table.id] = visible
        _, by_field = _hidden_by_field(db, table, user)
        entries.append(
            build_table_dictionary(
                table,
                visible,
                table_names=table_names,
                field_names=_field_names(visible),
                hidden_by_field=by_field,
                include_internal=include_internal,
                group_name=groups.get(table.group_id or -1, ""),
                owner_name=_table_owner_name(db, table),
                views=_views_brief(table),
                row_rules_active=row_rules_active(db, table),
                change_log=_change_log(db, table.id),
            )
        )
    return build_document(
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        schema_hash=compute_schema_hash(tables, hash_fields),
        include_internal=include_internal,
        tables=entries,
    )


def _render(document: Any, fmt: str, *, template: str | None) -> bytes:
    """按格式渲染（docx / pdf 走共享渲染层，见 ADR 0188 D10）."""
    if fmt == "md":
        return render_markdown(document).encode("utf-8")
    if fmt == "xlsx":
        return render_xlsx(document)
    if fmt == "json":
        import json

        return json.dumps(document_to_dict(document), ensure_ascii=False, indent=2, default=str).encode("utf-8")
    # docx / pdf：先出 Markdown，再交给共享渲染层
    from cndb.plugins.tables.services.dictionary.export_render import render_office

    return render_office(render_markdown(document), fmt, title=document.title, template=template)


def _respond(content: bytes, fmt: str, filename: str) -> Response:
    """构造下载响应（中文文件名走 RFC 5987，与行导出口径一致）."""
    from urllib.parse import quote

    media_type, _ = _FORMATS[fmt]
    ascii_fallback = "".join(c if ord(c) < 128 else "_" for c in filename)
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(filename)}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": disposition})


def _record_export(
    db: Session,
    *,
    user: User,
    workspace_id: int,
    fmt: str,
    table_count: int,
    field_count: int,
    include_internal: bool,
    target_id: int | None,
) -> None:
    """写导出事件（C9）：只记定位与计数，不落字段说明 / 示例值（H38 口径）."""
    record_event(
        db,
        "table.dictionary_export",
        summary=f"导出数据字典（{fmt}，{table_count} 张表 / {field_count} 个字段）",
        target_type=TARGET_TABLE,
        target_id=target_id,
        workspace_id=workspace_id,
        actor_id=user.id,
        actor_name=user.username,
        detail={
            "format": fmt,
            "table_count": table_count,
            "field_count": field_count,
            "include_internal": include_internal,
        },
    )


def _workspace_or_404(db: Session, workspace_id: int, user: User) -> Workspace:
    """取工作区并校验数据面读权限（经 resolve_capabilities，H64 单一判定）."""
    from cndb.plugins.workspaces.permissions import resolve_capabilities

    ws = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if ws is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    caps = resolve_capabilities(user, ws, db)
    if caps.data_role is None:
        raise HTTPException(status_code=404, detail="工作区不存在")
    return ws


@router.get("/dictionary")
def export_workspace_dictionary(
    workspace_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    format: str = "md",
    table_ids: str | None = None,
    include_internal: bool = False,
    template: str | None = None,
) -> Response:
    """工作区合订数据字典（C5）：缺省导出全部未删表，``table_ids`` 可指定子集.

    不可读的表**静默跳过**：既不因为一张表无权限让整份失败，也不暴露「存在但不可读」。
    """
    fmt = _normalize_format(format)
    workspace = _workspace_or_404(db, workspace_id, current_user)

    query = db.query(DataTable).filter(
        DataTable.workspace_id == workspace_id,
        DataTable.trashed == False,  # noqa: E712
    )
    wanted: list[int] = []
    if table_ids:
        for chunk in table_ids.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                wanted.append(int(chunk))
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f"table_ids 含非整数: {chunk}") from exc
        if not wanted:
            raise HTTPException(status_code=400, detail="table_ids 不能为空")
        query = query.filter(DataTable.id.in_(wanted))

    candidates = query.order_by(DataTable.order, DataTable.id).all()
    readable: list[DataTable] = []
    for table in candidates:
        try:
            get_table_or_404(table.id, workspace_id, db, user=current_user, action=TableAction.READ)
        except HTTPException:
            logger.debug("字典导出跳过无读权限的表 %s", table.id)
            continue
        readable.append(table)

    if not readable:
        raise HTTPException(status_code=404, detail="没有可导出的数据表（无读权限或工作区无表）")

    document = _build_for_tables(db, workspace, readable, current_user, include_internal=include_internal)
    content = _render(document, fmt, template=template)
    name = f"{workspace.name}-数据字典-{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}"
    _record_export(
        db,
        user=current_user,
        workspace_id=workspace_id,
        fmt=fmt,
        table_count=len(readable),
        field_count=document.field_count,
        include_internal=include_internal,
        target_id=None,
    )
    return _respond(content, fmt, name + _FORMATS[fmt][1])


@router.get("/{table_id}/dictionary")
def export_table_dictionary(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    format: str = "md",
    include_internal: bool = False,
    template: str | None = None,
) -> Response:
    """单表字段字典（C1）：五种格式，只读，不含行数据."""
    fmt = _normalize_format(format)
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    workspace = _workspace_or_404(db, workspace_id, current_user)

    document = _build_for_tables(db, workspace, [table], current_user, include_internal=include_internal)
    content = _render(document, fmt, template=template)
    filename = _build_export_filename(workspace.name, table.name, "数据字典", fmt)
    _record_export(
        db,
        user=current_user,
        workspace_id=workspace_id,
        fmt=fmt,
        table_count=1,
        field_count=document.field_count,
        include_internal=include_internal,
        target_id=table.id,
    )
    return _respond(content, fmt, filename)


@router.get("/{table_id}/dictionary/score")
def get_dictionary_score(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """标准符合度指标（C4）：六项覆盖率 + 缺口字段名."""
    table = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    visible = _visible_fields(db, table, current_user)
    score = compute_score(visible)
    score["table_id"] = table.id
    score["table_name"] = table.name
    score["schema_hash"] = compute_schema_hash([table], {table.id: visible})
    return score


__all__ = ["router"]
