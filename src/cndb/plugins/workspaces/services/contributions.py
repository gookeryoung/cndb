"""工作区贡献统计（需求 0126）.

按工作区编辑者聚合直接写活动：

- 数据行新建 / 更新（``tables_auditlog.action = create / update``，需 ``actor_id``）
- 文档新建（``documents_document.created_by_id``）与保存（版本号 > 1）
- 设计新建（``design_design.created_by_id``）与保存（版本号 > 1）

「曾为编辑者」不依赖成员角色历史表：当前不是 ``owner / editor``（或已移出工作区）
但存在上述活动的人，即视为曾为编辑者并纳入结果。历史数据行审计因未记录
``actor_id`` 无法归属，只统计补记之后的数据。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
from cndb.plugins.documents.models import Document, DocumentVersion
from cndb.plugins.tables.models import AuditLog, DataTable
from cndb.plugins.tables.services.core.audit import ACTION_CREATE, ACTION_UPDATE
from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

#: 计入「编辑者」口径的角色；owner 权限高于 editor，同样展示
EDITOR_ROLES: tuple[WorkspaceRole, ...] = (WorkspaceRole.OWNER, WorkspaceRole.EDITOR)


@dataclass
class ContributionBucket:
    """单个用户的贡献累计（服务层内部结构）."""

    user_id: int
    rows_created: int = 0
    rows_updated: int = 0
    documents_created: int = 0
    documents_edited: int = 0
    designs_created: int = 0
    designs_edited: int = 0
    last_active_at: dt.datetime | None = field(default=None)

    @property
    def total(self) -> int:
        return (
            self.rows_created
            + self.rows_updated
            + self.documents_created
            + self.documents_edited
            + self.designs_created
            + self.designs_edited
        )

    def touch(self, at: dt.datetime | None) -> None:
        """更新最近活动时间（None 忽略）."""
        if at is not None and (self.last_active_at is None or at > self.last_active_at):
            self.last_active_at = at


def _bucket(buckets: dict[int, ContributionBucket], user_id: int) -> ContributionBucket:
    bucket = buckets.get(user_id)
    if bucket is None:
        bucket = ContributionBucket(user_id=user_id)
        buckets[user_id] = bucket
    return bucket


def compute_workspace_contributions(db: Session, workspace_id: int) -> dict[str, Any]:
    """计算工作区贡献统计（需求 0126 C2-C6），返回可直接序列化的 dict."""
    buckets: dict[int, ContributionBucket] = {}

    # ① / ② 数据行新建 / 更新：只统计未回收站表，历史 actor_id 为空的行跳过
    row_stats = (
        db.query(
            AuditLog.actor_id,
            AuditLog.action,
            func.count(AuditLog.id),
            func.max(AuditLog.created_at),
        )
        .join(DataTable, DataTable.id == AuditLog.table_id)
        .filter(
            DataTable.workspace_id == workspace_id,
            DataTable.trashed_at.is_(None),
            AuditLog.actor_id.is_not(None),
            AuditLog.action.in_((ACTION_CREATE, ACTION_UPDATE)),
        )
        .group_by(AuditLog.actor_id, AuditLog.action)
        .all()
    )
    for actor_id, action, count, last_at in row_stats:
        if actor_id is None:  # SQL 已过滤，防御 None 类型
            continue
        bucket = _bucket(buckets, int(actor_id))
        if action == ACTION_CREATE:
            bucket.rows_created += int(count)
        elif action == ACTION_UPDATE:
            bucket.rows_updated += int(count)
        bucket.touch(last_at)

    # ③ 文档新建
    doc_created = (
        db.query(Document.created_by_id, func.count(Document.id), func.max(Document.created_at))
        .filter(
            Document.workspace_id == workspace_id,
            Document.is_folder.is_(False),
            Document.created_by_id.is_not(None),
        )
        .group_by(Document.created_by_id)
        .all()
    )
    for user_id, count, last_at in doc_created:
        if user_id is None:  # pragma: no cover - SQL 已过滤
            continue
        bucket = _bucket(buckets, int(user_id))
        bucket.documents_created += int(count)
        bucket.touch(last_at)

    # ④ 文档保存：版本号 > 1，创建文档时的首版不算「保存」
    doc_edited = (
        db.query(
            DocumentVersion.created_by_id,
            func.count(DocumentVersion.id),
            func.max(DocumentVersion.created_at),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .filter(
            Document.workspace_id == workspace_id,
            DocumentVersion.version_number > 1,
            DocumentVersion.created_by_id.is_not(None),
        )
        .group_by(DocumentVersion.created_by_id)
        .all()
    )
    for user_id, count, last_at in doc_edited:
        if user_id is None:  # pragma: no cover - SQL 已过滤
            continue
        bucket = _bucket(buckets, int(user_id))
        bucket.documents_edited += int(count)
        bucket.touch(last_at)

    # ⑤ 设计新建
    design_created = (
        db.query(DesignDesign.created_by_id, func.count(DesignDesign.id), func.max(DesignDesign.created_at))
        .filter(
            DesignDesign.workspace_id == workspace_id,
            DesignDesign.created_by_id.is_not(None),
        )
        .group_by(DesignDesign.created_by_id)
        .all()
    )
    for user_id, count, last_at in design_created:
        if user_id is None:  # pragma: no cover - SQL 已过滤
            continue
        bucket = _bucket(buckets, int(user_id))
        bucket.designs_created += int(count)
        bucket.touch(last_at)

    # ⑥ 设计保存：版本号 > 1，首次落库不算「保存」
    design_edited = (
        db.query(
            DesignDesignVersion.created_by_id,
            func.count(DesignDesignVersion.id),
            func.max(DesignDesignVersion.created_at),
        )
        .filter(
            DesignDesignVersion.workspace_id == workspace_id,
            DesignDesignVersion.version_number > 1,
            DesignDesignVersion.created_by_id.is_not(None),
        )
        .group_by(DesignDesignVersion.created_by_id)
        .all()
    )
    for user_id, count, last_at in design_edited:
        if user_id is None:  # pragma: no cover - SQL 已过滤
            continue
        bucket = _bucket(buckets, int(user_id))
        bucket.designs_edited += int(count)
        bucket.touch(last_at)

    # 当前成员角色：owner / editor 即使 0 贡献也纳入；viewer 仅在已有活动时纳入
    member_rows = (
        db.query(WorkspaceMember.user_id, WorkspaceMember.role)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .all()
    )
    roles: dict[int, WorkspaceRole] = {}
    for user_id, role in member_rows:
        roles[int(user_id)] = role
        if role in EDITOR_ROLES:
            _bucket(buckets, int(user_id))

    # 用户展示信息（已删除用户查不到，前端按「已删除用户」展示）
    user_ids = list(buckets)
    users = (
        {int(user.id): (user.username, user.nickname) for user in db.query(User).filter(User.id.in_(user_ids)).all()}
        if user_ids
        else {}
    )

    items: list[dict[str, Any]] = []
    for user_id, bucket in buckets.items():
        role = roles.get(user_id)
        total = bucket.total
        if role not in EDITOR_ROLES and total == 0:
            continue
        username, nickname = users.get(user_id, ("", None))
        items.append(
            {
                "user_id": user_id,
                "username": username,
                "nickname": nickname,
                "role": role.value if role is not None else None,
                "is_member": role is not None,
                "is_former_editor": role not in EDITOR_ROLES and total > 0,
                "rows_created": bucket.rows_created,
                "rows_updated": bucket.rows_updated,
                "documents_created": bucket.documents_created,
                "documents_edited": bucket.documents_edited,
                "designs_created": bucket.designs_created,
                "designs_edited": bucket.designs_edited,
                "total": total,
                "last_active_at": bucket.last_active_at,
            }
        )

    # 合计降序 → 最近活动降序 → user_id 升序（保证结果确定性）
    items.sort(
        key=lambda item: (
            -item["total"],
            -(item["last_active_at"].timestamp() if item["last_active_at"] else 0),
            item["user_id"],
        )
    )
    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "items": items,
    }


__all__ = ["EDITOR_ROLES", "ContributionBucket", "compute_workspace_contributions"]
