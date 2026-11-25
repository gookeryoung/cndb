"""ADR 0153 P1：团队层对 `resolve_capabilities` 的影响（判定层单测）.

锁定四条口径：
1. 团队角色只产管理面（D4 / I1）：`team_admin` 读不到数据，但能改设置 / 管成员；
2. 删除 / 覆盖恢复仍只认工作区所有者（D9，`DELETE_WORKSPACE`）；
3. 显式工作区角色 > 团队策略默认 > 工作区可见性（D5 / I7 固定两步链）；
4. 存量等价（I3）：未挂团队 / 策略缺省时判定与 P0 完全一致。
"""

from __future__ import annotations

import pytest

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import (
    TEAM_POLICY_DEFAULTS,
    Team,
    TeamMember,
    TeamRole,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceVisibility,
)
from cndb.plugins.workspaces.permissions import (
    WorkspaceCapability,
    has_role,
    permission_denied_detail,
    require_capability,
    resolve_capabilities,
)


@pytest.fixture()
def _user(db):
    def _make(username: str, nickname: str = "") -> User:
        u = User(username=username, nickname=nickname or username)
        u.set_password("pass")
        db.add(u)
        db.commit()
        return u

    return _make


@pytest.fixture()
def _team(db):
    def _make(name: str, *, policy: dict | None = None, owner: User | None = None) -> Team:
        team = Team(
            name=name,
            slug=name.lower(),
            description="",
            policy=policy or {},
            created_by_id=owner.id if owner else None,
        )
        db.add(team)
        db.flush()
        if owner is not None:
            db.add(TeamMember(team_id=team.id, user_id=owner.id, role=TeamRole.OWNER))
        db.commit()
        db.refresh(team)
        return team

    return _make


@pytest.fixture()
def _team_member(db):
    def _make(team: Team, user: User, role: TeamRole) -> None:
        db.add(TeamMember(team_id=team.id, user_id=user.id, role=role))
        db.commit()

    return _make


@pytest.fixture()
def _ws(db):
    def _make(
        name: str,
        *,
        owner: User | None = None,
        team: Team | None = None,
        visibility: WorkspaceVisibility = WorkspaceVisibility.MEMBER,
    ) -> Workspace:
        ws = Workspace(
            name=name,
            created_by_id=owner.id if owner else None,
            team_id=team.id if team else None,
            visibility=visibility,
        )
        db.add(ws)
        db.flush()
        if owner is not None:
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(ws)
        return ws

    return _make


class TestTeamRoleOnlyGrantsManagement:
    """D4 / I1：团队管理员默认看不到数据（H49）."""

    @pytest.mark.parametrize("team_role", [TeamRole.ADMIN, TeamRole.OWNER])
    def test_team_admin_without_membership_cannot_read_data(self, db, _user, _team, _team_member, _ws, team_role):
        team = _team("研发部")
        admin = _user(f"p1_teamadmin_{team_role.value}")
        _team_member(team, admin, team_role)
        ws = _ws("研发部工作区", team=team)

        caps = resolve_capabilities(admin, ws, db)
        assert caps.data_role is None
        assert caps.team_role == team_role.value
        assert not caps.allows(WorkspaceCapability.READ)
        assert not caps.allows(WorkspaceCapability.WRITE)
        assert not caps.allows(WorkspaceCapability.EXPORT)
        assert caps.allows(WorkspaceCapability.EDIT_SETTINGS)
        assert caps.allows(WorkspaceCapability.MANAGE_MEMBERS)
        assert caps.sources["manage"] == f"team_role:{team_role.value}"
        assert "data" not in caps.sources

    def test_team_admin_cannot_delete_workspace(self, db, _user, _team, _team_member, _ws):
        team = _team("研发部")
        admin = _user("p1_teamadmin_delete")
        _team_member(team, admin, TeamRole.ADMIN)
        ws = _ws("研发部工作区2", team=team)
        caps = resolve_capabilities(admin, ws, db)
        assert not caps.allows(WorkspaceCapability.DELETE_WORKSPACE)
        with pytest.raises(PermissionDeniedError):
            require_capability(WorkspaceCapability.DELETE_WORKSPACE, db, ws, admin, requirement="仅所有者可删除工作区")

    def test_team_member_has_nothing_by_default(self, db, _user, _team, _team_member, _ws):
        """团队成员不是工作区成员 → 无数据面、无管理面（默认 none，I3）."""
        team = _team("研发部")
        plain = _user("p1_team_member_plain")
        _team_member(team, plain, TeamRole.MEMBER)
        ws = _ws("研发部工作区3", team=team)

        caps = resolve_capabilities(plain, ws, db)
        assert caps.data_role is None
        assert caps.team_role == "member"
        assert caps.capabilities == frozenset()
        assert caps.sources == {}

    def test_owner_membership_beats_team_role(self, db, _user, _team, _team_member, _ws):
        team = _team("研发部")
        user = _user("p1_both_owner")
        _team_member(team, user, TeamRole.MEMBER)
        ws = _ws("研发部工作区4", owner=user, team=team)

        caps = resolve_capabilities(user, ws, db)
        assert caps.data_role is WorkspaceRole.OWNER
        assert caps.sources["manage"] == "workspace_member:owner"
        assert caps.allows(WorkspaceCapability.DELETE_WORKSPACE)


