"""视图管理路由."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.api.deps import get_current_user
from cndb.core.database import get_db
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import AuditLog, DataField, DataTable, DataView, ViewVisibility, scope_key_for
from cndb.plugins.tables.schemas import (
    ShareableMemberOut,
    ViewCreate,
    ViewMemberGrant,
    ViewMemberOut,
    ViewResponse,
    ViewUpdate,
    ViewVisibilityUpdate,
)
from cndb.plugins.tables.services.core.access import TableAction, check_action, get_table_or_404
from cndb.plugins.tables.services.core.view_access import (
    ViewAction,
    assert_can_change_visibility,
    get_view_or_404,
    grantee_counts,
    grants_for_user,
    is_table_admin,
    list_view_grants,
    replace_view_grants,
    require_can_publish_to_table,
    resolve_view_action,
    revoke_view_grant,
    role_codes_for_workspace,
    set_view_grant,
    shareable_members,
    view_visibility_filter,
)

router = APIRouter(prefix="/{workspace_id}/tables/{table_id}/views", tags=["views"])

#: 非 ``shared`` 档视图不允许改共享名单（名单在其它档位是惰性的，改它没有意义）
_SHARED_ONLY_DETAIL = "仅「指定成员」档视图可设置共享名单"


def _validate_view_fields(vc: ViewCreate, table_id: int, db: Session) -> tuple[bool, str | None]:
    """校验视图配置里引用的所有 field_name 是否在目标表存在."""
    valid_fields = {f.name for f in db.query(DataField).filter(DataField.table_id == table_id).all()}
    for f in vc.filters or []:
        if f.get("field_name") not in valid_fields:
            return False, f"filter field_name='{f.get('field_name')}' 不存在"
    for s in vc.sortings or []:
        if s.get("field_name") not in valid_fields:
            return False, f"sorting field_name='{s.get('field_name')}' 不存在"
    vo = vc.view_options or {}
    for opt_key in (
        "group_field",
        "start_field",
        "title_field",
        # Gantt 甘特图（v1 未校验，此次补齐）
        "start_date_field",
        "end_date_field",
        "actual_end_field",
        "progress_field",
        "assignee_field",
        # WBS 工作分解结构
        "parent_field",
        "status_field",
        # Matrix 矩阵视图（纵横轴字段）
        "row_field",
        "column_field",
        # Chart 图表视图（维度/度量/散点双轴字段；group_field 已在上方）
        "dimension_field",
        "measure_field",
        "x_field",
        "y_field",
    ):
        opt_val = vo.get(opt_key)
        if opt_val and opt_val not in valid_fields:
            return False, f"view_options.{opt_key}='{opt_val}' 不存在"
    # chart 多图形态：charts[] 逐条目校验字段引用（detail 定位到 charts[i].<key>）
    charts = vo.get("charts")
    if isinstance(charts, list):
        for i, entry in enumerate(charts):
            if not isinstance(entry, dict):
                return False, f"view_options.charts[{i}] 不是对象"
            for opt_key in ("dimension_field", "measure_field", "x_field", "y_field", "group_field"):
                opt_val = entry.get(opt_key)
                if opt_val and opt_val not in valid_fields:
                    return False, f"view_options.charts[{i}].{opt_key}='{opt_val}' 不存在"
    return True, None


def _scoped_name_conflict(db: Session, table_id: int, scope_key: int, name: str) -> bool:
    """同名视图是否已存在于**同一命名空间**（ADR 0003 缺陷 #7 的修复点）."""
    return (
        db.query(DataView)
        .filter(DataView.table_id == table_id, DataView.scope_key == scope_key, DataView.name == name)
        .first()
        is not None
    )


def _write_view_audit(
    db: Session,
    table_id: int,
    action: str,
    actor_id: int,
    detail: dict[str, Any],
) -> None:
    """视图权限类变更写一条审计（与 ``members.py`` 同款，随主事务一起提交）.

    审计动作词：``view_visibility`` / ``view_grant`` / ``view_revoke``。
    """
    db.add(AuditLog(table_id=table_id, action=action, actor_id=actor_id, detail=detail))


