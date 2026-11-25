"""ADR 0158 P0：链接作为分析数据源（判定层 + 接口层）.

锁定口径：
- 不新增授权面（L1 / H53）：链接读数与只读网格同权，失效 404、无读权 403；
- 每次执行重新解析链接（过期 / 撤回立即生效，缓存不兜底）；
- 隐藏字段不得进入公式 / 返回字段（H17 / C3）；
- 行级读范围照旧（H15）：规则外行不计入聚合；
- 单一数据源：`source` 与 `table_id` 同传 → 422。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import TablePermission
from cndb.plugins.workspaces.models import (
    Workspace,
    WorkspaceLink,
    WorkspaceMember,
    WorkspaceRole,
)

WS = "/api/v1/workspaces"
LINKS = "/api/v1/workspaces/{wid}/links"
ANALYTICS = "/api/v1/workspaces/{wid}/analytics"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    """源工作区（owner）与消费方工作区（owner），一张源表 + 三行数据。"""

    def __init__(self, db: Session) -> None:
        self.source_owner = _user(db, "al_src_owner")
        self.consumer_owner = _user(db, "al_con_owner")
        self.outsider = _user(db, "al_outsider")

        self.source = Workspace(name="分析源", created_by_id=self.source_owner.id)
        self.consumer = Workspace(name="分析消费方", created_by_id=self.consumer_owner.id)
        db.add_all([self.source, self.consumer])
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.source.id, user_id=self.source_owner.id, role=WorkspaceRole.OWNER))
        db.add(WorkspaceMember(workspace_id=self.consumer.id, user_id=self.consumer_owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(self.source)
        db.refresh(self.consumer)


@pytest.fixture()
def env(db: Session) -> Env:
    return Env(db)


def _setup_source_table(client: TestClient, env: Env) -> tuple[int, dict[str, str]]:
    auth = _login(client, env.source_owner.username)
    tid = client.post(f"{WS}/{env.source.id}/tables", json={"name": "销售"}, headers=auth).json()["id"]
    for order, (name, ftype) in enumerate((("名称", "text"), ("金额", "number"), ("状态", "text"))):
        r = client.post(
            f"{WS}/{env.source.id}/tables/{tid}/fields",
            json={"name": name, "field_type": ftype, "order": order},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    for name, amount, status in (("甲", 10, "public"), ("乙", 20, "secret"), ("丙", 30, "public")):
        r = client.post(
            f"{WS}/{env.source.id}/tables/{tid}/records",
            json={"values": {"名称": name, "金额": amount, "状态": status}},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    return tid, auth


def _approve_link(client: TestClient, env: Env, table_id: int, *, ttl_days: int = 30) -> dict:
    con_auth = _login(client, env.consumer_owner.username)
    link = client.post(
        LINKS.format(wid=env.consumer.id),
        json={"source_workspace_id": env.source.id, "target_table_id": table_id, "ttl_days": ttl_days},
        headers=con_auth,
    ).json()
    src_auth = _login(client, env.source_owner.username)
    r = client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={}, headers=src_auth)
    assert r.status_code == 200, r.text
    return r.json()


def _compute(client: TestClient, env: Env, auth: dict[str, str], body: dict):
    return client.post(f"{ANALYTICS.format(wid=env.consumer.id)}/compute", json=body, headers=auth)


class TestDatasources:
    def test_lists_tables_and_active_links(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)
        client.post(f"{WS}/{env.consumer.id}/tables", json={"name": "本地表"}, headers=con_auth)

        r = client.get(f"{ANALYTICS.format(wid=env.consumer.id)}/datasources", headers=con_auth)
        assert r.status_code == 200, r.text
        body = r.json()
        assert [t["name"] for t in body["tables"]] == ["本地表"]
        assert [link_item["name"] for link_item in body["links"]] == ["销售"]
        item = body["links"][0]
        assert item["link_id"] == link["id"]
        assert item["source_workspace_name"] == "分析源"
        assert item["readable"] is True
        assert item["expires_at"] is not None

    def test_expired_and_pending_links_not_listed(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        con_auth = _login(client, env.consumer_owner.username)
        # pending（未批准）
        client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.source.id, "target_table_id": tid},
            headers=con_auth,
        )
        # active 但已过期
        link = _approve_link(client, env, tid)
        stored = db.get(WorkspaceLink, link["id"])
        stored.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
        db.commit()

        body = client.get(f"{ANALYTICS.format(wid=env.consumer.id)}/datasources", headers=con_auth).json()
        assert body["links"] == []

    def test_unreadable_link_is_listed_but_flagged(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        # 撤销后重新建一条 active 但用户不可读（模拟：把链接创建的成员踢掉）
        db.query(WorkspaceMember).filter(
            WorkspaceMember.workspace_id == env.source.id,
            WorkspaceMember.user_id == env.consumer_owner.id,
        ).delete()
        db.commit()
        con_auth = _login(client, env.consumer_owner.username)
        body = client.get(f"{ANALYTICS.format(wid=env.consumer.id)}/datasources", headers=con_auth).json()
        assert [item["id"] for item in body["links"]] == [link["id"]]
        assert body["links"][0]["readable"] is False

    def test_non_member_forbidden(self, client, db, env):
        r = client.get(
            f"{ANALYTICS.format(wid=env.consumer.id)}/datasources",
            headers=_login(client, env.outsider.username),
        )
        assert r.status_code in (403, 404)


class TestComputeWithLink:
    def _body(self, link_id: int, **extra) -> dict:
        return {
            "source": {"type": "link", "link_id": link_id},
            "formulas": [{"key": "金额合计", "expr": "sum([金额])"}],
            **extra,
        }

    def test_compute_uses_link_rows(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)

        r = _compute(client, env, con_auth, self._body(link["id"]))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 3
        assert {row.get("名称") for row in body["rows"]} == {"甲", "乙", "丙"}
        # sum 公式对三行都成立
        assert all(row.get("金额合计") == 60 for row in body["rows"])

    def test_unknown_or_expired_link_is_404(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)

        assert _compute(client, env, con_auth, self._body(999999)).status_code == 404

        stored = db.get(WorkspaceLink, link["id"])
        stored.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
        db.commit()
        assert _compute(client, env, con_auth, self._body(link["id"])).status_code == 404

    def test_revoked_link_is_404(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)
        assert client.delete(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}", headers=con_auth).status_code == 204
        assert _compute(client, env, con_auth, self._body(link["id"])).status_code == 404

    def test_without_source_read_permission_is_403(self, client, db, env):
        """链接 active 但用户对源工作区无 READ（如批准后才加入消费方的人）→ 403."""
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        late = _user(db, "al_late")
        db.add(WorkspaceMember(workspace_id=env.consumer.id, user_id=late.id, role=WorkspaceRole.VIEWER))
        db.commit()

        r = _compute(client, env, _login(client, late.username), self._body(link["id"]))
        assert r.status_code == 403, r.text
        assert "链接为只读引用" in r.json()["detail"]

    def test_hidden_field_rejected(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        db.add(TablePermission(table_id=tid, hidden_fields={"viewer": ["金额"]}))
        db.commit()
        con_auth = _login(client, env.consumer_owner.username)

        r = _compute(client, env, con_auth, self._body(link["id"]))
        assert r.status_code == 400, r.text
        assert "字段不可用于该数据源" in r.json()["detail"]

    def test_hidden_field_in_returned_fields_rejected(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        db.add(TablePermission(table_id=tid, hidden_fields={"viewer": ["状态"]}))
        db.commit()
        con_auth = _login(client, env.consumer_owner.username)

        body = {"source": {"type": "link", "link_id": link["id"]}, "fields": ["状态"], "formulas": []}
        assert _compute(client, env, con_auth, body).status_code == 400

    def test_row_level_scope_still_applies(self, client, db, env):
        """行级读范围（H15）在链接数据源上同样生效：默认档外行不计入聚合."""
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        db.add(
            TablePermission(
                table_id=tid,
                row_filters=[{"field_name": "状态", "op": "eq", "value": "public"}],
                row_filter_type="AND",
            )
        )
        db.commit()
        con_auth = _login(client, env.consumer_owner.username)

        body = _compute(client, env, con_auth, self._body(link["id"]))
        assert body.status_code == 200, body.text
        payload = body.json()
        assert payload["total"] == 2
        assert {row.get("名称") for row in payload["rows"]} == {"甲", "丙"}
        assert all(row.get("金额合计") == 40 for row in payload["rows"])

    def test_link_view_filters_are_default(self, client, db, env):
        tid, source_auth = _setup_source_table(client, env)
        view = client.post(
            f"{WS}/{env.source.id}/tables/{tid}/views",
            json={
                "name": "只看公开",
                "view_type": "grid",
                "filters": [{"field_name": "状态", "op": "eq", "value": "public"}],
            },
            headers=source_auth,
        )
        assert view.status_code in (200, 201), view.text
        con_auth = _login(client, env.consumer_owner.username)
        link = client.post(
            LINKS.format(wid=env.consumer.id),
            json={
                "source_workspace_id": env.source.id,
                "target_table_id": tid,
                "target_view_id": view.json()["id"],
            },
            headers=con_auth,
        ).json()
        client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={}, headers=source_auth)

        r = _compute(client, env, con_auth, self._body(link["id"]))
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 2

    def test_both_source_and_table_id_rejected(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)
        body = self._body(link["id"])
        body["table_id"] = tid
        assert _compute(client, env, con_auth, body).status_code == 422

    def test_table_source_compatibility_unchanged(self, client, db, env):
        """L6 存量不变：只传 table_id 的老请求行为不变."""
        tid, _ = _setup_source_table(client, env)
        body = {"table_id": tid, "formulas": [{"key": "合计", "expr": "sum([金额])"}]}
        r = client.post(
            f"{ANALYTICS.format(wid=env.source.id)}/compute",
            json=body,
            headers=_login(client, env.source_owner.username),
        )
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 3


class TestTemplateSource:
    """ADR 0158 P1：模板可保存链接数据源，字段白名单取链接可见字段."""

    def _template_body(self, link_id: int, **extra) -> dict:
        return {
            "name": "跨部门汇总",
            "config": {
                "source": {"type": "link", "link_id": link_id},
                "formulas": [{"key": "合计", "expr": "sum([金额])"}],
            },
            **extra,
        }

    def test_create_template_with_link_source(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)

        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/templates",
            json=self._template_body(link["id"]),
            headers=con_auth,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["config"]["source"] == {"type": "link", "link_id": link["id"]}
        # table_id 落源表 id（旧消费方展示用）
        assert body["table_id"] == tid

        listed = client.get(f"{ANALYTICS.format(wid=env.consumer.id)}/templates", headers=con_auth).json()
        assert listed[0]["config"]["source"]["link_id"] == link["id"]

    def test_template_with_link_validates_hidden_field(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        db.add(TablePermission(table_id=tid, hidden_fields={"viewer": ["金额"]}))
        db.commit()
        con_auth = _login(client, env.consumer_owner.username)

        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/templates",
            json=self._template_body(link["id"]),
            headers=con_auth,
        )
        assert r.status_code == 400, r.text
        assert "金额" in r.json()["detail"]

    def test_template_with_revoked_link_rejected_at_save(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)
        client.delete(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}", headers=con_auth)

        r = client.post(
            f"{ANALYTICS.format(wid=env.consumer.id)}/templates",
            json=self._template_body(link["id"]),
            headers=con_auth,
        )
        assert r.status_code == 404, r.text

    def test_template_legacy_table_id_config_unchanged(self, client, db, env):
        """L6：不带 source 的旧配置行为不变（仍按 table_id 校验）。"""
        tid, _ = _setup_source_table(client, env)
        auth = _login(client, env.source_owner.username)
        r = client.post(
            f"{ANALYTICS.format(wid=env.source.id)}/templates",
            json={
                "name": "本表模板",
                "table_id": tid,
                "config": {"formulas": [{"key": "合计", "expr": "sum([金额])"}]},
            },
            headers=auth,
        )
        assert r.status_code == 201, r.text
        assert "source" not in r.json()["config"]


class TestRecommendationsWithLink:
    def test_link_recommendations(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)

        r = client.get(
            f"{ANALYTICS.format(wid=env.consumer.id)}/recommendations",
            params={"link_id": link["id"]},
            headers=con_auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["row_count"] == 3
        names = {f["name"] for f in body["fields"]}
        assert {"名称", "金额", "状态"} <= names

    def test_link_recommendations_hide_hidden_fields(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        db.add(TablePermission(table_id=tid, hidden_fields={"viewer": ["金额"]}))
        db.commit()
        con_auth = _login(client, env.consumer_owner.username)

        body = client.get(
            f"{ANALYTICS.format(wid=env.consumer.id)}/recommendations",
            params={"link_id": link["id"]},
            headers=con_auth,
        ).json()
        assert "金额" not in {f["name"] for f in body["fields"]}

    def test_link_recommendations_fail_closed(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        late = _user(db, "al_rec_late")
        db.add(WorkspaceMember(workspace_id=env.consumer.id, user_id=late.id, role=WorkspaceRole.VIEWER))
        db.commit()
        r = client.get(
            f"{ANALYTICS.format(wid=env.consumer.id)}/recommendations",
            params={"link_id": link["id"]},
            headers=_login(client, late.username),
        )
        assert r.status_code == 403

    def test_both_sources_rejected(self, client, db, env):
        tid, _ = _setup_source_table(client, env)
        link = _approve_link(client, env, tid)
        r = client.get(
            f"{ANALYTICS.format(wid=env.consumer.id)}/recommendations",
            params={"table_id": tid, "link_id": link["id"]},
            headers=_login(client, env.consumer_owner.username),
        )
        assert r.status_code == 400