class TestPolicyDefaultRole:
    """D5：显式 > 团队策略默认 > 无；默认 none 保持存量（I3）."""

    def test_policy_default_viewer_grants_team_member_read(self, db, _user, _team, _team_member, _ws):
        team = _team("研发部", policy={"default_workspace_role": "viewer"})
        member = _user("p1_policy_viewer")
        _team_member(team, member, TeamRole.MEMBER)
        ws = _ws("策略工作区", team=team)

        caps = resolve_capabilities(member, ws, db)
        assert caps.data_role is WorkspaceRole.VIEWER
        assert caps.sources["data"] == "team_default:viewer"
        assert caps.allows(WorkspaceCapability.READ)
        assert not caps.allows(WorkspaceCapability.WRITE)

    def test_policy_default_editor(self, db, _user, _team, _team_member, _ws):
        team = _team("研发部", policy={"default_workspace_role": "editor"})
        member = _user("p1_policy_editor")
        _team_member(team, member, TeamRole.MEMBER)
        ws = _ws("策略工作区2", team=team)

        caps = resolve_capabilities(member, ws, db)
        assert caps.data_role is WorkspaceRole.EDITOR
        assert caps.allows(WorkspaceCapability.WRITE)

    def test_explicit_member_role_beats_policy(self, db, _user, _team, _team_member, _ws):
        """团队策略永不覆盖显式角色（D5 第 1 步）."""
        team = _team("研发部", policy={"default_workspace_role": "editor"})
        member = _user("p1_explicit_viewer")
        _team_member(team, member, TeamRole.MEMBER)
        ws = _ws("策略工作区3", team=team)
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=member.id, role=WorkspaceRole.VIEWER))
        db.commit()

        caps = resolve_capabilities(member, ws, db)
        assert caps.data_role is WorkspaceRole.VIEWER
        assert caps.sources["data"] == "workspace_member:viewer"

    def test_non_team_member_gets_nothing_from_policy(self, db, _user, _team, _ws):
        team = _team("研发部", policy={"default_workspace_role": "editor"})
        outsider = _user("p1_policy_outsider")
        ws = _ws("策略工作区4", team=team)

        caps = resolve_capabilities(outsider, ws, db)
        assert caps.data_role is None
        assert caps.team_role is None
        assert caps.capabilities == frozenset()

    def test_invalid_policy_value_falls_back_to_none(self, db, _user, _team, _team_member, _ws):
        """库里存了脏值（历史 / 手工改）时不放行，按 none 处理."""
        team = _team("研发部", policy={"default_workspace_role": "admin"})
        member = _user("p1_policy_dirty")
        _team_member(team, member, TeamRole.MEMBER)
        ws = _ws("策略工作区5", team=team)
        assert resolve_capabilities(member, ws, db).data_role is None


