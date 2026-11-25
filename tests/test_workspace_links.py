"""ADR 0154 P1：链接只读取数（fields / rows / export）.

锁定口径：
- 权限 = 用户在**源工作区**的既有读权限（A 期：链接创建的 viewer），链接本身不授权（L1）；
- 行级规则（H15）与字段隐藏（H17）走与普通读**同一条**路径，链接不越权；
- 只挂 GET：对 rows 端点的写方法一律不可达（L2 / C4）；
- 失效（过期 / 未批准 / 目标表删）统一 404（L3 / L4）。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, TablePermission
from cndb.plugins.workspaces.models import Workspace, WorkspaceLink, WorkspaceMember, WorkspaceRole

WS = "/api/v1/workspaces"
LINKS = "/api/v1/workspaces/{wid}/links"


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
    def __init__(self, db: Session) -> None:
        self.source_owner = _user(db, "pl_src_owner")
        self.consumer_owner = _user(db, "pl_con_owner")
        self.late_member = _user(db, "pl_late_member")

        self.source = Workspace(name="链接源", created_by_id=self.source_owner.id)
        self.consumer = Workspace(name="链接消费方", created_by_id=self.consumer_owner.id)
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


def _setup_table(client: TestClient, env: Env) -> tuple[int, dict[str, str]]:
    """源工作区建一张表（名称 / 状态 / 秘密 三列）+ 三行数据，返回 (table_id, source_owner 头)."""
    auth = _login(client, env.source_owner.username)
    tid = client.post(f"{WS}/{env.source.id}/tables", json={"name": "销售明细"}, headers=auth).json()["id"]
    for order, (name, field_type) in enumerate((("名称", "text"), ("状态", "text"), ("秘密", "text"))):
        r = client.post(
            f"{WS}/{env.source.id}/tables/{tid}/fields",
            json={"name": name, "field_type": field_type, "order": order},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    for name, status in (("甲", "public"), ("乙", "secret"), ("丙", "public")):
        r = client.post(
            f"{WS}/{env.source.id}/tables/{tid}/records",
            json={"values": {"名称": name, "状态": status, "秘密": f"{name}-秘密"}},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    return tid, auth


def _approve_new_link(client: TestClient, env: Env, table_id: int, *, ttl_days: int = 30) -> dict:
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


def _row_names(payload: dict) -> list[str]:
    return [row.get("名称") for row in payload["rows"]]


class TestFieldsAndRows:
    def test_rows_are_readable_after_approval(self, client, db, env):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)

        fields = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/fields", headers=con_auth)
        assert fields.status_code == 200, fields.text
        assert [f["name"] for f in fields.json()["fields"]] == ["名称", "状态", "秘密"]

        rows = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=con_auth)
        assert rows.status_code == 200, rows.text
        body = rows.json()
        assert body["total"] == 3
        assert sorted(_row_names(body)) == ["丙", "乙", "甲"]

    def test_rows_filter_and_paging(self, client, db, env):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)

        rows = client.get(
            f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows",
            params={"filters": '[{"field_name": "状态", "op": "eq", "value": "public"}]'},
            headers=con_auth,
        )
        assert rows.status_code == 200, rows.text
        assert sorted(_row_names(rows.json())) == ["丙", "甲"]

        page = client.get(
            f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows",
            params={"limit": 1, "offset": 0},
            headers=con_auth,
        )
        assert len(page.json()["rows"]) == 1

    def test_invalid_query_params(self, client, db, env):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)
        base = f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows"
        assert client.get(base, params={"limit": 0}, headers=con_auth).status_code == 400
        assert client.get(base, params={"offset": -1}, headers=con_auth).status_code == 400
        assert client.get(base, params={"filter_logic": "XOR"}, headers=con_auth).status_code == 400
        # 坏 JSON 降级为「无筛选」而不是 400（与 records 端点同口径）
        assert client.get(base, params={"filters": "{oops"}, headers=con_auth).status_code == 200

    def test_write_methods_not_available(self, client, db, env):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)
        base = f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows"
        assert client.post(base, json={"values": {"名称": "x"}}, headers=con_auth).status_code == 405
        assert client.patch(base, json={}, headers=con_auth).status_code == 405
        assert client.delete(base, headers=con_auth).status_code == 405


class TestPermissionCeiling:
    def test_late_member_without_source_access_gets_403(self, client, db, env):
        """批准后才加入消费方的人不在受众里 → 源工作区无读权限 → 403（L1）."""
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        db.add(WorkspaceMember(workspace_id=env.consumer.id, user_id=env.late_member.id, role=WorkspaceRole.VIEWER))
        db.commit()

        late_auth = _login(client, env.late_member.username)
        r = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=late_auth)
        assert r.status_code == 403, r.text
        assert "链接为只读引用" in r.json()["detail"]

    def test_revoked_link_is_404(self, client, db, env):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)
        assert client.delete(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}", headers=con_auth).status_code == 204
        assert client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=con_auth).status_code == 404

    def test_expired_link_is_404(self, client, db, env):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        stored = db.get(WorkspaceLink, link["id"])
        stored.expires_at = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=5)
        db.commit()

        con_auth = _login(client, env.consumer_owner.username)
        assert client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=con_auth).status_code == 404
        # 过期链接也不出现在「可读」列表口径里
        listed = client.get(LINKS.format(wid=env.consumer.id), headers=con_auth).json()
        assert listed[0]["readable"] is False

    def test_pending_link_is_404(self, client, db, env):
        tid, _ = _setup_table(client, env)
        con_auth = _login(client, env.consumer_owner.username)
        link = client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.source.id, "target_table_id": tid},
            headers=con_auth,
        ).json()
        assert client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=con_auth).status_code == 404

    def test_trashed_target_table_is_404(self, client, db, env):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        table = db.get(DataTable, tid)
        table.trashed = True
        db.commit()
        con_auth = _login(client, env.consumer_owner.username)
        assert client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=con_auth).status_code == 404

    def test_hidden_fields_are_not_returned(self, client, db, env):
        """字段隐藏（H17）在链接读上同样生效."""
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        db.add(TablePermission(table_id=tid, hidden_fields={"viewer": ["秘密"]}))
        db.commit()

        con_auth = _login(client, env.consumer_owner.username)
        fields = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/fields", headers=con_auth).json()
        assert [f["name"] for f in fields["fields"]] == ["名称", "状态"]

        rows = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=con_auth).json()
        assert rows["rows"]
        assert all("秘密" not in row for row in rows["rows"])

        csv_text = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/export", headers=con_auth).text
        assert "秘密" not in csv_text.splitlines()[0]

    def test_row_level_scope_still_applies(self, client, db, env):
        """行级读范围（H15）在链接读上同样生效：默认档外的行不可见.

        注意 ADR 0004 §7-5：规则本身只做**并集放宽**，收窄必须来自默认档
        （`TablePermission.row_filters`），因此这里用默认档构造读范围。
        """
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        db.add(
            TablePermission(
                table_id=tid,
                row_filters=[{"field_name": "状态", "op": "eq", "value": "public"}],
                row_filter_type="AND",
            )
        )
        db.commit()

        con_auth = _login(client, env.consumer_owner.username)
        rows = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=con_auth).json()
        assert sorted(_row_names(rows)) == sorted(["丙", "甲"])
        assert rows["total"] == 2


class TestExport:
    def test_csv_export_contains_rows_and_header(self, client, db, env):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        con_auth = _login(client, env.consumer_owner.username)

        r = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/export", headers=con_auth)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/csv")
        assert "attachment" in r.headers["content-disposition"]
        text = r.content.decode("utf-8-sig")
        lines = [line for line in text.splitlines() if line.strip()]
        assert lines[0].split(",")[:3] == ["名称", "状态", "秘密"]
        assert len(lines) == 4  # 表头 + 3 行

    def test_export_rejected_when_over_cap(self, client, db, env, monkeypatch):
        tid, _ = _setup_table(client, env)
        link = _approve_new_link(client, env, tid)
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "EXPORT_MAX_ROWS", 1)
        con_auth = _login(client, env.consumer_owner.username)
        r = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/export", headers=con_auth)
        assert r.status_code == 400
        assert "EXPORT_MAX_ROWS" in r.json()["detail"]


class TestViewScopedLink:
    def test_view_filters_and_sorts_are_default(self, client, db, env):
        tid, source_auth = _setup_table(client, env)
        view = client.post(
            f"{WS}/{env.source.id}/tables/{tid}/views",
            json={
                "name": "只看公开",
                "view_type": "grid",
                "filters": [{"field_name": "状态", "op": "eq", "value": "public"}],
                "sortings": [{"field_name": "名称", "direction": "desc"}],
            },
            headers=source_auth,
        )
        assert view.status_code in (200, 201), view.text
        view_id = view.json()["id"]

        con_auth = _login(client, env.consumer_owner.username)
        link = client.post(
            LINKS.format(wid=env.consumer.id),
            json={"source_workspace_id": env.source.id, "target_table_id": tid, "target_view_id": view_id},
            headers=con_auth,
        ).json()
        src_auth = _login(client, env.source_owner.username)
        client.post(f"{LINKS.format(wid=env.source.id)}/{link['id']}/approve", json={}, headers=src_auth)

        rows = client.get(f"{LINKS.format(wid=env.consumer.id)}/{link['id']}/rows", headers=con_auth).json()
        names = _row_names(rows)
        # 视图筛选生效（只剩 public 两行）；排序按 direction=desc 生效
        # 顺序按 SQLite 默认码点序比较，不假设拼音序
        assert names == sorted(["甲", "丙"], reverse=True)
        assert rows["total"] == 2
        assert rows["target_type"] == "view"