def _view_payloads(
    db: Session,
    table: DataTable,
    user: User,
    views: list[DataView],
) -> list[dict[str, Any]]:
    """把 ``DataView`` 列表序列化为带**能力位**的响应体（I5：能力判定只此一处）.

    批量场景下所有依赖都一次性预取（工作区角色 / 是否管理视角 / 本人授权名单 /
    授权人数），因此查询次数与视图数量无关 —— 不再由前端用 ``visibility`` +
    ``owner_id`` 各自推断"能不能改/能不能管理"，避免前后端口径漂移。
    """
    view_ids = [int(v.id) for v in views]
    codes = role_codes_for_workspace(db, table.workspace_id, user)
    admin = is_table_admin(db, table, user)
    granted = grants_for_user(db, view_ids, user.id, codes)
    counts = grantee_counts(db, view_ids)

    out: list[dict[str, Any]] = []
    for v in views:
        data = ViewResponse.model_validate(v).model_dump()
        grant_role = granted.get(int(v.id))
        data["can_edit"] = resolve_view_action(
            db, table, v, user, ViewAction.VIEW_EDIT, grant_role=grant_role, is_admin=admin
        )
        data["can_manage"] = resolve_view_action(
            db, table, v, user, ViewAction.VIEW_MANAGE, grant_role=grant_role, is_admin=admin
        )
        data["grantee_count"] = counts.get(int(v.id), 0)
        out.append(data)
    return out


def _require_shared(view: DataView) -> None:
    if view.visibility != ViewVisibility.SHARED:
        raise HTTPException(status_code=400, detail=_SHARED_ONLY_DETAIL)


