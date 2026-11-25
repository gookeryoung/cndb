"""主页待办聚合（ADR 0160 P2）—— `GET /api/v1/home/summary` 的判定与统计.

口径（ADR 0160 D1-D6 / I1-I5）：

- **只读**：只做 SELECT，不写业务表、不写 ``core_event``；
- **逐工作区同权**：每个工作区的计数都建立在既有判定之上
  （``readable_tables`` 表 READ、``can_write_directly`` 审批资格、``resolve_capabilities`` 的
  ``MANAGE_LINKS``），任一工作区不可读 → 该工作区不贡献计数，也不出现在载荷里；
- **不外泄**：响应只有聚合计数，不含工作区 id / 名称 / 条目标题 / 行数据；
- **降级**：单个工作区统计异常 → 该块计 0 并置 ``partial=True``，不整体 500（主页入口页不因辅助信息失败）；
- **缓存**：进程内 20s（≤30s），key 含 ``user_id``；写路径经 :func:`invalidate_home_summary` 主动失效。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceVisibility,
)

# 短 TTL：待办写路径分散在三个插件，主动失效为主、TTL 兜底（ADR 0160 D4 / I4）
HOME_SUMMARY_TTL_SECONDS = 20.0


def _cache() -> Any:
    from cndb.core.cache import list_cache

    return list_cache


def invalidate_home_summary() -> int:
    """失效所有用户的主页待办聚合缓存（待办 / 成员 / 工作区 / 团队写路径调用）."""
    from cndb.core.cache import cache_key, list_cache

    return list_cache.clear(cache_key("home-summary"))


def visible_workspaces(db: Session, user: User) -> list[Workspace]:
    """当前用户「可见工作区」——与 `GET /workspaces` 同口径（成员行 + 私有仅所有者）.

    团队派生的只读访问（团队策略默认角色 / 公开工作区）不建成员行，也不进工作区列表，
    这里同样不计入，保证两处口径一致（ADR 0160 I2）。
    """
    rows = db.execute(
        select(Workspace, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.id)
    ).all()
    workspaces: list[Workspace] = []
    for workspace, member in rows:
        # D6：私有工作区只对所有者出现在列表里（非 owner 成员 role 为 None）
        if workspace.visibility == WorkspaceVisibility.PRIVATE and member.role != WorkspaceRole.OWNER:
            continue
        workspaces.append(workspace)
    return workspaces


def _workspace_pending(db: Session, workspace: Workspace, user: User) -> dict[str, int]:
    """单个工作区的待办计数（全部建立在既有判定之上）."""
    from cndb.plugins.change_requests.models import CR_STATUS_OPEN, ChangeRequest
    from cndb.plugins.change_requests.services import can_write_directly
    from cndb.plugins.issues.models import ISSUE_STATUS_OPEN, Issue
    from cndb.plugins.tables.services.core.access import readable_tables
    from cndb.plugins.workspaces.models import WorkspaceLink, WorkspaceLinkStatus
    from cndb.plugins.workspaces.permissions import WorkspaceCapability, resolve_capabilities

    counts = {"change_requests": 0, "issues": 0, "link_requests": 0}

    tables = readable_tables(db, workspace.id, user)
    readable_ids = [table.id for table in tables]

    # 修改申请：只算「我能审」的表上的 open，且排除自己提交的（自己提交的不需要自己处理）
    reviewable_ids = [table.id for table in tables if can_write_directly(db, table, user)]
    if reviewable_ids:
        counts["change_requests"] = int(
            db.scalar(
                select(func.count())
                .select_from(ChangeRequest)
                .where(
                    ChangeRequest.table_id.in_(reviewable_ids),
                    ChangeRequest.status == CR_STATUS_OPEN,
                    ChangeRequest.submitted_by_id != user.id,
                )
            )
            or 0
        )

    # 问题：可读表上的 open（所有成员都能看 / 回复，不额外要求审批资格）
    if readable_ids:
        counts["issues"] = int(
            db.scalar(
                select(func.count())
                .select_from(Issue)
                .where(
                    Issue.table_id.in_(readable_ids),
                    Issue.status == ISSUE_STATUS_OPEN,
                )
            )
            or 0
        )

    # 链接审批：源工作区的 MANAGE_LINKS（与 `links/inbox` 同一判定）
    capabilities = resolve_capabilities(user, workspace, db)
    if capabilities.allows(WorkspaceCapability.MANAGE_LINKS):
        counts["link_requests"] = int(
            db.scalar(
                select(func.count())
                .select_from(WorkspaceLink)
                .where(
                    WorkspaceLink.source_workspace_id == workspace.id,
                    WorkspaceLink.status == WorkspaceLinkStatus.PENDING,
                )
            )
            or 0
        )
    return counts


def build_home_summary(db: Session, user: User) -> dict[str, Any]:
    """聚合主页待办（返回值即响应载荷，字段白名单见 ADR 0160 D2）."""
    workspaces = visible_workspaces(db, user)
    team_ids = {workspace.team_id for workspace in workspaces if workspace.team_id}
    pending = {"change_requests": 0, "issues": 0, "link_requests": 0}
    partial = False
    for workspace in workspaces:
        try:
            counts = _workspace_pending(db, workspace, user)
        except Exception:
            partial = True
            continue
        for key, value in counts.items():
            pending[key] += value
    pending["total"] = pending["change_requests"] + pending["issues"] + pending["link_requests"]
    return {
        "workspace_count": len(workspaces),
        "team_count": len(team_ids),
        "pending": pending,
        "partial": partial,
    }


def cached_home_summary(db: Session, user: User) -> dict[str, Any]:
    """带进程内缓存的聚合入口（key 含 user_id 与库标识，ADR 0160 I4）."""
    from cndb.core.cache import cache_key

    cache = _cache()
    key = cache_key("home-summary", user.id, id(db.bind))
    cached = cache.get(key)
    if cached is not None:
        return cached
    data = build_home_summary(db, user)
    cache.set(key, data, HOME_SUMMARY_TTL_SECONDS)
    return data
