"""表单级控件覆盖测试：widget/widget_config 校验与响应透传."""

from __future__ import annotations

from typing import Any

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

BASE = "/api/v1/workspaces/{wid}"


@pytest.fixture
def owner(db):
    u = User(username="w_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="WidgetWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="WidgetTable", owner_id=None)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for i, (name, ftype) in enumerate([("姓名", "text"), ("年龄", "number")]):
        df = DataField(table_id=dt.id, name=name, field_type=ftype, order=i)
        df.ensure_db_name()
        db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


def _auth(client, user) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": user.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_owner(client, owner):
    return _auth(client, owner)


def _create_form(client, ws, table, headers, field_config: list[dict[str, Any]]) -> dict:
    payload = {"table_id": table.id, "name": "控件表单", "field_config": field_config}
    return client.post(f"{BASE.format(wid=ws.id)}/forms", json=payload, headers=headers)


# ── 控件覆盖保存与透传 ──────────────────────────────────


class TestWidgetOverride:
    def test_select_override_roundtrip(self, client, ws, table, auth_owner):
        """text 字段覆盖为 select（带 options）→ 保存并详情透传."""
        r = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[
                {
                    "field_name": "姓名",
                    "editable": True,
                    "widget": "select",
                    "widget_config": {"options": [{"value": "a", "label": "甲"}, {"value": "b", "label": "乙"}]},
                },
                {"field_name": "年龄", "editable": True},
            ],
        )
        assert r.status_code == 201, r.text
        cfg = r.json()["field_config"]
        assert cfg[0]["widget"] == "select"
        assert cfg[0]["widget_config"]["options"][0]["label"] == "甲"

        r = client.get(f"{BASE.format(wid=ws.id)}/forms/{r.json()['id']}", headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["field_config"][0]["widget"] == "select"

    def test_meta_passes_widget_through(self, client, ws, table, auth_owner):
        """meta 解析后的 fields 保留 widget/widget_config."""
        created = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[
                {"field_name": "年龄", "editable": True, "widget": "rate", "widget_config": {"max": 5}},
            ],
        )
        assert created.status_code == 201, created.text
        r = client.get(f"{BASE.format(wid=ws.id)}/forms/{created.json()['id']}/meta", headers=auth_owner)
        assert r.status_code == 200
        fields = r.json()["fields"]
        assert fields[0]["widget"] == "rate"
        assert fields[0]["widget_config"] == {"max": 5}
        assert fields[0]["field_type"] == "number"

    def test_rate_on_number_ok(self, client, ws, table, auth_owner):
        """rate 覆盖 number 字段合法（无需 options）."""
        r = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "年龄", "editable": True, "widget": "rate"}],
        )
        assert r.status_code == 201, r.text


# ── 校验失败 ─────────────────────────────────────────────


class TestWidgetValidation:
    def test_invalid_widget_name_400(self, client, ws, table, auth_owner):
        """非法控件名 → 400 带明细."""
        r = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名", "widget": "colorpicker"}],
        )
        assert r.status_code == 400
        assert "控件覆盖非法" in r.json()["detail"]

    def test_incompatible_field_type_400(self, client, ws, table, auth_owner):
        """rate 覆盖 text 字段 → 400 类型不兼容."""
        r = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名", "widget": "rate"}],
        )
        assert r.status_code == 400
        assert "不支持控件覆盖" in r.json()["detail"]

    def test_select_without_options_400(self, client, ws, table, auth_owner):
        """select 缺 options → 400."""
        r = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名", "widget": "select"}],
        )
        assert r.status_code == 400
        assert "options" in r.json()["detail"]

    def test_select_empty_options_400(self, client, ws, table, auth_owner):
        """select options 为空列表 → 400."""
        r = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名", "widget": "select", "widget_config": {"options": []}}],
        )
        assert r.status_code == 400

    def test_update_field_config_revalidates(self, client, ws, table, auth_owner):
        """PATCH field_config 同样执行控件校验."""
        created = _create_form(
            client,
            ws,
            table,
            auth_owner,
            field_config=[{"field_name": "姓名", "editable": True}],
        )
        assert created.status_code == 201
        fid = created.json()["id"]
        r = client.patch(
            f"{BASE.format(wid=ws.id)}/forms/{fid}",
            json={"field_config": [{"field_name": "年龄", "widget": "select"}]},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "options" in r.json()["detail"]


__all__ = []