class TestPublicVisibility:
    """D6：`public` = 团队成员只读（纯放宽；无团队时等价 member）."""

    def test_public_grants_team_member_viewer(self, db, _user, _team, _team_member, _ws):
        team = _team("研发部")
        member = _user("p1_public_member")
        _team_member(team, member, TeamRole.MEMBER)
        ws = _ws("公开工作区", team=team, visibility=WorkspaceVisibility.PUBLIC)

        caps = resolve_capabilities(member, ws, db)
        assert caps.data_role is WorkspaceRole.VIEWER
        assert caps.sources["data"] == "workspace_public"

    def test_public_does_not_grant_outside_team(self, db, _user, _team, _ws):
        team = _team("研发部")
        outsider = _user("p1_public_outsider")
        ws = _ws("公开工作区2", team=team, visibility=WorkspaceVisibility.PUBLIC)
        assert resolve_capabilities(outsider, ws, db).data_role is None

    def test_public_without_team_equals_member(self, db, _user, _ws):
        """未挂团队时 public 不引入「全站可见」（D6 边界 3）."""
        outsider = _user("p1_public_noteam")
        ws = _ws("个人公开工作区", visibility=WorkspaceVisibility.PUBLIC)
        assert resolve_capabilities(outsider, ws, db).data_role is None

    def test_private_is_owner_only_since_p2(self, db, _user, _ws):
        """D6（P2）：`private` = 仅工作区所有者有数据面；存量 private 已由迁移归一为 member."""
        viewer = _user("p2_private_viewer")
        editor = _user("p2_private_editor")
        owner = _user("p2_private_owner")
        ws = _ws("私有工作区", visibility=WorkspaceVisibility.PRIVATE, owner=owner)
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=editor.id, role=WorkspaceRole.EDITOR))
        db.commit()

        viewer_caps = resolve_capabilities(viewer, ws, db)
        assert viewer_caps.data_role is None
        assert viewer_caps.capabilities == frozenset()
        # 归因保留：说明「私有工作区不放行非所有者」
        assert viewer_caps.sources["data"] == "workspace_private:viewer"

        assert resolve_capabilities(editor, ws, db).data_role is None
        owner_caps = resolve_capabilities(owner, ws, db)
        assert owner_caps.data_role is WorkspaceRole.OWNER
        assert owner_caps.allows(WorkspaceCapability.DELETE_WORKSPACE)

    def test_private_does_not_grant_team_public_read(self, db, _user, _team, _team_member, _ws):
        """`private` 与 `public` 互斥：私有工作区不因团队成员身份获得只读."""
        team = _team("研发部")
        member = _user("p2_private_team_member")
        _team_member(team, member, TeamRole.MEMBER)
        ws = _ws("私有工作区2", team=team, visibility=WorkspaceVisibility.PRIVATE)
        assert resolve_capabilities(member, ws, db).data_role is None


class TestLegacyEquivalenceStillHolds:
    """I3：未挂团队 / 策略缺省的工作区判定与 P0 / 升级前逐条一致."""

    @pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.EDITOR, WorkspaceRole.VIEWER])
    def test_teamless_workspace_matches_legacy(self, db, _user, _ws, role):
        user = _user(f"p1_eq_{role.value}")
        ws = _ws(f"无团队工作区_{role.value}")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role))
        db.commit()

        caps = resolve_capabilities(user, ws, db)
        assert caps.data_role is role
        assert caps.team_role is None
        minimum_capability = {
            WorkspaceRole.VIEWER: WorkspaceCapability.READ,
            WorkspaceRole.EDITOR: WorkspaceCapability.WRITE,
            WorkspaceRole.OWNER: WorkspaceCapability.EDIT_SETTINGS,
        }[role]
        assert caps.allows(minimum_capability) is has_role(user, ws, role, db)

    def test_defaults_are_unchanged(self):
        assert TEAM_POLICY_DEFAULTS["default_workspace_role"] == "none"
        assert TEAM_POLICY_DEFAULTS["allowed_modules"] is None


class TestPermissionDeniedCopy:
    """I4：团队管理面被数据面拒绝时，403 文案要说明团队角色."""

    def test_team_admin_copy_explains_team_role(self, db, _user, _team, _team_member, _ws):
        team = _team("研发部")
        admin = _user("p1_copy_admin", nickname="王五")
        _team_member(team, admin, TeamRole.ADMIN)
        owner = _user("p1_copy_owner", nickname="张三")
        ws = _ws("文案工作区", owner=owner, team=team)

        detail = permission_denied_detail(db, ws, admin, scope="表级")
        assert "研发部" in detail
        assert "团队管理员" in detail
        assert "管理面权限不含数据读写" in detail
        assert "张三" in detail

    def test_teamless_copy_unchanged(self, db, _user, _ws):
        owner = _user("p1_copy_owner2", nickname="李四")
        ws = _ws("文案工作区2", owner=owner)
        outsider = _user("p1_copy_outsider")
        detail = permission_denied_detail(db, ws, outsider)
        assert detail == "你不是该工作区成员，权限不足；如需加入，请联系工作区拥有者【李四】"
