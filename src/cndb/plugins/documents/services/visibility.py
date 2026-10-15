"""文档可见性策略 —— 草稿/未发布内容只对创建者与工作区管理员可见.

**背景（线上问题）**：``Document.status ∈ {draft, published, archived}``（默认 ``draft``），
但该状态此前只用于展示与筛选，**从未参与任何读取过滤**。于是：

- 列表 / 目录树 / 全文搜索 / 详情 / 版本记录 / 差异 / 导出 / 反链都会命中他人的草稿；
- 分享链接可以对草稿创建，等于把未发布内容直接放给外部；
- 实时协作的锁与在线状态也会把"某人正在编辑某草稿"暴露给所有人。

本模块把可见性收敛为**一条可复用的规则**，并提供三种入口（SQL 条件、单文档判定、
内存过滤），供各读取端点复用，避免每个端点各写一遍导致遗漏：

============  =====================================================
status        谁可见
============  =====================================================
published     该工作区的**全部成员**（成员身份已在路由层校验）
draft         仅**创建者**本人 + 工作区 **OWNER** / 超级用户
archived      同 draft（已下线内容不再向普通成员扩散）
============  =====================================================

设计取舍：
- 结构文件夹不单独设权限：只要其**任一可见后代**可见，就把祖先文件夹一并展示，
  否则目录树会出现"孤儿节点"（树是按 parent_id 组装的）。
- 非授权访问一律按 **404 处理**（而不是 403）：不泄露"存在这样一份草稿"。
- 管理员判定：``WorkspaceRole.OWNER`` 或 ``User.is_superuser``；
  工作区管理员需要能审阅/清理他人草稿，故纳入可见范围。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from sqlalchemy import ColumnElement, or_, select
from sqlalchemy.orm import Session

from cndb.core.errors import NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import DOC_STATUS_PUBLISHED, Document, DocumentPermission
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

# 全员可见的状态（其余状态仅创建者/管理员可见）
PUBLIC_STATUSES: tuple[str, ...] = (DOC_STATUS_PUBLISHED,)


def is_document_admin(db: Session, workspace_id: int, user: User | None) -> bool:
    """是否"能看到全部状态"的管理者：超级用户或工作区 OWNER."""
    if user is None:  # pragma: no cover - 路由层已保证 user 非空
        return False
    if getattr(user, "is_superuser", False):
        return True
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id)
        .first()
    )
    return member is not None and member.role == WorkspaceRole.OWNER


def visible_condition(
    db: Session,
    workspace_id: int,
    user: User | None,
    *,
    is_admin: bool | None = None,
) -> ColumnElement[bool]:
    """SQL 层可见性条件（与其它筛选条件 AND 使用）.

    管理员返回恒真条件，避免在查询里再拼 OR 分支。
    """
    admin = is_document_admin(db, workspace_id, user) if is_admin is None else is_admin
    if admin or user is None:
        return Document.workspace_id == workspace_id  # 恒真（调用方已按工作区过滤）
    return or_(
        Document.status.in_(PUBLIC_STATUSES),
        Document.created_by_id == user.id,
        # 文档级授权（协作者白名单）：被显式授权者可读未发布草稿
        Document.id.in_(select(DocumentPermission.document_id).where(DocumentPermission.user_id == user.id)),
    )


def can_view_document(db: Session, doc: Document, user: User | None, *, is_admin: bool | None = None) -> bool:
    """单个文档是否对当前用户可见."""
    if user is None:  # pragma: no cover - 路由层已保证 user 非空
        return False
    if doc.status in PUBLIC_STATUSES:
        return True
    if doc.created_by_id == user.id:
        return True
    # 文档级授权：被邀请的协作者可读（含草稿）
    from cndb.plugins.documents.services import document_permissions

    if document_permissions.role_for(db, doc.id, user.id) is not None:
        return True
    admin = is_document_admin(db, doc.workspace_id, user) if is_admin is None else is_admin
    return admin


def filter_visible_documents(
    db: Session,
    workspace_id: int,
    docs: Sequence[Document],
    user: User | None,
    *,
    is_admin: bool | None = None,
) -> list[Document]:
    """内存过滤（已取出的文档列表，避免逐条查库）."""
    admin = is_document_admin(db, workspace_id, user) if is_admin is None else is_admin
    if admin:
        return list(docs)
    return [d for d in docs if can_view_document(db, d, user, is_admin=False)]


def visible_document_ids(
    db: Session,
    workspace_id: int,
    user: User | None,
    ids: Iterable[int],
    *,
    is_admin: bool | None = None,
) -> set[int]:
    """给定 id 集合中可见的部分（反链、标签计数等按 id 过滤的场景）."""
    id_list = [int(i) for i in ids]
    if not id_list:
        return set()
    admin = is_document_admin(db, workspace_id, user) if is_admin is None else is_admin
    stmt = select(Document.id).where(Document.workspace_id == workspace_id, Document.id.in_(id_list))
    if not admin:
        stmt = stmt.where(visible_condition(db, workspace_id, user, is_admin=False))
    return {int(row[0]) for row in db.execute(stmt).all()}


def get_visible_document_or_404(
    db: Session,
    workspace_id: int,
    doc_id: int,
    user: User | None,
    *,
    include_deleted: bool = False,
) -> Document:
    """取文档并校验可见性；不可见按 404 处理（不泄露存在性）.

    Args:
        include_deleted: 回收站场景传 True（仍受可见性约束）。
    """
    conditions = [Document.id == doc_id, Document.workspace_id == workspace_id]
    conditions.append(Document.is_deleted.is_(include_deleted))
    if not is_document_admin(db, workspace_id, user):
        conditions.append(visible_condition(db, workspace_id, user, is_admin=False))
    doc = db.execute(select(Document).where(*conditions)).scalar_one_or_none()
    if doc is None:
        raise NotFoundError("文档不存在")
    return doc


def visible_ancestor_ids(docs: Sequence[Document], targets: Sequence[Document] | None = None) -> set[int]:
    """收集 ``targets``（默认全部）的祖先文件夹 id，用于目录树补链.

    ``docs`` 必须是**全部**文档（用于沿 parent_id 上溯），``targets`` 是可见文档；
    只补可见文档的祖先，避免把"他人草稿文件夹"带进树里。
    """
    by_id = {d.id: d for d in docs}
    ancestors: set[int] = set()
    for doc in targets if targets is not None else docs:
        parent_id = doc.parent_id
        while parent_id is not None and parent_id not in ancestors:
            ancestors.add(parent_id)
            parent = by_id.get(parent_id)
            parent_id = parent.parent_id if parent is not None else None
    return ancestors


def is_workspace_owner(db: Session, workspace_id: int, user: User | None) -> bool:
    """工作区所有者（不含超级用户）：用于"仅所有者可发布/下线"等场景."""
    if user is None:  # pragma: no cover
        return False
    if db.get(Workspace, workspace_id) is None:
        return False
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user.id)
        .first()
    )
    return member is not None and member.role == WorkspaceRole.OWNER


__all__ = [
    "PUBLIC_STATUSES",
    "can_view_document",
    "filter_visible_documents",
    "get_visible_document_or_404",
    "is_document_admin",
    "is_workspace_owner",
    "visible_ancestor_ids",
    "visible_condition",
    "visible_document_ids",
]
