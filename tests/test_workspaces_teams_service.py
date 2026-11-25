"""团队服务helper（`workspaces/services/teams.py`）判定层单测.

覆盖 slug 生成与去重、策略归一与校验、成员 / 角色门控、模块白名单、同团队判定。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Team, TeamMember, TeamRole, Workspace, WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.permissions import policy_default_role, team_policy
from cndb.plugins.workspaces.services.teams import (
    SLUG_MAX_LENGTH,
    ensure_modules_allowed,
    get_team_role,
    in_same_team,
    normalize_team_policy,
    require_team_member,
    require_team_role,
    slugify_team_name,
    team_policy_for,
    unique_team_slug,
    workspace_team_id,
)


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class TestSlug:
    def test_ascii_name(self):
        assert slugify_team_name("R&D Team") == "r-d-team"

    def test_chinese_falls_back_to_team(self):
        assert slugify_team_name("研发部") == "team"

    def test_blank_name(self):
        assert slugify_team_name("   ") == "team"

    def test_truncated(self):
        assert len(slugify_team_name("a" * 200)) == SLUG_MAX_LENGTH

    def test_unique_suffix(self, db):
        a = _user(db, "slug_owner")
        db.add(Team(name="Rd", slug="rd", description="", policy={}, created_by_id=a.id))
        db.commit()
        assert unique_team_slug(db, "Rd") == "rd-2"
        assert unique_team_slug(db, "Rd", exclude_id=None) == "rd-2"

    def test_unique_excludes_self(self, db):
        a = _user(db, "slug_owner2")
        team = Team(name="Ops", slug="ops", description="", policy={}, created_by_id=a.id)
        db.add(team)
        db.commit()
        db.refresh(team)
        assert unique_team_slug(db, "Ops", exclude_id=team.id) == "ops"


class TestPolicy:
    def test_defaults_filled_and_unknown_dropped(self):
        policy = normalize_team_policy({"unknown": 1})
        assert policy == {
            "default_workspace_role": "none",
            "allowed_modules": None,
            "default_storage_quota_bytes": None,
            "allow_member_invite": False,
        }

    def test_allowed_modules_normalized(self):
        policy = normalize_team_policy({"allowed_modules": ["documents", "tables", "tables"]})
        assert policy["allowed_modules"] == ["tables", "documents"]

    @pytest.mark.parametrize(
        ("payload", "detail"),
        [
            ({"default_workspace_role": "root"}, "default_workspace_role"),
            ({"default_storage_quota_bytes": -1}, "default_storage_quota_bytes"),
            ({"default_storage_quota_bytes": True}, "default_storage_quota_bytes"),
            ({"allow_member_invite": "yes"}, "allow_member_invite"),
        ],
    )
    def test_invalid_values_400(self, payload, detail):
        with pytest.raises(HTTPException) as exc:
            normalize_team_policy(payload)
        assert exc.value.status_code == 400
        assert detail in exc.value.detail

    def test_policy_default_role(self):
        assert policy_default_role({}) is None
        assert policy_default_role({"default_workspace_role": "none"}) is None
        assert policy_default_role({"default_workspace_role": "bogus"}) is None
        assert policy_default_role({"default_workspace_role": "editor"}) is WorkspaceRole.EDITOR

    def test_team_policy_merges(self, db):
        owner = _user(db, "policy_owner")
        team = Team(name="P", slug="p", description="", policy={"allow_member_invite": True}, created_by_id=owner.id)
        db.add(team)
        db.commit()
        merged = team_policy_for(team)
        assert merged["allow_member_invite"] is True
        assert merged["default_workspace_role"] == "none"
        assert team_policy(None)["allow_member_invite"] is False


class TestTeamGates:
    def _team(self, db: Session, owner: User) -> Team:
        team = Team(name="G", slug=f"g{owner.id}", description="", policy={}, created_by_id=owner.id)
        db.add(team)
        db.flush()
        db.add(TeamMember(team_id=team.id, user_id=owner.id, role=TeamRole.OWNER))
        db.commit()
        db.refresh(team)
        return team

    def test_get_role_and_member_gate(self, db):
        owner = _user(db, "gate_owner")
        outsider = _user(db, "gate_outsider")
        team = self._team(db, owner)
        assert get_team_role(db, team, owner) is TeamRole.OWNER
        assert get_team_role(db, team, outsider) is None
        with pytest.raises(HTTPException) as exc:
            require_team_member(db, team, outsider)
        assert exc.value.status_code == 404

    def test_require_role_with_and_without_requirement(self, db):
        owner = _user(db, "gate_owner2")
        member = _user(db, "gate_member")
        team = self._team(db, owner)
        db.add(TeamMember(team_id=team.id, user_id=member.id, role=TeamRole.MEMBER))
        db.commit()

        with pytest.raises(PermissionDeniedError) as exc:
            require_team_role(db, team, member, TeamRole.ADMIN)
        assert "团队权限不足" in exc.value.detail

        with pytest.raises(PermissionDeniedError) as exc:
            require_team_role(db, team, member, TeamRole.ADMIN, requirement="仅管理员可操作")
        assert "仅管理员可操作" in exc.value.detail

        assert require_team_role(db, team, owner, TeamRole.OWNER) is TeamRole.OWNER


class TestModulesWhitelist:
    def test_unrestricted_policy_passes(self):
        ensure_modules_allowed({"allowed_modules": None}, ["tables", "documents"])

    def test_subset_passes(self):
        ensure_modules_allowed({"allowed_modules": ["tables", "documents"]}, ["tables"])

    def test_extra_module_rejected(self):
        with pytest.raises(HTTPException) as exc:
            ensure_modules_allowed({"allowed_modules": ["tables"]}, ["tables", "design"])
        assert exc.value.status_code == 400
        assert "design" in exc.value.detail


class TestSameTeam:
    def test_same_and_cross_team(self, db):
        owner = _user(db, "same_owner")
        a = _user(db, "same_a")
        team = Team(name="S", slug="s", description="", policy={}, created_by_id=owner.id)
        db.add(team)
        db.flush()
        ws1 = Workspace(name="S1", created_by_id=owner.id, team_id=team.id)
        ws2 = Workspace(name="S2", created_by_id=owner.id, team_id=team.id)
        solo = Workspace(name="Solo", created_by_id=owner.id)
        db.add_all([ws1, ws2, solo])
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws1.id, user_id=a.id, role=WorkspaceRole.OWNER))
        db.commit()

        assert workspace_team_id(db, ws1.id) == team.id
        assert workspace_team_id(db, solo.id) is None
        assert workspace_team_id(db, 999999) is None
        assert in_same_team(db, ws1.id, ws2.id) is True
        assert in_same_team(db, ws1.id, solo.id) is False
        assert in_same_team(db, 0, ws2.id) is False
        assert in_same_team(db, solo.id, solo.id) is False
