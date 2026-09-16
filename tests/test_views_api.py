"""DataView 视图端点测试."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.tables import ddl
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole


@pytest.fixture
def db(tmp_path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "views.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def owner(db):
    u = User(username="v_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    from cndb.plugins.workspaces.models import WorkspaceMember

    w = Workspace(name="VWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="VTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


class TestViewsAPI:
    def test_create_view(self, client, ws, table, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "默认表格", "view_type": "grid", "is_default": True},
            headers=auth_owner,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "默认表格"
        assert data["view_type"] == "grid"
        assert data["is_default"] is True

    def test_list_views(self, client, ws, table, auth_owner):
        # 先创建两个
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "Grid1", "view_type": "grid"},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "Kanban1", "view_type": "kanban"},
            headers=auth_owner,
        )
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_get_view_detail(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "DetailView", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "DetailView"

    def test_update_view(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "OldName", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}",
            json={"name": "NewName", "is_default": True},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "NewName"
        assert r.json()["is_default"] is True

    def test_delete_view(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "ToDelete", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}",
            headers=auth_owner,
        )
        assert r.status_code == 204

    def test_create_view_duplicate_name(self, client, ws, table, auth_owner):
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "Dup", "view_type": "grid"},
            headers=auth_owner,
        )
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "Dup", "view_type": "kanban"},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_get_view_not_found(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_update_view_not_found(self, client, ws, table, auth_owner):
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999",
            json={"name": "x"},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_delete_view_not_found(self, client, ws, table, auth_owner):
        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_create_view_set_default_replaces_others(self, client, ws, table, auth_owner):
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "V1", "is_default": True},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "V2", "is_default": True},
            headers=auth_owner,
        )
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            headers=auth_owner,
        )
        views = r.json()
        defaults = [v for v in views if v["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["name"] == "V2"

    def test_get_view_rows(self, client, ws, table, auth_owner):
        # 先创建视图
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "RowView", "view_type": "grid", "sortings": [{"field_name": "姓名", "direction": "asc"}]},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/rows?limit=10",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert "rows" in r.json()
        assert "total" in r.json()

    def test_get_view_rows_not_found(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999/rows",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_get_view_kanban_no_group_field(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "NoGroupKanban", "view_type": "kanban", "view_options": {}},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/kanban",
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_get_view_kanban(self, client, ws, table, auth_owner):
        # 先加字段，再创建视图，然后加数据

        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
            json={"name": "状态", "field_type": "text", "order": 1},
            headers=auth_owner,
        )
        # 重新从 test client 获取
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "KanbanView",
                "view_type": "kanban",
                "view_options": {"group_field": "状态"},
            },
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/kanban",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert "columns" in r.json()
        assert r.json()["group_field"] == "状态"

    def test_get_view_kanban_not_found(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999/kanban",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_get_view_calendar_no_start_field(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "NoStartCal", "view_type": "calendar", "view_options": {}},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/calendar",
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_get_view_calendar(self, client, ws, table, auth_owner):
        # 先加 date 字段，再创建视图
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
            json={"name": "截止日期", "field_type": "date", "order": 1},
            headers=auth_owner,
        )
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "CalendarView",
                "view_type": "calendar",
                "view_options": {"start_field": "截止日期"},
            },
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/calendar",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert "rows" in r.json()
        assert r.json()["start_field"] == "截止日期"

    def test_get_view_calendar_with_date_range(self, client, ws, table, auth_owner):
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
            json={"name": "截止日期", "field_type": "date", "order": 1},
            headers=auth_owner,
        )
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "CalRange",
                "view_type": "calendar",
                "view_options": {"start_field": "截止日期"},
            },
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/calendar?start=2024-01-01&end=2024-12-31",
            headers=auth_owner,
        )
        assert r.status_code == 200

    def test_get_view_calendar_not_found(self, client, ws, table, auth_owner):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999/calendar",
            headers=auth_owner,
        )
        assert r.status_code == 404

    # ── P4 公开分享测试 ──

    def test_create_view_share(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "ShareView", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["is_public"] is True
        assert data["slug"]
        assert "share_url" in data

    def test_create_form_share(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "FormView", "view_type": "form"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["form_url"]

    def test_create_view_share_not_found(self, client, ws, table, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999/share",
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_revoke_view_share(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "ShareRevoke", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["is_public"] is False

    def test_public_share_view(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "PubShare", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        share_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        slug = share_r.json()["slug"]
        r = client.get(f"/api/v1/public/share/{slug}")
        assert r.status_code == 200
        assert "rows" in r.json()
        assert "total" in r.json()

    def test_public_share_invalid_slug(self, client, ws, table, auth_owner):
        r = client.get("/api/v1/public/share/nonexistentslug12")
        assert r.status_code == 404

    def test_public_form_submit(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "PubForm", "view_type": "form"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        share_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        slug = share_r.json()["slug"]
        r = client.post(f"/api/v1/public/forms/{slug}", json={"姓名": "匿名提交"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_public_form_view(self, client, ws, table, auth_owner):
        """覆盖 GET /forms/{slug} —— 返回表结构供前端渲染表单."""
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "PubFormView", "view_type": "form"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        share_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        slug = share_r.json()["slug"]
        r = client.get(f"/api/v1/public/forms/{slug}")
        assert r.status_code == 200
        data = r.json()
        assert "view" in data
        assert "table" in data
        assert data["table"]["fields"]
        assert len(data["table"]["fields"]) > 0
        # 字段应按默认顺序返回
        field_names = [f["name"] for f in data["table"]["fields"]]
        assert "姓名" in field_names

    def test_public_form_view_invalid_slug(self, client, ws, table, auth_owner):
        r = client.get("/api/v1/public/forms/nonexistentslug99")
        assert r.status_code == 404

    def test_public_form_view_not_form_type(self, client, ws, table, auth_owner):
        """GET /forms/{slug} 对非 form 视图应返回 400."""
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "NotFormView", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        share_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        slug = share_r.json()["slug"]
        r = client.get(f"/api/v1/public/forms/{slug}")
        assert r.status_code == 400

    def test_public_form_not_form_type(self, client, ws, table, auth_owner):
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "NotForm", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        share_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/share",
            headers=auth_owner,
        )
        slug = share_r.json()["slug"]
        r = client.post(f"/api/v1/public/forms/{slug}", json={"姓名": "x"})
        assert r.status_code == 400

    # ── 覆盖遗漏分支 ──

    def test_update_view_without_is_default(self, client, ws, table, auth_owner):
        """update_view 不传 is_default 时条件为 False，跳过清 default 分支."""
        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "VNoDefault", "view_type": "grid", "is_default": True},
            headers=auth_owner,
        )
        vid = create_r.json()["id"]
        # 只更新 name，不传 is_default —— 覆盖 if payload.is_default: 的 False 分支
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}",
            json={"name": "Renamed"},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "Renamed"
        assert r.json()["is_default"] is True

    def test_get_view_kanban_with_rows(self, client, ws, table, auth_owner):
        """kanban 有实际行数据时进入 for row in rows 循环，覆盖 line 204-205."""
        # 先加状态字段
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
            json={"name": "状态", "field_type": "text", "order": 1},
            headers=auth_owner,
        )

        create_r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "KanbanWithRows",
                "view_type": "kanban",
                "view_options": {"group_field": "状态"},
            },
            headers=auth_owner,
        )
        vid = create_r.json()["id"]

        # 使用 records API 插行（values 字段）
        row1 = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
            headers=auth_owner,
            json={"values": {"姓名": "张三", "状态": "进行中"}},
        )
        row2 = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
            headers=auth_owner,
            json={"values": {"姓名": "李四", "状态": None}},
        )
        assert row1.status_code in (200, 201), f"row1 failed: {row1.text}"
        assert row2.status_code in (200, 201), f"row2 failed: {row2.text}"

        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/kanban",
            headers=auth_owner,
        )
        assert r.status_code == 200
        cols = r.json()["columns"]
        assert "进行中" in cols
        assert "未分组" in cols

    def test_revoke_view_share_not_found(self, client, ws, table, auth_owner):
        """revoke 不存在的 view 应返回 404（覆盖 line 298）."""
        r = client.delete(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/99999/share",
            headers=auth_owner,
        )
        assert r.status_code == 404


class TestKanbanEnhanced:
    """看板增强：group_order + ungrouped_label + 返回字段."""

    def test_kanban_group_order(self, client, ws, table, auth_owner):
        """按 group_order 排序分组，未列出的追加末尾，ungrouped 自动放最后."""
        # 建字段
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
            json={"name": "状态", "field_type": "text", "order": 1},
            headers=auth_owner,
        )
        # 建视图 + group_order
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "KanbanOrdered",
                "view_type": "kanban",
                "view_options": {
                    "group_field": "状态",
                    "group_order": ["待办", "进行中", "已完成"],
                    "ungrouped_label": "未设置",
                },
            },
            headers=auth_owner,
        )
        vid = r.json()["id"]

        # 插数据
        for val in ["进行中", "待办", "已完成", "阻塞", None]:
            client.post(
                f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
                headers=auth_owner,
                json={"values": {"姓名": f"row-{val}", "状态": val}},
            )

        resp = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/kanban",
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        # group_order 字段存在
        assert body["group_order"] == ["待办", "进行中", "已完成", "阻塞", "未设置"]
        assert body["ungrouped_label"] == "未设置"
        # columns key 顺序匹配
        assert list(body["columns"].keys()) == ["待办", "进行中", "已完成", "阻塞", "未设置"]
        # ungrouped（None）在最后
        assert body["columns"]["未设置"][0]["状态"] is None

    def test_kanban_empty_group_order_default_sort(self, client, ws, table, auth_owner):
        """group_order 为空列表 → 保持 defaultdict 自然顺序."""
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
            json={"name": "状态", "field_type": "text", "order": 1},
            headers=auth_owner,
        )
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "KanbanNoOrder",
                "view_type": "kanban",
                "view_options": {"group_field": "状态", "group_order": []},
            },
            headers=auth_owner,
        )
        vid = r.json()["id"]

        for val in ["B", "A", "C"]:
            client.post(
                f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
                headers=auth_owner,
                json={"values": {"姓名": f"r-{val}", "状态": val}},
            )

        resp = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/{vid}/kanban",
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["group_order"] == ["B", "A", "C"]


class TestViewValidation:
    """视图字段校验覆盖：filter / sorting / view_options 各分支."""

    def test_filter_field_not_found(self, client, ws, table, auth_owner):
        """filter 引用不存在的字段 → 400（覆盖 _validate_view_fields filter 分支）."""
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "BadFilter",
                "view_type": "grid",
                "filters": [{"field_name": "不存在的字段", "op": "=", "value": "x"}],
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "filter field_name" in r.json()["detail"]

    def test_sorting_field_not_found(self, client, ws, table, auth_owner):
        """sorting 引用不存在的字段 → 400（覆盖 _validate_view_fields sorting 分支）."""
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "BadSort",
                "view_type": "grid",
                "sortings": [{"field_name": "不存在的字段", "direction": "asc"}],
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "sorting field_name" in r.json()["detail"]

    def test_view_options_field_not_found(self, client, ws, table, auth_owner):
        """view_options 里的单字段引用不存在 → 400（覆盖 _validate_view_fields opt_key 循环）."""
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "BadTitle",
                "view_type": "gallery",
                "view_options": {"title_field": "不存在的字段"},
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "view_options.title_field" in r.json()["detail"]

    def test_meta_fields_field_not_found(self, client, ws, table, auth_owner):
        """meta_fields 数组里包含不存在的字段 → 400."""
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "BadMeta",
                "view_type": "gallery",
                "view_options": {"meta_fields": ["不存在的字段"]},
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "meta_fields" in r.json()["detail"]

    def test_gallery_with_subtitle_tag_meta(self, client, ws, table, auth_owner):
        """gallery 视图带 subtitle_field / tag_field / meta_fields 全部合法字段 → 201."""
        # 先加几个字段
        for fname, ftype in [("部门", "text"), ("状态", "text"), ("备注", "text")]:
            client.post(
                f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
                json={"name": fname, "field_type": ftype},
                headers=auth_owner,
            )
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={
                "name": "GalleryFull",
                "view_type": "gallery",
                "view_options": {
                    "title_field": "姓名",
                    "subtitle_field": "部门",
                    "tag_field": "状态",
                    "meta_fields": ["备注"],
                },
            },
            headers=auth_owner,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["view_options"]["subtitle_field"] == "部门"
        assert data["view_options"]["tag_field"] == "状态"
        assert data["view_options"]["meta_fields"] == ["备注"]

    def test_import_views_with_meta_fields(self, client, ws, table, auth_owner):
        """批量导入视图时 meta_fields 合法字段能通过校验."""
        for fname, ftype in [("部门", "text"), ("状态", "text")]:
            client.post(
                f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields",
                json={"name": fname, "field_type": ftype},
                headers=auth_owner,
            )
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/import",
            json=[
                {
                    "name": "BatchGallery",
                    "view_type": "gallery",
                    "view_options": {
                        "title_field": "姓名",
                        "subtitle_field": "部门",
                        "tag_field": "状态",
                        "meta_fields": ["部门"],
                    },
                }
            ],
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_import_views_meta_fields_bad(self, client, ws, table, auth_owner):
        """批量导入视图时 meta_fields 含不存在字段 → 跳过该视图但整体 200."""
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/import",
            json=[
                {
                    "name": "SkipBadMeta",
                    "view_type": "gallery",
                    "view_options": {"meta_fields": ["no_such_field"]},
                }
            ],
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) == 0

    def test_import_views_skip_existing(self, client, ws, table, auth_owner):
        """批量导入遇到同名视图自动跳过，不报错（覆盖 import_views 同名跳过分支）."""
        # 先建一个视图
        client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "ExistView", "view_type": "grid"},
            headers=auth_owner,
        )
        # 再 import 同名的 —— 应跳过
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/import",
            json=[{"name": "ExistView", "view_type": "grid"}],
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) == 0


class TestViewReorder:
    """POST /views/reorder 视图排序."""

    def test_reorder_views(self, client, ws, table, auth_owner):
        """批量调整视图顺序应按传入顺序返回."""
        view_ids = []
        for i in range(3):
            r = client.post(
                f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
                json={"name": f"v{i}", "view_type": "grid"},
                headers=auth_owner,
            )
            view_ids.append(r.json()["id"])

        # 反转顺序
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/reorder",
            json=list(reversed(view_ids)),
            headers=auth_owner,
        )
        assert r.status_code == 200
        reordered = r.json()
        assert reordered[0]["id"] == view_ids[2]
        assert reordered[1]["id"] == view_ids[1]
        assert reordered[2]["id"] == view_ids[0]

    def test_reorder_views_skip_missing_id(self, client, ws, table, auth_owner):
        """reorder 视图时传入不存在的 view_id 应被跳过，不报错."""
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "v_only", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = r.json()["id"]
        # 混入一个不存在的 id
        r2 = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/reorder",
            json=[99999, vid],
            headers=auth_owner,
        )
        assert r2.status_code == 200
        assert [v["id"] for v in r2.json()] == [vid]

    def test_reorder_views_readonly_forbidden(self, client, db, ws, table, auth_owner):
        """只读用户 reorder 视图应返回 403."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.models import WorkspaceMember

        viewer = User(username="viewer", email="v@t.com")
        viewer.set_password("pw")
        viewer.role = "user"
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        db.refresh(viewer)

        login = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "viewer", "password": "pw"},
        )
        viewer_h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # 先建一个视图
        vr = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views",
            json={"name": "v1", "view_type": "grid"},
            headers=auth_owner,
        )
        vid = vr.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views/reorder",
            json=[vid],
            headers=viewer_h,
        )
        assert r.status_code == 403
