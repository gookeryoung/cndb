"""主页待办聚合端点测试（ADR 0160 P2）：`GET /api/v1/home/summary`.

覆盖：
- 登录要求 / 空账号
- 逐工作区同权：修改申请只算「我能审且非本人提交」、问题只算可读表、链接只算有 MANAGE_LINKS 的源工作区
- 不可见工作区不贡献计数（非成员 / 私有工作区非所有者）
- 载荷白名单（无 id / 名称 / 标题）
- 进程内缓存命中与写路径主动失效
- 单块失败降级为 0 + partial=True，HTTP 仍 200
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.issues.models import ISSUE_STATUS_OPEN, Issue
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import (
    Team,
    Workspace,
    WorkspaceMember,
    WorkspaceRole,
    WorkspaceVisibility,
)
from cndb.plugins.workspaces.services import home_summary as home_service

SUMMARY = "/api/v1/home/summary"
CR = "/api/v1/workspaces/{ws}/tables/{tb}/change-requests"
ISSUES = "/api/v1/workspaces/{ws}/tables/{tb}/issues"
LINKS = "/api/v1/workspaces/{wid}/links"


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=f"{username}-昵称")
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_table(db: Session, ws: Workspace, name: str = "SummaryTable") -> DataTable:
    engine = db.get_bind()
    table = DataTable(workspace_id=ws.id, name=name)
    table.ensure_db_name()
    db.add(table)
    db.flush()
    for fname, ftype in [("名称", "text"), ("数量", "number")]:
        field = DataField(table_id=table.id, name=fname, field_type=ftype)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(engine, table)
    return table


class Env:
    """owner / viewer 同在一个工作区；outsider 另有一个自己的私有工作区。"""

    def __init__(self, db: Session) -> None:
        self.owner = _make_user(db, "home_owner")
        self.viewer = _make_user(db, "home_viewer")
        self.outsider = _make_user(db, "home_outsider")

        self.ws = Workspace(name="主页待办工作区", created_by_id=self.owner.id)
        self.private_ws = Workspace(
            name="私有工作区",
            created_by_id=self.outsider.id,
            visibility=WorkspaceVisibility.PRIVATE,
        )
        db.add_all([self.ws, self.private_ws])
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.add(
            WorkspaceMember(
                workspace_id=self.private_ws.id,
                user_id=self.outsider.id,
                role=WorkspaceRole.OWNER,
            )
        )
        # 私有工作区的非 owner 成员（D6：不出现在列表，也不计入待办口径）
        db.add(WorkspaceMember(workspace_id=self.private_ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        db.refresh(self.ws)
        db.refresh(self.private_ws)
        self.table = _make_table(db, self.ws)
        self.private_table = _make_table(db, self.private_ws, name="私有表")


@pytest.fixture()
def env(db: Session) -> Env:
    return Env(db)


@pytest.fixture(autouse=True)
def _clear_summary_cache():
    """每个用例前清空聚合缓存：进程内缓存跨用例共享，避免用户 id 复用导致串数据."""
    home_service.invalidate_home_summary()


def _submit_issue(client: TestClient, env: Env, auth: dict[str, str], title: str = "问题") -> dict:
    r = client.post(
        ISSUES.format(ws=env.ws.id, tb=env.table.id),
        json={"title": title},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _submit_request(client: TestClient, env: Env, auth: dict[str, str], title: str = "申请") -> dict:
    r = client.post(
        CR.format(ws=env.ws.id, tb=env.table.id),
        json={"title": title, "items": [{"op": "create", "values": {"名称": "新行"}}]},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestAuthAndEmpty:
    def test_unauthenticated_401(self, client: TestClient) -> None:
        assert client.get(SUMMARY).status_code == 401

    def test_user_without_workspace_is_all_zero(self, client: TestClient, db: Session) -> None:
        lonely = _make_user(db, "home_lonely")
        body = client.get(SUMMARY, headers=_login(client, lonely.username)).json()
        assert body == {
            "workspace_count": 0,
            "team_count": 0,
            "pending": {"change_requests": 0, "issues": 0, "link_requests": 0, "total": 0},
            "partial": False,
        }


class TestPendingCounts:
    def test_owner_sees_reviewable_requests_and_open_issues(self, client, env: Env) -> None:
        auth_viewer = _login(client, env.viewer.username)
        _submit_issue(client, env, auth_viewer, "问题一")
        _submit_issue(client, env, auth_viewer, "问题二")
        _submit_request(client, env, auth_viewer)

        body = client.get(SUMMARY, headers=_login(client, env.owner.username)).json()
        assert body["workspace_count"] == 1
        assert body["pending"] == {
            "change_requests": 1,
            "issues": 2,
            "link_requests": 0,
            "total": 3,
        }
        assert body["partial"] is False

    def test_viewer_cannot_review_so_change_requests_not_counted(self, client, env: Env) -> None:
        auth_viewer = _login(client, env.viewer.username)
        _submit_issue(client, env, auth_viewer)
        _submit_request(client, env, auth_viewer)

        body = client.get(SUMMARY, headers=auth_viewer).json()
        # viewer 没有审批资格（非 owner/editor 直编）→ 修改申请不计入；问题照常计入
        assert body["pending"]["change_requests"] == 0
        assert body["pending"]["issues"] == 1
        assert body["pending"]["total"] == 1

    def test_own_submitted_request_not_counted(self, client, env: Env) -> None:
        auth_owner = _login(client, env.owner.username)
        _submit_request(client, env, auth_owner, "我自己提的")

        body = client.get(SUMMARY, headers=auth_owner).json()
        assert body["pending"]["change_requests"] == 0

    def test_closed_issue_not_counted(self, client, env: Env) -> None:
        auth_owner = _login(client, env.owner.username)
        auth_viewer = _login(client, env.viewer.username)
        issue = _submit_issue(client, env, auth_viewer)
        _submit_issue(client, env, auth_viewer, "还开着")

        r = client.post(f"{ISSUES.format(ws=env.ws.id, tb=env.table.id)}/{issue['id']}/close", headers=auth_owner)
        assert r.status_code == 200, r.text

        body = client.get(SUMMARY, headers=auth_owner).json()
        assert body["pending"]["issues"] == 1

    def test_invisible_workspace_does_not_contribute(self, client, env: Env) -> None:
        auth_outsider = _login(client, env.outsider.username)
        # outsider 的私有工作区里有 open 问题（viewer 是该私有工作区成员但不是 owner）
        r = client.post(
            ISSUES.format(ws=env.private_ws.id, tb=env.private_table.id),
            json={"title": "私有区问题"},
            headers=auth_outsider,
        )
        assert r.status_code == 201, r.text

        owner_body = client.get(SUMMARY, headers=_login(client, env.owner.username)).json()
        assert owner_body["pending"]["issues"] == 0
        assert owner_body["workspace_count"] == 1

        # 私有工作区的非 owner 成员：列表与待办口径都不可见（D6）
        viewer_body = client.get(SUMMARY, headers=_login(client, env.viewer.username)).json()
        assert viewer_body["workspace_count"] == 1
        assert viewer_body["pending"]["issues"] == 0

        # outsider 自己能看到自己的私有工作区
        outsider_body = client.get(SUMMARY, headers=auth_outsider).json()
        assert outsider_body["workspace_count"] == 1
        assert outsider_body["pending"]["issues"] == 1

    def test_pending_link_counted_for_source_owner_only(self, client, db: Session, env: Env) -> None:
        consumer_owner = _make_user(db, "home_consumer_owner")
        consumer = Workspace(name="消费方", created_by_id=consumer_owner.id)
        db.add(consumer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=consumer.id, user_id=consumer_owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(consumer)

        auth_consumer = _login(client, consumer_owner.username)
        r = client.post(
            LINKS.format(wid=consumer.id),
            json={"source_workspace_id": env.ws.id, "target_table_id": env.table.id, "ttl_days": 30},
            headers=auth_consumer,
        )
        assert r.status_code == 201, r.text

        # 源工作区 owner 有 MANAGE_LINKS → 待审链接计入
        source_body = client.get(SUMMARY, headers=_login(client, env.owner.username)).json()
        assert source_body["pending"]["link_requests"] == 1
        # 消费方不算（审批发生在源工作区）
        consumer_body = client.get(SUMMARY, headers=auth_consumer).json()
        assert consumer_body["pending"]["link_requests"] == 0

    def test_team_count(self, client, db: Session, env: Env) -> None:
        team = Team(name="主页团队", slug="home-team", created_by_id=env.owner.id)
        db.add(team)
        db.flush()
        env.ws.team_id = team.id
        db.commit()

        body = client.get(SUMMARY, headers=_login(client, env.owner.username)).json()
        assert body["team_count"] == 1


class TestPayloadAndCache:
    def test_payload_whitelist_has_no_ids_or_names(self, client, env: Env) -> None:
        auth_viewer = _login(client, env.viewer.username)
        _submit_issue(client, env, auth_viewer)

        body = client.get(SUMMARY, headers=_login(client, env.owner.username)).json()
        assert set(body) == {"workspace_count", "team_count", "pending", "partial"}
        assert set(body["pending"]) == {"change_requests", "issues", "link_requests", "total"}
        raw = client.get(SUMMARY, headers=_login(client, env.owner.username)).text
        assert "主页待办工作区" not in raw
        assert "问题" not in raw

    def test_cache_hit_then_invalidated_by_write_path(self, client, db: Session, env: Env) -> None:
        auth_owner = _login(client, env.owner.username)
        assert client.get(SUMMARY, headers=auth_owner).json()["pending"]["issues"] == 0

        # 直接落库（绕过服务层，不触发失效）→ 第二次仍读到缓存值
        db.add(
            Issue(
                workspace_id=env.ws.id,
                table_id=env.table.id,
                title="直接插入",
                description="",
                category="other",
                status=ISSUE_STATUS_OPEN,
                created_by_id=env.viewer.id,
            )
        )
        db.commit()
        assert client.get(SUMMARY, headers=auth_owner).json()["pending"]["issues"] == 0

        # 走 API 写入 → 服务层失效缓存 → 计数立刻生效
        _submit_issue(client, env, _login(client, env.viewer.username), "走接口")
        assert client.get(SUMMARY, headers=auth_owner).json()["pending"]["issues"] == 2


class TestDegradation:
    def test_single_workspace_failure_degrades_to_partial(self, client, env: Env, monkeypatch) -> None:
        def _boom(*_args, **_kwargs):
            raise RuntimeError("统计炸了")

        monkeypatch.setattr(home_service, "_workspace_pending", _boom)

        r = client.get(SUMMARY, headers=_login(client, env.owner.username))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["partial"] is True
        assert body["pending"]["total"] == 0
        assert body["workspace_count"] == 1
