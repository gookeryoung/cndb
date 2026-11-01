"""跨工作区统一检索（主页顶栏搜索框）—— ``GET /api/v1/search``（需求 0081 C3）.

覆盖口径：
1. 只扫当前用户所属的工作区：多工作区命中合并且每项带 workspace_id / workspace_name，
   非成员工作区的内容不出现；
2. pinned 工作区排在前面（与工作区列表顺序一致）；
3. 空白关键词返回空结果；
4. 未登录 401。
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


@pytest.fixture
def owner(db) -> User:
    u = User(username="gsp_owner", nickname="GSP Owner")
    u.set_password("pw")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "pw"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_ws(db, owner: User, name: str, *, pinned: bool = False) -> Workspace:
    w = Workspace(name=name, created_by_id=owner.id)
    db.add(w)
    db.flush()
    member = WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER)
    member.pinned = pinned
    db.add(member)
    db.commit()
    db.refresh(w)
    return w


def _make_table(db, ws: Workspace, owner: User, name: str) -> DataTable:
    dt = DataTable(workspace_id=ws.id, name=name, owner_id=owner.id)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="名称", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db.get_bind(), dt)
    return dt


def _add_row(client, ws: Workspace, table: DataTable, auth: dict, name: str) -> None:
    r = client.post(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
        json={"values": {"名称": name}},
        headers=auth,
    )
    assert r.status_code in (200, 201), r.text


def _add_doc(client, ws: Workspace, auth: dict, title: str) -> None:
    r = client.post(
        f"/api/v1/workspaces/{ws.id}/documents",
        json={"title": title, "content": "正文内容"},
        headers=auth,
    )
    assert r.status_code == 201, r.text


def _search_global(client, auth: dict, q: str, **params) -> dict:
    r = client.get("/api/v1/search", params={"q": q, **params}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


class TestGlobalSearch:
    def test_merges_hits_across_member_workspaces_with_workspace_ref(self, client, db, owner, auth):
        """两个工作区各有一条命中行：合并返回且逐项带工作区标识（C3）."""
        ws_a = _make_ws(db, owner, "工作区甲")
        ws_b = _make_ws(db, owner, "工作区乙")
        t_a = _make_table(db, ws_a, owner, "甲清单")
        t_b = _make_table(db, ws_b, owner, "乙清单")
        _add_row(client, ws_a, t_a, auth, "华东客户甲")
        _add_row(client, ws_b, t_b, auth, "华东客户乙")
        _add_doc(client, ws_b, auth, "华东客户复盘")

        data = _search_global(client, auth, "华东")
        assert sorted(r["title"] for r in data["rows"]) == ["华东客户乙", "华东客户甲"]
        by_title = {r["title"]: r for r in data["rows"]}
        assert by_title["华东客户甲"]["workspace_id"] == ws_a.id
        assert by_title["华东客户甲"]["workspace_name"] == "工作区甲"
        assert by_title["华东客户乙"]["workspace_id"] == ws_b.id
        assert [d["title"] for d in data["documents"]] == ["华东客户复盘"]
        assert data["documents"][0]["workspace_id"] == ws_b.id

    def test_non_member_workspace_not_searched(self, client, db, owner, auth):
        """非成员工作区的内容不参与全局检索（权限口径 = 工作区列表口径）."""
        ws_mine = _make_ws(db, owner, "我的工作区")
        t_mine = _make_table(db, ws_mine, owner, "我的清单")
        _add_row(client, ws_mine, t_mine, auth, "全局命中词甲")

        outsider = User(username="gsp_other", email="gsp_other@example.com")
        outsider.set_password("pw")
        db.add(outsider)
        db.commit()
        ws_other = _make_ws(db, outsider, "别人的工作区")
        t_other = _make_table(db, ws_other, outsider, "别人清单")
        _add_row(
            client,
            ws_other,
            t_other,
            {"Authorization": _login(client, outsider)},
            "全局命中词乙",
        )

        data = _search_global(client, auth, "全局命中词")
        assert [r["title"] for r in data["rows"]] == ["全局命中词甲"]

    def test_pinned_workspace_hits_first(self, client, db, owner, auth):
        """pinned 工作区的命中排在前面（与主页工作区列表顺序一致）."""
        ws_plain = _make_ws(db, owner, "普通工作区")
        ws_pinned = _make_ws(db, owner, "收藏工作区", pinned=True)
        t_plain = _make_table(db, ws_plain, owner, "普通清单")
        t_pinned = _make_table(db, ws_pinned, owner, "收藏清单")
        _add_row(client, ws_plain, t_plain, auth, "排序命中词甲")
        _add_row(client, ws_pinned, t_pinned, auth, "排序命中词乙")

        data = _search_global(client, auth, "排序命中词")
        assert [r["workspace_name"] for r in data["rows"]] == ["收藏工作区", "普通工作区"]

    def test_global_limit_caps_each_group(self, client, db, owner, auth):
        """limit 收敛各组命中数（文档 / 表名 / 行同口径）."""
        ws = _make_ws(db, owner, "限额工作区")
        for i in range(4):
            t = _make_table(db, ws, owner, f"限额表{i}")
            _add_row(client, ws, t, auth, f"限额命中行{i}")

        data = _search_global(client, auth, "限额", limit=2)
        assert len(data["tables"]) <= 2
        assert len(data["rows"]) == 2

    def test_blank_query_returns_empty(self, client, owner, auth):
        data = _search_global(client, auth, "   ")
        assert data == {"query": "", "documents": [], "tables": [], "rows": []}

    def test_requires_auth(self, client, owner):
        r = client.get("/api/v1/search", params={"q": "任意"})
        assert r.status_code == 401


def _login(client, user: User) -> str:
    r = client.post("/api/v1/accounts/auth/login", json={"login": user.username, "password": "pw"})
    assert r.status_code == 200, r.text
    return f"Bearer {r.json()['access_token']}"
