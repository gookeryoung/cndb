"""工作区贡献统计（需求 0126）.

按工作区编辑者聚合直接写活动：

- 数据行新建 / 更新（``tables_auditlog.action = create / update``，需 ``actor_id``）
- 文档新建（``documents_document.created_by_id``）与保存（版本号 > 1）
- 设计新建（``design_design.created_by_id``）与保存（版本号 > 1）

「曾为编辑者」不依赖成员角色历史表：当前不是 ``owner / editor``（或已移出工作区）
但存在上述活动的人，即视为曾为编辑者并纳入结果。历史数据行审计因未记录
``actor_id`` 无法归属，只统计补记之后的数据。

除累计值外，同时返回近 12 个月按天时序 ``daily``（GitHub 贡献日历 / 趋势曲线用）：
累计始终为全部时间；``daily`` 只含窗口内且计数非零的 ``(日期, 用户)`` 组合。
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

#: 按天时序窗口：近 12 个月（含今天共 365 天）
TIMELINE_DAYS = 365

#: ``daily`` 的键：用户 + 日期
DailyKey = tuple[int, dt.date]


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


def _coerce_date(value: Any) -> dt.date | None:
    """把 SQL ``func.date()`` 的返回值（SQLite 字符串 / PG ``date``）归一为日期."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:  # pragma: no cover - 非法日期防御
        return None


def _record_daily(
    daily: dict[DailyKey, int],
    user_id: int,
    day: Any,
    count: int,
    start: dt.date,
    end: dt.date,
) -> None:
    """写入窗口内按天计数（窗口外的历史活动只计入累计值）."""
    parsed = _coerce_date(day)
    if parsed is None or parsed < start or parsed > end:
        return
    key = (user_id, parsed)
    daily[key] = daily.get(key, 0) + count


def compute_workspace_contributions(db: Session, workspace_id: int) -> dict[str, Any]:
    """计算工作区贡献统计（需求 0126 C2-C6），返回可直接序列化的 dict."""
    buckets: dict[int, ContributionBucket] = {}
    daily: dict[DailyKey, int] = {}
    timeline_end = dt.datetime.now(dt.UTC).date()
    timeline_start = timeline_end - dt.timedelta(days=TIMELINE_DAYS - 1)

    # ① / ② 数据行新建 / 更新：只统计未回收站表，历史 actor_id 为空的行跳过
    row_day = func.date(AuditLog.created_at)
    row_stats = (
        db.query(
            AuditLog.actor_id,
            AuditLog.action,
            row_day,
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
        .group_by(AuditLog.actor_id, AuditLog.action, row_day)
        .all()
    )
    for actor_id, action, day, count, last_at in row_stats:
        if actor_id is None:  # SQL 已过滤，防御 None 类型
            continue
        bucket = _bucket(buckets, int(actor_id))
        if action == ACTION_CREATE:
            bucket.rows_created += int(count)
        elif action == ACTION_UPDATE:
            bucket.rows_updated += int(count)
        bucket.touch(last_at)
        _record_daily(daily, int(actor_id), day, int(count), timeline_start, timeline_end)

    # ③ 文档新建
    doc_created_day = func.date(Document.created_at)
    doc_created = (
        db.query(
            Document.created_by_id,
            doc_created_day,
            func.count(Document.id),
            func.max(Document.created_at),
        )
        .filter(
            Document.workspace_id == workspace_id,
            Document.is_folder.is_(False),
            Document.created_by_id.is_not(None),
        )
        .group_by(Document.created_by_id, doc_created_day)
        .all()
    )
    for user_id, day, count, last_at in doc_created:
        if user_id is None:  # pragma: no cover - SQL 已过滤
            continue
        bucket = _bucket(buckets, int(user_id))
        bucket.documents_created += int(count)
        bucket.touch(last_at)
        _record_daily(daily, int(user_id), day, int(count), timeline_start, timeline_end)

    # ④ 文档保存：版本号 > 1，创建文档时的首版不算「保存」
    doc_edited_day = func.date(DocumentVersion.created_at)
    doc_edited = (
        db.query(
            DocumentVersion.created_by_id,
            doc_edited_day,
            func.count(DocumentVersion.id),
            func.max(DocumentVersion.created_at),
        )
        .join(Document, Document.id == DocumentVersion.document_id)
        .filter(
            Document.workspace_id == workspace_id,
            DocumentVersion.version_number > 1,
            DocumentVersion.created_by_id.is_not(None),
        )
        .group_by(DocumentVersion.created_by_id, doc_edited_day)
        .all()
    )
    for user_id, day, count, last_at in doc_edited:
        if user_id is None:  # pragma: no cover - SQL 已过滤
            continue
        bucket = _bucket(buckets, int(user_id))
        bucket.documents_edited += int(count)
        bucket.touch(last_at)
        _record_daily(daily, int(user_id), day, int(count), timeline_start, timeline_end)

    # ⑤ 设计新建
    design_created_day = func.date(DesignDesign.created_at)
    design_created = (
        db.query(
            DesignDesign.created_by_id,
            design_created_day,
            func.count(DesignDesign.id),
            func.max(DesignDesign.created_at),
        )
        .filter(
            DesignDesign.workspace_id == workspace_id,
            DesignDesign.created_by_id.is_not(None),
        )
        .group_by(DesignDesign.created_by_id, design_created_day)
        .all()
    )
    for user_id, day, count, last_at in design_created:
        if user_id is None:  # pragma: no cover - SQL 已过滤
            continue
        bucket = _bucket(buckets, int(user_id))
        bucket.designs_created += int(count)
        bucket.touch(last_at)
        _record_daily(daily, int(user_id), day, int(count), timeline_start, timeline_end)

    # ⑥ 设计保存：版本号 > 1，首次落库不算「保存」
    design_edited_day = func.date(DesignDesignVersion.created_at)
    design_edited = (
        db.query(
            DesignDesignVersion.created_by_id,
            design_edited_day,
            func.count(DesignDesignVersion.id),
            func.max(DesignDesignVersion.created_at),
        )
        .filter(
            DesignDesignVersion.workspace_id == workspace_id,
            DesignDesignVersion.version_number > 1,
            DesignDesignVersion.created_by_id.is_not(None),
        )
        .group_by(DesignDesignVersion.created_by_id, design_edited_day)
        .all()
    )
    for user_id, day, count, last_at in design_edited:
        if user_id is None:  # pragma: no cover - SQL 已过滤
            continue
        bucket = _bucket(buckets, int(user_id))
        bucket.designs_edited += int(count)
        bucket.touch(last_at)
        _record_daily(daily, int(user_id), day, int(count), timeline_start, timeline_end)

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
    daily_items = [{"date": day, "user_id": user_id, "count": count} for (user_id, day), count in daily.items()]
    daily_items.sort(key=lambda item: (item["date"], item["user_id"]))
    return {
        "generated_at": dt.datetime.now(dt.UTC),
        "timeline_start": timeline_start,
        "timeline_end": timeline_end,
        "daily": daily_items,
        "items": items,
    }


__all__ = ["EDITOR_ROLES", "ContributionBucket", "compute_workspace_contributions"]
