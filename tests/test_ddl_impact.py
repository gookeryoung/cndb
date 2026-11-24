"""大表 DDL 影响预估（需求 0150 / ADR 0150）.

覆盖：三类动作的估算形状、空表、抽样上限、字段空值行数、非法入参、
阈值开关（默认关闭 / 开启时 400 / 带 force 通过）、只读（不改数据与元数据）
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.ddl_impact import (
    ACTION_FACTORS,
    MAX_SAMPLE,
    estimate_ddl_impact,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="impact_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": "impact_owner", "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="ImpactWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="预估表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for order, (name, ftype) in enumerate([("编号", "text"), ("金额", "number")]):
        f = DataField(table_id=dt.id, name=name, field_type=ftype, order=order)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    for i in range(20):
        rec.create_row(engine, dt, {"编号": f"N{i}", "金额": i if i % 3 else None}, db=db)
    return dt


class TestEstimate:
    def _field(self, db, table):
        return next(f for f in table.fields if f.name == "金额")

    def test_change_type_shape(self, db, table):
        field = self._field(db, table)
        impact = estimate_ddl_impact(db, table, action="change_type", field=field, target_type="text")
        assert impact["action"] == "change_type"
        assert impact["row_count"] == 20
        assert impact["field"] == "金额"
        assert impact["factor"] == ACTION_FACTORS["change_type"]
        assert impact["sampled_rows"] <= 200
        assert impact["estimated_ms"] >= 0
        assert impact["field_null_count"] == 7  # i=0/3/6/9/12/15/18
        assert impact["force_required"] is False  # 默认阈值 0 = 关闭

    def test_add_field_and_index(self, db, table):
        add = estimate_ddl_impact(db, table, action="add_field", target_type="text")
        assert add["field"] is None and add["factor"] == ACTION_FACTORS["add_field"]
        idx = estimate_ddl_impact(db, table, action="add_index", target_type="text")
        assert idx["factor"] == ACTION_FACTORS["add_index"]

    def test_empty_table_zero_estimate(self, db, ws):
        engine = db.get_bind()
        dt = DataTable(workspace_id=ws.id, name="空预估表")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        for order, (name, ftype) in enumerate([("名称", "text")]):
            f = DataField(table_id=dt.id, name=name, field_type=ftype, order=order)
            f.ensure_db_name()
            db.add(f)
        db.commit()
        db.refresh(dt)
        ddl.create_table(engine, dt)

        impact = estimate_ddl_impact(db, dt, action="add_field", target_type="text")
        assert impact["row_count"] == 0
        assert impact["estimated_ms"] == 0
        assert impact["sampled_rows"] == 0

    def test_sample_capped(self, db, table):
        impact = estimate_ddl_impact(db, table, action="add_index", target_type="text", sample=10_000)
        assert impact["sample_size"] == MAX_SAMPLE
        assert impact["sampled_rows"] <= MAX_SAMPLE

    def test_invalid_inputs(self, db, table):
        field = self._field(db, table)
        with pytest.raises(ValueError, match="不支持的动作"):
            estimate_ddl_impact(db, table, action="drop_everything")
        with pytest.raises(ValueError, match="需要指定字段"):
            estimate_ddl_impact(db, table, action="change_type", target_type="text")
        with pytest.raises(ValueError, match="需要指定目标字段类型"):
            estimate_ddl_impact(db, table, action="change_type", field=field)
        with pytest.raises(ValueError, match="未知字段类型"):
            estimate_ddl_impact(db, table, action="add_field", target_type="not-a-type")

    def test_readonly(self, db, table):
        before_rows = rec.count_rows(db.get_bind(), table, db=db)
        before_type = next(f for f in table.fields if f.name == "金额").field_type
        field = self._field(db, table)
        estimate_ddl_impact(db, table, action="change_type", field=field, target_type="text")
        db.expire_all()
        assert rec.count_rows(db.get_bind(), table, db=db) == before_rows
        refreshed = db.get(DataTable, table.id)
        assert next(f for f in refreshed.fields if f.name == "金额").field_type == before_type


class TestImpactApi:
    def test_endpoint_ok(self, client, db, ws, table, auth):
        field = next(f for f in table.fields if f.name == "金额")
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields/ddl-impact",
            params={"action": "change_type", "field_id": field.id, "field_type": "text"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["row_count"] == 20
        assert body["force_required"] is False

    def test_endpoint_bad_action(self, client, ws, table, auth):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields/ddl-impact",
            params={"action": "nope", "field_type": "text"},
            headers=auth,
        )
        assert r.status_code == 400

    def test_endpoint_unknown_field(self, client, ws, table, auth):
        r = client.get(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields/ddl-impact",
            params={"action": "change_type", "field_id": 99999, "field_type": "text"},
            headers=auth,
        )
        assert r.status_code == 404


class TestForceThreshold:
    def test_disabled_by_default(self, client, db, ws, table, auth):
        field = next(f for f in table.fields if f.name == "金额")
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields/{field.id}",
            json={"field_type": "text"},
            headers=auth,
        )
        # 默认阈值 0 → 不拦截（既有行为不变）；转换本身成功或按既有规则失败都行
        assert r.status_code in (200, 400)
        assert "force=true" not in r.text

    def test_threshold_blocks_without_force(self, client, db, ws, table, auth, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "DDL_IMPACT_FORCE_THRESHOLD_ROWS", 5)
        field = next(f for f in table.fields if f.name == "金额")
        blocked = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields/{field.id}",
            json={"field_type": "text"},
            headers=auth,
        )
        assert blocked.status_code == 400
        assert "force=true" in blocked.text
        assert "20 行" in blocked.text

    def test_threshold_allows_with_force(self, client, db, ws, table, auth, monkeypatch):
        from cndb.core.config import settings

        monkeypatch.setattr(settings, "DDL_IMPACT_FORCE_THRESHOLD_ROWS", 5)
        field = next(f for f in table.fields if f.name == "金额")
        r = client.patch(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields/{field.id}",
            json={"field_type": "text"},
            params={"force": "true"},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        assert r.json()["field_type"] == "text"