def _resolve_target_user(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return target


def _create_view_obj(
    db: Session,
    table_id: int,
    payload: ViewCreate,
    owner_id: int,
) -> DataView:
    """创建单个 DataView 对象（不含 commit）.

    ``owner_id`` 恒为创建者（I4：授权不转移归属）；可见性由 ``payload.visibility``
    决定（新建默认 ``private``），命名空间由 :func:`scope_key_for` 推导。
    档位合法性（``table`` 档需表 ``EDIT_VIEWS``、``is_default`` 仅限 ``table`` 档）
    由调用方在创建前校验。
    """
    if payload.is_default:
        db.query(DataView).filter(DataView.table_id == table_id).update({"is_default": False})
    # 未显式指定顺序时追加到末尾（现有最大 order + 1），避免新视图排在最前
    if payload.order is None:
        max_order = db.query(func.max(DataView.order)).filter(DataView.table_id == table_id).scalar()
        order = (max_order or 0) + 1
    else:
        order = payload.order
    return DataView(
        table_id=table_id,
        owner_id=owner_id,
        name=payload.name,
        view_type=payload.view_type,
        filter_type=payload.filter_type,
        filters=payload.filters,
        sortings=payload.sortings,
        field_options=payload.field_options,
        field_order=payload.field_order,
        view_options=payload.view_options,
        is_default=payload.is_default,
        order=order,
        visibility=payload.visibility,
        scope_key=scope_key_for(payload.visibility, owner_id),
    )


@router.post("", response_model=ViewResponse, status_code=status.HTTP_201_CREATED)
def create_view(
    workspace_id: int,
    table_id: int,
    payload: ViewCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> DataView:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    # 定档校验：table 档（表内所有人可见）需表 EDIT_VIEWS（D4）；
    # shared/private 档只需本人是创建者（由 VIEW_MANAGE 语义保证，创建时天然满足）
    visibility = payload.visibility
    require_can_publish_to_table(db, dt, current_user, visibility)
    # is_default 是**表级**标记（会清掉同表其它默认视图）：只有 table 档视图才代表
    # "全表成员的落地页"，private/shared 视图持有它会抢占他人视角（ADR 0003 §2）
    if payload.is_default and visibility != ViewVisibility.TABLE:
        raise HTTPException(status_code=400, detail="仅表内可见视图可设为默认视图")

    # 同表视图名唯一 —— 按命名空间判定（私有视图只在本人空间内唯一，修缺陷 #7）
    scope_key = scope_key_for(visibility, current_user.id)
    if _scoped_name_conflict(db, table_id, scope_key, payload.name):
        raise HTTPException(status_code=400, detail="视图名已存在")

    ok, err = _validate_view_fields(payload, table_id, db)
    if not ok:
        raise HTTPException(status_code=400, detail=f"视图字段校验失败: {err}")

    dv = _create_view_obj(db, table_id, payload, owner_id=current_user.id)
    db.add(dv)
    db.commit()
    db.refresh(dv)
    return _view_payloads(db, dt, current_user, [dv])[0]


@router.post("/import", response_model=list[ViewResponse])
def import_views(
    workspace_id: int,
    table_id: int,
    payload: list[ViewCreate],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[DataView]:
    """批量导入视图配置（上传 JSON 数组）.

    同名视图自动跳过，字段引用不存在时跳过并返回 warnings.
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    # 已占用的命名空间键（scope_key, name）—— 私有视图只与本人空间的同名冲突（缺陷 #7）
    existing_keys = {
        (int(r[0]), str(r[1]))
        for r in db.query(DataView.scope_key, DataView.name).filter(DataView.table_id == table_id).all()
    }
    created: list[DataView] = []
    skipped: list[str] = []

    # 导入者无 EDIT_VIEWS → 只能落 private 档（与 create_view 的 D4 门槛一致）
    can_edit_views = check_action(db, dt, current_user, TableAction.EDIT_VIEWS)

    for vc in payload:
        visibility = vc.visibility
        if visibility == ViewVisibility.TABLE and not can_edit_views:
            visibility = ViewVisibility.PRIVATE
        # is_default 是表级标记，仅 table 档视图可持有（个人视图会抢占全表落地页）
        is_default = vc.is_default and visibility == ViewVisibility.TABLE
        if visibility != vc.visibility or is_default != vc.is_default:
            vc = vc.model_copy(update={"visibility": visibility, "is_default": is_default})
        scope_key = scope_key_for(visibility, current_user.id)
        if (scope_key, vc.name) in existing_keys:
            skipped.append(f"已存在: {vc.name}")
            continue
        ok, err = _validate_view_fields(vc, table_id, db)
        if not ok:
            skipped.append(f"跳过 {vc.name}: {err}")
            continue
        dv = _create_view_obj(db, table_id, vc, owner_id=current_user.id)
        db.add(dv)
        created.append(dv)
        existing_keys.add((scope_key, vc.name))

    db.commit()
    for dv in created:
        db.refresh(dv)
    if skipped:
        import json as _json

        print(
            f"[视图导入] table_id={table_id}: {len(created)} 成功, {len(skipped)} 跳过: {_json.dumps(skipped, ensure_ascii=False)}"
        )
    return created


@router.get("", response_model=list[ViewResponse])
def list_views(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 可见性统一由 view_access 判定：table 档全表可见 + shared 档名单内 + private 档仅本人
    views = (
        db.query(DataView)
        .filter(DataView.table_id == table_id, view_visibility_filter(db, dt, current_user))
        .order_by(DataView.order, DataView.id)
        .all()
    )
    return _view_payloads(db, dt, current_user, list(views))


@router.get("/export", response_model=list[ViewCreate])
def export_views(
    workspace_id: int,
    table_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    ids: Annotated[list[int] | None, Query()] = None,
) -> list[dict[str, object]]:
    """导出视图配置（返回 ViewCreate 兼容的 JSON 数组，不含 id / 时间戳等内部元数据）.

    - 不传 ids → 导出该表全部视图
    - 传 ids → 仅导出指定视图（不存在的 id 自动跳过）
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)

    q = db.query(DataView).filter(
        DataView.table_id == table_id,
        # 可见性：与 list_views 一致 —— table 档 + shared 名单内 + 本人 private
        view_visibility_filter(db, dt, current_user),
    )
    if ids:
        q = q.filter(DataView.id.in_(ids))
    views = q.order_by(DataView.order, DataView.id).all()

    stripped: list[dict[str, object]] = []
    keep_fields = {
        "name",
        "view_type",
        "filter_type",
        "filters",
        "sortings",
        "field_options",
        "field_order",
        "view_options",
        "is_default",
        "visibility",
        "order",
    }
    for v in views:
        raw = DataView.__table__.columns.keys()
        obj = {k: getattr(v, k) for k in raw if k in keep_fields}
        stripped.append(obj)
    return stripped


@router.get("/{view_id}", response_model=ViewResponse)
def get_view(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # table/shared 档仅需表 READ 即可查看（此前误要求 EDIT_VIEWS，导致"列表可见但点开 403"）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_READ)
    return _view_payloads(db, dt, current_user, [dv])[0]


@router.patch("/{view_id}", response_model=ViewResponse)
def update_view(
    workspace_id: int,
    table_id: int,
    view_id: int,
    payload: ViewUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 改配置需 VIEW_EDIT：本人视图放行；table 档需表 EDIT_VIEWS（I7）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_EDIT)

    # is_default 是**表级**标记（会清掉同表其它默认视图）：只有 table 档视图代表
    # "全表成员的落地页"，private/shared 档持有它会让其他成员进表看到空白（ADR 0003 §2）
    if payload.is_default and dv.visibility != ViewVisibility.TABLE:
        raise HTTPException(status_code=400, detail="仅表内可见视图可设为默认视图")

    # 如果标记为 default，先把同表其他视图的 default 清掉
    if payload.is_default:
        db.query(DataView).filter(DataView.table_id == table_id).update({"is_default": False})

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(dv, key, value)
    db.commit()
    db.refresh(dv)
    return _view_payloads(db, dt, current_user, [dv])[0]


@router.post("/{view_id}/visibility", response_model=ViewResponse)
def set_view_visibility(
    workspace_id: int,
    table_id: int,
    view_id: int,
    payload: ViewVisibilityUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """切换视图可见性档位，可一并设置共享名单（ADR 0003 §6）.

    - 需 ``VIEW_MANAGE``：创建者本人，或非私有档下的表内管理视角
    - 开放为 ``table`` 档（表内所有人可见）额外需表 ``EDIT_VIEWS``（决策 D4）
    - **每张表至少保留一个 ``table`` 档视图**：把最后一个转出 → 400（决策 D1）
    - 同名冲突按**目标档位**的命名空间判定（private 与共享空间互不干扰）
    - ``members`` 仅在目标档位为 ``shared`` 时接受，**全量替换**共享名单；缺省不动名单
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)

    new_visibility = payload.visibility
    if payload.members is not None and new_visibility != ViewVisibility.SHARED:
        raise HTTPException(status_code=400, detail=_SHARED_ONLY_DETAIL)

    require_can_publish_to_table(db, dt, current_user, new_visibility)
    assert_can_change_visibility(db, dt, dv, new_visibility)

    new_scope = scope_key_for(new_visibility, dv.owner_id)
    if new_scope != dv.scope_key and _scoped_name_conflict(db, table_id, new_scope, dv.name):
        raise HTTPException(status_code=400, detail="目标可见范围内的同名视图已存在")

    # 名单先校验后落库（replace_view_grants 内部逐条 assert，任一不过即 422 且不写库）
    if payload.members is not None:
        replace_view_grants(db, dt, dv, current_user, payload.members)

    previous = dv.visibility
    if new_visibility != ViewVisibility.TABLE and dv.is_default:
        # 表级默认位只属于 table 档视图：转出时先摘掉，避免"默认视图他人看不见"
        dv.is_default = False
    dv.visibility = new_visibility
    dv.scope_key = new_scope
    if previous != new_visibility:
        _write_view_audit(
            db,
            table_id,
            "view_visibility",
            current_user.id,
            {
                "view_id": int(dv.id),
                "name": dv.name,
                "from": str(previous),
                "to": str(new_visibility),
                "members": len(payload.members) if payload.members is not None else None,
            },
        )
    db.commit()
    db.refresh(dv)
    return _view_payloads(db, dt, current_user, [dv])[0]


# ── 共享名单（``shared`` 档）────────────────────────────


@router.get("/{view_id}/members", response_model=list[ViewMemberOut])
def list_view_members(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    """列出该视图的共享名单（需 ``VIEW_MANAGE``）.

    只有名单可以被查看，不返回任何行数据；不在名单里的成员看不到名单本身，
    与 D2「私有档对非创建者一律 404」不冲突（本端点自身仍先过 ``VIEW_MANAGE``）。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)
    return list_view_grants(db, dt, dv)


@router.put("/{view_id}/members/{user_id}", response_model=ViewMemberOut)
def set_view_member(
    workspace_id: int,
    table_id: int,
    view_id: int,
    user_id: int,
    payload: ViewMemberGrant,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """新增 / 修改名单内某成员的授权角色（``viewer`` / ``editor``）.

    仅 ``shared`` 档视图可改名单 —— 其余档位名单是惰性的（保留但失效），改它没有意义。
    授权对象必须落在**数据表范围内**（本工作区成员 ∧ 该表 ``READ``；``editor`` 还需
    该表 ``EDIT_VIEWS``），否则 422（ADR 0003 §4）。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)
    _require_shared(dv)

    target = _resolve_target_user(db, user_id)
    set_view_grant(db, dt, dv, current_user, target, payload.role)
    _write_view_audit(
        db,
        table_id,
        "view_grant",
        current_user.id,
        {"view_id": int(dv.id), "name": dv.name, "user_id": int(target.id), "role": str(payload.role)},
    )
    db.commit()
    row = next((r for r in list_view_grants(db, dt, dv) if int(r["user_id"]) == int(target.id)), None)
    if row is None:  # pragma: no cover - 刚写入即存在，仅防御
        raise HTTPException(status_code=500, detail="授权写入后未读取到名单条目")
    return row


@router.delete("/{view_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_view_member(
    workspace_id: int,
    table_id: int,
    view_id: int,
    user_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    """从共享名单收回某成员的授权（需 ``VIEW_MANAGE``，仅 ``shared`` 档）.

    收回后若该成员已不再拥有任何授权，视图对其即刻恢复"不存在"（404），无需回填清理。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)
    _require_shared(dv)

    if not revoke_view_grant(db, dv, user_id):
        raise HTTPException(status_code=404, detail="该成员不在共享名单中")
    _write_view_audit(
        db,
        table_id,
        "view_revoke",
        current_user.id,
        {"view_id": int(dv.id), "name": dv.name, "user_id": int(user_id)},
    )
    db.commit()


@router.get("/{view_id}/shareable-members", response_model=list[ShareableMemberOut])
def list_shareable_members(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    """可被授权者列表（共享选择器数据源，需 ``VIEW_MANAGE``）.

    缺陷补丁：``GET /{wid}/tables/{tid}/members`` 需 ``_require_table_admin``，普通
    viewer 拿不到成员列表 → 共享选择器做不出来。本端点只返回"谁可以被授权"
    （本工作区成员 ∧ 该表 ``READ``，含是否可给 ``editor``），不暴露任何视图。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)
    return shareable_members(db, dt, current_user, dv)


@router.delete("/{view_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_view(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 删除需 VIEW_MANAGE：本人个人视图放行；公共视图需表 EDIT_VIEWS（I7）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_MANAGE)

    was_default = dv.is_default
    db.delete(dv)
    db.flush()
    if was_default:
        # 删除的是默认视图 → 把默认标记转移给同表剩余视图（按 order/id 取第一个），避免出现"无默认视图".
        # 候选必须是 table 档视图：private/shared 档对全表不可见，让它持有 is_default 会让其他成员进表看到空白（缺陷 ⑥）.
        next_default = (
            db.query(DataView)
            .filter(DataView.table_id == table_id, DataView.visibility == ViewVisibility.TABLE)
            .order_by(DataView.order, DataView.id)
            .first()
        )
        if next_default is not None:
            next_default.is_default = True
    db.commit()


@router.post("/reorder", response_model=list[ViewResponse])
def reorder_views(
    workspace_id: int,
    table_id: int,
    view_ids: list[int],
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[dict[str, Any]]:
    """批量调整视图顺序（按传入顺序赋值 order 字段）.

    只重排**当前用户可改**的视图子集：他人视图（本就不可见）与仅可读的 ``table`` 档
    视图一律跳过；响应也只返回当前用户**可见**的视图。修复：原实现返回该表**全部**
    视图，等于借重排接口枚举他人视图的完整配置（缺陷 ②）。
    """
    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.EDIT_VIEWS)

    requested = (
        db.query(DataView)
        .filter(
            DataView.table_id == table_id,
            DataView.id.in_(view_ids),
        )
        .all()
    )
    view_map = {v.id: v for v in requested}

    idx = 0
    for vid in view_ids:
        view = view_map.get(vid)
        if view is None:
            continue  # 不存在的 id / 不属于本表 → 跳过（保持既有容错语义）
        if not resolve_view_action(db, dt, view, current_user, ViewAction.VIEW_EDIT):
            continue  # 他人视图 / 仅可读 → 不参与重排，也不出现在响应里
        view.order = idx
        idx += 1

    db.commit()
    visible = (
        db.query(DataView)
        .filter(DataView.table_id == table_id, view_visibility_filter(db, dt, current_user))
        .order_by(DataView.order, DataView.id)
        .all()
    )
    return _view_payloads(db, dt, current_user, list(visible))


# ── 视图驱动的行查询 ──────────────────────────────────


@router.get("/{view_id}/rows")
def get_view_rows(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=100, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    """按视图的 filters + sortings 查询行."""
    from cndb.plugins.tables.services.core import records as rec

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 补 VIEW_READ 校验：此前只校验表 READ，凭他人个人视图 id 即可按其筛选规则取数（缺陷 ①）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_READ)

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=dv.filters or None,
        filter_logic=dv.filter_type,
        sorts=dv.sortings or None,
        limit=limit,
        offset=offset,
        db=db,
        user=current_user,
    )
    return {"rows": rows, "total": total, "view_id": view_id}


@router.get("/{view_id}/kanban")
def get_view_kanban(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    limit: int = Query(default=500, ge=1, le=10000),
) -> dict[str, object]:
    """看板视图：按 view_options.group_field 分组返回行.

    view_options 支持：
    - group_field (str, 必填): 分组字段名（DataField.name）
    - group_order (list[str], 可选): 显式分组顺序，未在列表里的分组追加在末尾
    - ungrouped_label (str, 可选): 空值分组的显示名，默认 "未分组"
    """
    from collections import defaultdict

    from cndb.plugins.tables.services.core import records as rec

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 补 VIEW_READ 校验（缺陷 ①）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_READ)

    opts = dv.view_options or {}
    group_field = opts.get("group_field")
    if not group_field:
        raise HTTPException(status_code=400, detail="看板视图需配置 group_field")

    group_order: list[str] = opts.get("group_order") or []
    ungrouped_label: str = opts.get("ungrouped_label") or "未分组"

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=dv.filters or None,
        filter_logic=dv.filter_type,
        sorts=dv.sortings or None,
        limit=limit,
        db=db,
        user=current_user,
    )
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        raw_val = row.get(group_field)
        key = str(raw_val) if raw_val not in (None, "") else ungrouped_label
        grouped[key].append(row)

    # 按 group_order 排序分组，未列出的追加在末尾
    if group_order:
        ordered_keys = [k for k in group_order if k in grouped]
        extra_keys = [k for k in grouped if k not in group_order]
        # ungrouped_label 放最后（如果不在 group_order 里）
        if ungrouped_label in extra_keys:
            extra_keys.remove(ungrouped_label)
            extra_keys.append(ungrouped_label)
        ordered_keys.extend(extra_keys)
        grouped = {k: grouped[k] for k in ordered_keys}

    return {
        "columns": grouped,
        "total": total,
        "group_field": group_field,
        "group_order": list(grouped.keys()),
        "ungrouped_label": ungrouped_label,
    }


@router.get("/{view_id}/calendar")
def get_view_calendar(
    workspace_id: int,
    table_id: int,
    view_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    start: str | None = Query(default=None, description="ISO 日期起始 (YYYY-MM-DD)"),
    end: str | None = Query(default=None, description="ISO 日期结束"),
    limit: int = Query(default=500, ge=1, le=10000),
) -> dict[str, object]:
    """日历视图：按日期字段过滤并返回行列表."""
    from cndb.plugins.tables.services.core import records as rec

    dt = get_table_or_404(table_id, workspace_id, db, user=current_user, action=TableAction.READ)
    # 补 VIEW_READ 校验（缺陷 ①）
    dv = get_view_or_404(db, dt, current_user, view_id, ViewAction.VIEW_READ)

    start_field = dv.view_options.get("start_field") if dv.view_options else None
    if not start_field:
        raise HTTPException(status_code=400, detail="日历视图需配置 start_field")

    filters: list[dict[str, object]] = list(dv.filters or [])
    if start:
        filters.append({"field_name": start_field, "op": ">=", "value": start})
    if end:
        filters.append({"field_name": start_field, "op": "<=", "value": end})

    sorts = list(dv.sortings or [])
    sorts.append({"field_name": start_field, "direction": "asc"})

    rows, total = rec.list_rows(
        db.get_bind(),
        dt,
        filters=filters,
        filter_logic=dv.filter_type,
        sorts=sorts,
        limit=limit,
        db=db,
        user=current_user,
    )
    return {"rows": rows, "total": total, "start_field": start_field}
