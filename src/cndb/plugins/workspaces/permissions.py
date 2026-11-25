"""工作区角色判定辅助函数（非 FastAPI 权限类，便于单元测试直接调用）.

ADR 0153 D5 / I6：工作区级判定统一收敛到 :func:`resolve_capabilities`。
P0 语义与升级前逐条等价（无团队、无策略）：数据面只看 ``WorkspaceMember.role``，
管理面只授 ``owner``。团队层与策略在 P1 接入，本模块的判定链已预留两步结构。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

from sqlalchemy.orm import Session

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.workspaces.models import (
    ROLE_RANK,
    WORKSPACE_ROLE_LABELS,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
)

if TYPE_CHECKING:
    from cndb.plugins.accounts.models import User


class WorkspaceCapability(enum.StrEnum):
    """工作区能力位（ADR 0153 D10）：内置角色 → 能力位的唯一映射源.

    P0 取值与升级前各入口的判定逐条对齐，不新增 / 不放宽：

    - ``READ``：成员可见（列表 / 详情 / 贡献统计）
    - ``WRITE``：编辑者及以上（数据写入、改结构）
    - ``EXPORT``：编辑者及以上（工作区导出 / 导入，含归档备份导出）
    - ``EDIT_SETTINGS`` / ``MANAGE_MEMBERS`` / ``RESTORE``：仅所有者
    """

    READ = "READ"
    WRITE = "WRITE"
    EXPORT = "EXPORT"
    EDIT_SETTINGS = "EDIT_SETTINGS"
    MANAGE_MEMBERS = "MANAGE_MEMBERS"
    RESTORE = "RESTORE"


# 内置三档角色的能力位集合（唯一来源；自定义角色在 P2 复用同一映射口径）
ROLE_CAPABILITIES: dict[WorkspaceRole, frozenset[WorkspaceCapability]] = {
    WorkspaceRole.OWNER: frozenset(WorkspaceCapability),
    WorkspaceRole.EDITOR: frozenset({WorkspaceCapability.READ, WorkspaceCapability.WRITE, WorkspaceCapability.EXPORT}),
    WorkspaceRole.VIEWER: frozenset({WorkspaceCapability.READ}),
}


@dataclass(frozen=True)
class Capabilities:
    """一次判定结果：数据面角色 + 能力位集合 + 来源归因（ADR 0153 I4）.

    ``team_role`` 在 P0 恒为 None（团队表尚未落地），字段先占位，P1 接入后不改签名。
    """

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


def resolve_capabilities(user: User | None, workspace: Workspace, db: Session) -> Capabilities:
    """工作区能力位判定的唯一入口（ADR 0153 D5 / I6）.

    判定顺序（P0 只有第一步有语义，后两步为 P1 预留）：

    1. 显式工作区成员角色 → 数据面角色（团队策略永不覆盖显式角色）。
    2. 团队策略 ``default_workspace_role``（P1）。
    3. 工作区可见性 ``public`` 授予团队成员只读（P1 / D6）。
    """
    role = _member_role(user, workspace, db)
    sources: dict[str, str] = {}
    if role is not None:
        sources["data"] = f"workspace_member:{role.value}"
    capabilities = ROLE_CAPABILITIES.get(role, frozenset()) if role is not None else frozenset()
    if role is not None and role is WorkspaceRole.OWNER:
        sources["manage"] = f"workspace_member:{role.value}"
    return Capabilities(
        data_role=role,
        team_role=None,
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
    if role is None:
        detail = f"你不是该工作区成员，{scope_part}{contact}"
    else:
        label = WORKSPACE_ROLE_LABELS.get(role.value, role.value)
        detail = f"当前用户在此工作区的角色为【{label}】，{scope_part}{contact}"
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
    "Capabilities",
    "WorkspaceCapability",
    "get_member_role",
    "get_workspace_owner_display_name",
    "has_role",
    "permission_denied_detail",
    "raise_permission_denied",
    "require_capability",
    "resolve_capabilities",
]
