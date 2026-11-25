"""工作区角色判定辅助函数（非 FastAPI 权限类，便于单元测试直接调用）.

ADR 0153 D5 / I6：工作区级判定统一收敛到 :func:`resolve_capabilities`。

判定链固定两步（I7）：显式工作区成员角色 > 团队策略默认 / 工作区可见性 > 无。
管理面与数据面分离（D4）：团队 owner / admin 只拿管理面能力位，默认读不到数据。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

from sqlalchemy.orm import Session

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.workspaces.models import (
    POLICY_DEFAULT_ROLE_VALUES,
    ROLE_RANK,
    TEAM_POLICY_DEFAULTS,
    TEAM_ROLE_LABELS,
    WORKSPACE_ROLE_LABELS,
    Team,
    TeamMember,
    TeamRole,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceVisibility,
)

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


class WorkspaceCapability(enum.StrEnum):
    """工作区能力位（ADR 0153 D10）：内置角色 → 能力位的唯一映射源.

    P0 取值与升级前各入口的判定逐条对齐，不新增 / 不放宽：

    - ``READ``：成员可见（列表 / 详情 / 贡献统计）
    - ``WRITE``：编辑者及以上（数据写入、改结构）
    - ``EXPORT``：编辑者及以上（工作区导出 / 导入，含归档备份导出）
    - ``EDIT_SETTINGS`` / ``MANAGE_MEMBERS`` / ``RESTORE``：管理面，所有者或团队管理员
    - ``DELETE_WORKSPACE``：仅工作区所有者（团队管理员不可删，ADR 0153 D9）
    - ``MANAGE_LINKS``：仅工作区所有者（批准 / 拒绝 / 撤回跨工作区链接，ADR 0154 C2）
    """

    READ = "READ"
    WRITE = "WRITE"
    EXPORT = "EXPORT"
    EDIT_SETTINGS = "EDIT_SETTINGS"
    MANAGE_MEMBERS = "MANAGE_MEMBERS"
    RESTORE = "RESTORE"
    DELETE_WORKSPACE = "DELETE_WORKSPACE"
    MANAGE_LINKS = "MANAGE_LINKS"


# 内置三档角色的能力位集合（唯一来源；自定义角色在 P2 复用同一映射口径）
ROLE_CAPABILITIES: dict[WorkspaceRole, frozenset[WorkspaceCapability]] = {
    WorkspaceRole.OWNER: frozenset(WorkspaceCapability),
    WorkspaceRole.EDITOR: frozenset({WorkspaceCapability.READ, WorkspaceCapability.WRITE, WorkspaceCapability.EXPORT}),
    WorkspaceRole.VIEWER: frozenset({WorkspaceCapability.READ}),
}

# 团队管理面（D4）：团队 owner / admin 只拿这三个能力位，**不含**数据面与删除工作区
TEAM_MANAGE_CAPABILITIES: frozenset[WorkspaceCapability] = frozenset(
    {WorkspaceCapability.EDIT_SETTINGS, WorkspaceCapability.MANAGE_MEMBERS, WorkspaceCapability.RESTORE}
)


@dataclass(frozen=True)
class Capabilities:
    """一次判定结果：数据面角色 + 团队角色 + 能力位集合 + 来源归因（ADR 0153 I4）."""

    data_role: WorkspaceRole | None
    team_role: str | None
    capabilities: frozenset[WorkspaceCapability]
    sources: dict[str, str]

    def allows(self, capability: WorkspaceCapability) -> bool:
        """判断能力位是否可用."""
        return capability in self.capabilities

    def to_payload(self) -> dict[str, object]:
        """序列化为接口载荷（前端 ``useCapabilities`` 唯一消费形态）."""
        return {
            "data_role": self.data_role.value if self.data_role else None,
            "team_role": self.team_role,
            "capabilities": sorted(cap.value for cap in self.capabilities),
            "sources": dict(self.sources),
        }


def _member_role(user: User | None, workspace: Workspace, db: Session) -> WorkspaceRole | None:
    """唯一的工作区成员查询入口（其它判定一律经此派生）."""
    if user is None:  # pragma: no cover - Depends 保证 user 非 None
        return None
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == user.id)
        .first()
    )
    return member.role if member else None


def get_member_role(user: User | None, workspace: Workspace, db: Session) -> WorkspaceRole | None:
    """返回用户在工作区的角色枚举，非成员返回 None（``resolve_capabilities`` 的数据面视图）."""
    return _member_role(user, workspace, db)


def _team_of(workspace: Workspace, db: Session) -> Team | None:
    """读取工作区所属团队（无团队返回 None；单值归属，D3）."""
    team_id = getattr(workspace, "team_id", None)
    if not team_id:
        return None
    return db.get(Team, team_id)


def _team_role(user: User | None, team: Team | None, db: Session) -> TeamRole | None:
    """读取用户在团队内的角色；非成员 / 无团队返回 None."""
    if user is None or team is None:  # pragma: no cover - user 由 Depends 保证非 None
        return None
    member = db.query(TeamMember).filter(TeamMember.team_id == team.id, TeamMember.user_id == user.id).first()
    return member.role if member else None


def team_policy(team: Team | None) -> dict[str, object]:
    """团队策略（缺键按 ``TEAM_POLICY_DEFAULTS`` 补齐；未知键原样保留）."""
    merged: dict[str, object] = dict(TEAM_POLICY_DEFAULTS)
    if team is not None:
        merged.update(team.policy or {})
    return merged


def policy_default_role(policy: dict[str, object]) -> WorkspaceRole | None:
    """把策略里的 ``default_workspace_role`` 解析为数据面角色（``none`` / 非法值 → None）."""
    raw = policy.get("default_workspace_role")
    if not isinstance(raw, str) or raw not in POLICY_DEFAULT_ROLE_VALUES or raw == "none":
        return None
    return WorkspaceRole(raw)


def resolve_capabilities(user: User | None, workspace: Workspace, db: Session) -> Capabilities:
    """工作区能力位判定的唯一入口（ADR 0153 D5 / I6）.

    判定顺序（显式 > 策略默认 > 无，每步写入 ``sources`` 供 403 文案归因，I4）：

    1. 显式工作区成员角色 → 数据面角色（团队策略**永不覆盖**显式角色）。
    2. 工作区可见性 ``private``：仅工作区所有者有数据面（D6，P2 起生效）。
    3. 团队策略 ``default_workspace_role`` / 可见性 ``public``：团队成员只读（纯放宽）。
    4. 管理面：工作区所有者，或团队 owner / admin（D4，**不含**数据面）。
    """
    role = _member_role(user, workspace, db)
    team = _team_of(workspace, db)
    team_role = _team_role(user, team, db)
    sources: dict[str, str] = {}

    data_role = role
    if role is not None:
        sources["data"] = f"workspace_member:{role.value}"
        # D6（P2 起）：私有工作区只对所有者开放数据面；存量 private 已在迁移里归一为 member
        if workspace.visibility is WorkspaceVisibility.PRIVATE and role is not WorkspaceRole.OWNER:
            data_role = None
            sources["data"] = f"workspace_private:{role.value}"
    elif team_role is not None:
        # D6：公开工作区对团队成员开放只读（优先于策略默认）
        if workspace.visibility is WorkspaceVisibility.PUBLIC:
            data_role = WorkspaceRole.VIEWER
            sources["data"] = "workspace_public"
        else:
            default_role = policy_default_role(team_policy(team))
            if default_role is not None:
                data_role = default_role
                sources["data"] = f"team_default:{default_role.value}"

    capabilities = ROLE_CAPABILITIES.get(data_role, frozenset()) if data_role is not None else frozenset()
    if data_role is WorkspaceRole.OWNER:
        sources["manage"] = "workspace_member:owner"
    elif team_role in (TeamRole.OWNER, TeamRole.ADMIN):
        capabilities = capabilities | TEAM_MANAGE_CAPABILITIES
        sources["manage"] = f"team_role:{team_role.value}"

    return Capabilities(
        data_role=data_role,
        team_role=team_role.value if team_role is not None else None,
        capabilities=capabilities,
        sources=sources,
    )


def require_capability(
    capability: WorkspaceCapability,
    db: Session,
    workspace: Workspace,
    user: User,
    *,
    requirement: str = "",
) -> Capabilities:
    """校验能力位，失败按 ADR 0047 模板抛 403；成功返回判定结果供调用方复用."""
    caps = resolve_capabilities(user, workspace, db)
    if caps.allows(capability):
        return caps
    raise_permission_denied(db, workspace, user, requirement=requirement)


def has_role(user: User | None, workspace: Workspace, minimum: WorkspaceRole, db: Session) -> bool:
    """判断用户角色是否达到最低要求."""
    role = get_member_role(user, workspace, db)
    if role is None:  # pragma: no cover - 由 get_member_role 内部处理
        return False
    return ROLE_RANK[role] >= ROLE_RANK[minimum]


def get_workspace_owner_display_name(db: Session, workspace: Workspace) -> str | None:
    """返回工作区拥有者的展示名（nickname 回退 username），无 owner 成员返回 None."""
    member = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.role == WorkspaceRole.OWNER)
        .first()
    )
    if member is None or member.user is None:  # pragma: no cover - user 为关系必载
        return None
    return member.user.nickname or member.user.username


def permission_denied_detail(
    db: Session,
    workspace: Workspace,
    user: User,
    *,
    scope: str = "",
    requirement: str = "",
) -> str:
    """构造 403 权限不足的中文文案（ADR 0047 唯一出口）.

    Args:
        db: 数据库会话。
        workspace: 目标工作区。
        user: 当前用户。
        scope: 被拒层级描述（如 ``"表级"`` / ``"视图级"``；空串表示不带层级）。
        requirement: 额外要求描述（如 ``"仅 owner/editor 可合并修改申请"``）。
    """
    role = get_member_role(user, workspace, db)
    scope_part = f"{scope}权限不足" if scope else "权限不足"
    owner_name = get_workspace_owner_display_name(db, workspace)
    if owner_name:
        contact = (
            f"；如需加入，请联系工作区拥有者【{owner_name}】"
            if role is None
            else (f"；如需提升权限，请联系工作区拥有者【{owner_name}】")
        )
    else:
        contact = ""
    # 团队层归因（ADR 0153 I4）：团队管理员被数据面拒绝时说清「只有管理面」
    team = _team_of(workspace, db)
    team_role = _team_role(user, team, db)
    team_part = ""
    if team is not None and team_role is not None and role is not WorkspaceRole.OWNER:
        team_label = TEAM_ROLE_LABELS.get(team_role.value, team_role.value)
        team_part = f"（你在团队【{team.name}】的角色为【{team_label}】，管理面权限不含数据读写）"
    if role is None:
        detail = f"你不是该工作区成员{team_part}，{scope_part}{contact}"
    else:
        label = WORKSPACE_ROLE_LABELS.get(role.value, role.value)
        detail = f"当前用户在此工作区的角色为【{label}】{team_part}，{scope_part}{contact}"
    if requirement:
        detail = f"{detail}（{requirement}）"
    return detail


def raise_permission_denied(
    db: Session,
    workspace: Workspace,
    user: User,
    *,
    scope: str = "",
    requirement: str = "",
    code: str | None = None,
) -> NoReturn:
    """按 ADR 0047 模板构造文案并抛出 ``PermissionDeniedError``（HTTP 403）."""
    raise PermissionDeniedError(
        permission_denied_detail(db, workspace, user, scope=scope, requirement=requirement),
        code=code,
    )


__all__ = [
    "ROLE_CAPABILITIES",
    "TEAM_MANAGE_CAPABILITIES",
    "Capabilities",
    "WorkspaceCapability",
    "get_member_role",
    "get_workspace_owner_display_name",
    "has_role",
    "permission_denied_detail",
    "policy_default_role",
    "raise_permission_denied",
    "require_capability",
    "resolve_capabilities",
    "team_policy",
]
