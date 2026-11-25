"""ADR 0153 P2 / D8：设计复用模块库 `visibility=team`（权限只认拥有团队）.

口径：
- `team` 档 = 拥有工作区所属**团队成员**可见 / 可引用；
- 跨团队、无团队、非成员一律不可见（浏览 404 / 列表不返回，不泄露原因）；
- `public` / `workspace` 两档行为不变（回归由既有 test_design_library.py 覆盖）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Team, TeamMember, TeamRole, Workspace
from tests.pipeline_helpers import login, make_user, make_workspace

BASE = "/api/v1/workspaces/{ws}/designs"
LIB_BASE = "/api/v1/workspaces/{ws}/design-library"
PART = "param d = 10\ncyl(d = d, h = 5)\n"


def _make_team(db: Session, name: str, owner: User) -> Team:
    team = Team(name=name, slug=name.lower(), description="", policy={}, created_by_id=owner.id)
    db.add(team)
    db.flush()
    db.add(TeamMember(team_id=team.id, user_id=owner.id, role=TeamRole.OWNER))
    db.commit()
    db.refresh(team)
    return team


def _attach(db: Session, ws: Workspace, team: Team | None) -> None:
    ws.team_id = team.id if team else None
    db.commit()


def _publish_team_module(client: TestClient, ws: Workspace, headers: dict[str, str], name: str) -> dict:
    design_id = client.post(
        BASE.format(ws=ws.id),
        json={"title": name, "content": PART, "kind": "part"},
        headers=headers,
    ).json()["id"]
    r = client.post(
        f"{BASE.format(ws=ws.id)}/{design_id}/publish",
        json={"visibility": "team", "name": name, "comment": "团队共享"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def env(db: Session):
    owner = make_user(db, "team_lib_owner")
    team_a = _make_team(db, "TeamA", owner)
    team_b = _make_team(db, "TeamB", owner)
    ws_a = make_workspace(db, owner, "TeamLibA")
    ws_a2 = make_workspace(db, owner, "TeamLibA2")
    ws_b = make_workspace(db, owner, "TeamLibB")
    ws_solo = make_workspace(db, owner, "TeamLibSolo")
    _attach(db, ws_a, team_a)
    _attach(db, ws_a2, team_a)
    _attach(db, ws_b, team_b)
    _attach(db, ws_solo, None)
    return {
        "owner": owner,
        "team_a": team_a,
        "team_b": team_b,
        "ws_a": ws_a,
        "ws_a2": ws_a2,
        "ws_b": ws_b,
        "ws_solo": ws_solo,
    }


@pytest.fixture()
def auth(client: TestClient, env) -> dict[str, str]:
    return login(client, env["owner"])


class TestTeamVisibilityBrowser:
    def test_same_team_can_browse_other_team_outsider_cannot(self, client, db, env, auth):
        module = _publish_team_module(client, env["ws_a"], auth, "团队标准件")

        # 同团队另一个工作区可见
        listed = client.get(f"{LIB_BASE.format(ws=env['ws_a2'].id)}/modules", headers=auth)
        assert listed.status_code == 200, listed.text
        assert [item["name"] for item in listed.json()] == ["团队标准件"]
        assert (
            client.get(f"{LIB_BASE.format(ws=env['ws_a2'].id)}/modules/{module['module_id']}", headers=auth).status_code
            == 200
        )

        # 跨团队不可见（列表不含、详情 404）
        other = client.get(f"{LIB_BASE.format(ws=env['ws_b'].id)}/modules", headers=auth)
        assert other.status_code == 200
        assert other.json() == []
        assert (
            client.get(f"{LIB_BASE.format(ws=env['ws_b'].id)}/modules/{module['module_id']}", headers=auth).status_code
            == 404
        )

        # 未挂团队的工作区同样不可见
        assert client.get(f"{LIB_BASE.format(ws=env['ws_solo'].id)}/modules", headers=auth).json() == []

    def test_owner_workspace_always_visible(self, client, db, env, auth):
        module = _publish_team_module(client, env["ws_a"], auth, "团队标准件2")
        mine = client.get(f"{LIB_BASE.format(ws=env['ws_a'].id)}/modules", headers=auth).json()
        assert [item["id"] for item in mine] == [module["module_id"]]

    def test_visibility_value_accepted_and_listed_as_team(self, client, db, env, auth):
        module = _publish_team_module(client, env["ws_a"], auth, "团队标准件3")
        assert module["visibility"] == "team"
        items = client.get(f"{LIB_BASE.format(ws=env['ws_a'].id)}/modules", headers=auth).json()
        assert items[0]["visibility"] == "team"


class TestTeamVisibilityReference:
    def test_same_team_can_reference_module(self, client, db, env, auth):
        module = _publish_team_module(client, env["ws_a"], auth, "团队轮毂")
        content = f'use "lib:{module["module_key"]}@1"(d = 20)\n'
        r = client.post(
            BASE.format(ws=env["ws_a2"].id),
            json={"title": "装配件", "content": content, "kind": "part"},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
        assert r.json().get("diagnostics") in (None, [])

    def test_cross_team_reference_is_rejected(self, client, db, env, auth):
        module = _publish_team_module(client, env["ws_a"], auth, "团队轮毂2")
        content = f'use "lib:{module["module_key"]}@1"(d = 20)\n'
        r = client.post(
            BASE.format(ws=env["ws_b"].id),
            json={"title": "越权装配", "content": content, "kind": "part"},
            headers=auth,
        )
        # 保存期编译失败 → 4xx（诊断里只说「未找到」，不泄露私有原因）
        assert r.status_code >= 400
        assert "未找到引用的复用模块" in r.text


class TestTeamVisibilityPublication:
    def test_team_visibility_requires_owner_workspace_team(self, client, db, env, auth):
        """未挂团队的工作区发布 team 档仍可发布（等价 workspace），但只有自己可见."""
        module = _publish_team_module(client, env["ws_solo"], auth, "孤立件")
        assert module["visibility"] == "team"
        listed = client.get(f"{LIB_BASE.format(ws=env['ws_a'].id)}/modules", headers=auth).json()
        assert listed == []
