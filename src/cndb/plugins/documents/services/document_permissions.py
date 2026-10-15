"""文档级权限（协作者白名单）—— 让**未发布草稿**只对指定同事开放.

**为什么需要**：可见性策略把草稿限制为「创建者 + 工作区所有者」可见，这是"不互相偷看草稿"的正确默认，
但团队协作常需要"我这份草稿先拉你一起写/先给你看"。于是需要**显式授权**的中间档：
既不把草稿对全工作区开放，也不让协作只能靠"先发布"。

**数据结构**：复用既有表 ``documents_permission``（``(document_id, user_id) -> role``），
该表此前只在彻底删除时被清理、没有任何 API 与判定，属于未完成的半成品；这里补全。

**语义**：

============  ==================================================================
viewer        可读该文档（含草稿/归档）；写入仍走工作区策略（viewer → 修改申请）
editor        可读 + 可**直接编辑**该文档内容；仅对**未发布**文档生效
              （已发布文档仍遵循工作区 allow_edit / 修改申请策略，避免绕过审核流程）
============  ==================================================================

**授权者**：文档创建者、工作区 OWNER、超级用户（避免"被授权者再转发"造成权限扩散）。
**被授权者**：必须是该工作区成员；创建者/所有者本身无需授权，重复授权会被拒绝。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, NotFoundError, PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DOC_STATUS_PUBLISHED, Document, DocumentPermission
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

# 可授予的角色（owner 不通过本接口授予：创建者/工作区所有者天然可见）
PERMISSION_VIEWER = "viewer"
PERMISSION_EDITOR = "editor"
GRANTABLE_ROLES = (PERMISSION_VIEWER, PERMISSION_EDITOR)
# 视为"可编辑"的角色（含历史/手工写入的 owner）
EDITOR_EQUIVALENT_ROLES = (PERMISSION_EDITOR, "owner")


def _workspace(db: Session, workspace_id: int) -> Workspace:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    return ws


def can_manage(db: Session, doc: Document, user: User) -> bool:
    """是否有权管理该文档的协作者名单（创建者 / 工作区 OWNER / 超管）."""
    if getattr(user, "is_superuser", False):
        return True
    if doc.created_by_id is not None and doc.created_by_id == user.id:
        return True
    role = get_member_role(user, _workspace(db, doc.workspace_id), db)
    return role == WorkspaceRole.OWNER


def require_can_manage(db: Session, doc: Document, user: User) -> None:
    if not can_manage(db, doc, user):
        raise PermissionDeniedError("仅文档创建者或工作区所有者可管理协作者")


def role_for(db: Session, document_id: int, user_id: int) -> str | None:
    """该用户在此文档上的显式授权角色（无授权返回 None）."""
    row = (
        db.query(DocumentPermission)
        .filter(DocumentPermission.document_id == document_id, DocumentPermission.user_id == user_id)
        .first()
    )
    return row.role if row is not None else None


def is_editor_granted(db: Session, document_id: int, user_id: int) -> bool:
    """是否被授予"可编辑"（且文档**未发布**，避免绕过发布/审核流程）."""
    doc = db.get(Document, document_id)
    if doc is None or doc.status == DOC_STATUS_PUBLISHED:
        return False
    return role_for(db, document_id, user_id) in EDITOR_EQUIVALENT_ROLES


def granted_user_ids(db: Session, document_id: int) -> set[int]:
    rows = db.query(DocumentPermission.user_id).filter(DocumentPermission.document_id == document_id).all()
    return {int(r[0]) for r in rows}


def list_permissions(db: Session, doc: Document) -> list[dict[str, Any]]:
    """协作者名单（带用户名/昵称与角色）."""
    rows = (
        db.query(DocumentPermission, User)
        .outerjoin(User, User.id == DocumentPermission.user_id)
        .filter(DocumentPermission.document_id == doc.id)
        .order_by(DocumentPermission.user_id)
        .all()
    )
    return [
        {
            "document_id": perm.document_id,
            "user_id": perm.user_id,
            "role": perm.role,
            "username": user.username if user is not None else None,
            "nickname": user.nickname if user is not None else None,
        }
        for perm, user in rows
    ]


def upsert_permission(
    db: Session,
    doc: Document,
    *,
    operator: User,
    target_user_id: int,
    role: str,
) -> dict[str, Any]:
    """授予/更新某成员在本草稿上的权限（viewer/editor）."""
    require_can_manage(db, doc, operator)
    if role not in GRANTABLE_ROLES:
        raise BadRequestError(f"不支持的角色: {role}（可选 {'/'.join(GRANTABLE_ROLES)}）")
    if target_user_id == operator.id:
        raise BadRequestError("无需给自己授权：你是该文档的创建者/管理者")
    if doc.created_by_id is not None and target_user_id == doc.created_by_id:
        raise BadRequestError("文档创建者本身就可见，无需授权")

    target = db.get(User, target_user_id)
    if target is None:
        raise NotFoundError("用户不存在")
    if get_member_role(target, _workspace(db, doc.workspace_id), db) is None:
        raise BadRequestError("只能把文档授权给本工作区成员")

    row = (
        db.query(DocumentPermission)
        .filter(DocumentPermission.document_id == doc.id, DocumentPermission.user_id == target_user_id)
        .first()
    )
    if row is None:
        row = DocumentPermission(document_id=doc.id, user_id=target_user_id, role=role)
        db.add(row)
    else:
        row.role = role
    db.commit()
    return {
        "document_id": doc.id,
        "user_id": target_user_id,
        "role": role,
        "username": target.username,
        "nickname": target.nickname,
    }


def remove_permission(db: Session, doc: Document, *, operator: User, target_user_id: int) -> bool:
    """撤销授权（幂等：不存在返回 False）."""
    require_can_manage(db, doc, operator)
    row = (
        db.query(DocumentPermission)
        .filter(DocumentPermission.document_id == doc.id, DocumentPermission.user_id == target_user_id)
        .first()
    )
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


__all__ = [
    "EDITOR_EQUIVALENT_ROLES",
    "GRANTABLE_ROLES",
    "PERMISSION_EDITOR",
    "PERMISSION_VIEWER",
    "can_manage",
    "granted_user_ids",
    "is_editor_granted",
    "list_permissions",
    "remove_permission",
    "require_can_manage",
    "role_for",
    "upsert_permission",
]
