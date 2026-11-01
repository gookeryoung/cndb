"""dashboard 跨表 widget 的配置期校验与取数降级测试（ADR 0023 P3 / D8）.

覆盖：跨表配置保存成功且保留 ``query.table_id``、目标表字段按表校验、
目标表不存在 / 跨工作区 / 已软删 / 非法 id 在配置期统一 400、
取数按表分组（基表视图过滤不串到跨表组）、目标表越权 / 软删时该组降级为错误卡、
跨表字段隐藏生效。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from cndb.core.cache import dashboard_cache
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, TablePermission
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.dashboard_data import CROSS_TABLE_DENIED
from cndb.plugins.tables.services.core.records import create_row
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

#: 基表（销量表）
BASE_ROWS = [
    {"订单号": "A001", "商品类别": "数码", "销售额": 100, "日期": "2026-01-10"},
    {"订单号": "A002", "商品类别": "家电", "销售额": 70, "日期": "2026-02-11"},
    {"订单号": "A003", "商品类别": "食品", "销售额": 240, "日期": "2026-03-12"},
]
#: 跨表目标（客户表）
TARGET_ROWS = [
    {"客户": "甲公司", "等级": "金", "合同额": 1000, "签约日期": "2026-01-05"},
    {"客户": "乙公司", "等级": "金", "合同额": 2000, "签约日期": "2026-02-01"},
    {"客户": "丙公司", "等级": "银", "合同额": 500, "签约日期": "2026-03-01"},
    {"客户": "丁公司", "等级": "银", "合同额": 1500, "签约日期": "2026-03-20"},
]
TARGET_SUM = 5000


def _make_table(
    db,
    workspace: Workspace,
    name: str,
    specs: tuple[tuple[str, str], ...],
    rows: list[dict[str, Any]],
) -> DataTable:
    """建一张真实数据表并写入种子行（与 ``tests/test_dashboard_data.py`` 同款）."""
    engine = db.get_bind()
    dt = DataTable(workspace_id=workspace.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for order, (field_name, field_type) in enumerate(specs):
        field = DataField(table_id=dt.id, name=field_name, field_type=field_type, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    for values in rows:
        create_row(engine, dt, values, db=db)
    db.commit()
    return dt


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    dashboard_cache.clear()


@pytest.fixture
def owner(db) -> User:
    user = User(username="xt_owner", nickname="Owner")
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_owner(client, owner) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": owner.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def viewer(db) -> User:
    user = User(username="xt_viewer", nickname="Viewer")
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def auth_viewer(client, viewer) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": viewer.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner, viewer) -> Workspace:
    workspace = Workspace(name="XTableWS", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def base_table(db, ws) -> DataTable:
    return _make_table(
        db,
        ws,
        "销量表",
        (("订单号", "text"), ("商品类别", "text"), ("销售额", "number"), ("日期", "date")),
        BASE_ROWS,
    )


@pytest.fixture
def target_table(db, ws) -> DataTable:
    return _make_table(
        db,
        ws,
        "客户表",
        (("客户", "text"), ("等级", "text"), ("合同额", "number"), ("签约日期", "date")),
        TARGET_ROWS,
    )


def _url(ws: Workspace, table: DataTable) -> str:
    return f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views"


def _widgets(target_id: Any) -> list[dict[str, Any]]:
    """基表 KPI + 跨表 KPI + 跨表明细，覆盖三类字段引用校验."""
    return [
        {
            "id": "base",
            "type": "kpi",
            "layout": {"x": 0, "y": 0, "w": 3, "h": 4},
            "kpi": {"value": {"field": "销售额", "agg": "sum"}},
        },
        {
            "id": "cross",
            "type": "kpi",
            "layout": {"x": 3, "y": 0, "w": 3, "h": 4},
            "kpi": {"value": {"field": "合同额", "agg": "sum"}},
            "query": {"table_id": target_id},
        },
        {
            "id": "cross_table",
            "type": "table",
            "layout": {"x": 0, "y": 4, "w": 12, "h": 8},
            "table": {"columns": ["客户", "合同额"]},
            "query": {"table_id": target_id},
        },
    ]


def _options(target_id: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "widgets": _widgets(target_id),
        "global_filters": [{"id": "range", "kind": "date_range", "field": "日期"}],
        "settings": {"refresh_interval": 0, "theme": "inherit"},
    }


def _create(client, ws, table, auth, options: dict[str, Any], *, visibility: str = "private"):
    return client.post(
        _url(ws, table),
        json={"name": "跨表画布", "view_type": "dashboard", "view_options": options, "visibility": visibility},
        headers=auth,
    )


def _data(client, ws, table, view, auth, body: dict[str, Any] | None = None):
    return client.post(f"{_url(ws, table)}/{view['id']}/dashboard/data", json=body or {}, headers=auth)


# ── 配置期 ────────────────────────────────────────────


class TestCrossTableConfig:
    def test_cross_table_saved_and_table_id_kept(self, client, ws, base_table, target_table, auth_owner):
        r = _create(client, ws, base_table, auth_owner, _options(int(target_table.id)))
        assert r.status_code == 201, r.text
        widgets = r.json()["view_options"]["widgets"]
        assert widgets[0]["query"].get("table_id") is None
        assert widgets[1]["query"]["table_id"] == int(target_table.id)
        assert widgets[2]["query"]["table_id"] == int(target_table.id)

    def test_target_field_missing_rejected(self, client, ws, base_table, target_table, auth_owner):
        """跨表字段引用按目标表 schema 校验（基表同名字段不能顶替）."""
        options = _options(int(target_table.id))
        options["widgets"][1]["kpi"]["value"]["field"] = "订单号"
        r = _create(client, ws, base_table, auth_owner, options)
        assert r.status_code == 400
        assert "widgets[1].kpi" in r.json()["detail"]

    @pytest.mark.parametrize(
        ("bad_id", "expect"),
        [
            (99999, "目标表不存在或无权限"),
            (0, "必须是正整数"),
            ("abc", "必须是正整数"),
        ],
    )
    def test_invalid_target_rejected(self, client, ws, base_table, auth_owner, bad_id, expect):
        r = _create(client, ws, base_table, auth_owner, _options(bad_id))
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "widgets[1].query.table_id" in detail
        assert expect in detail

    def test_other_workspace_table_rejected(self, client, ws, base_table, db, owner, auth_owner):
        other = Workspace(name="OtherWS", created_by_id=owner.id)
        db.add(other)
        db.flush()
        stray = DataTable(workspace_id=other.id, name="别的工作区的表")
        stray.ensure_db_name()
        db.add(stray)
        db.commit()
        db.refresh(stray)
        r = _create(client, ws, base_table, auth_owner, _options(int(stray.id)))
        assert r.status_code == 400
        assert "目标表不存在或无权限" in r.json()["detail"]

    def test_trashed_target_rejected(self, client, ws, base_table, target_table, db, auth_owner):
        target_table.trashed_at = datetime.now(UTC)
        db.commit()
        r = _create(client, ws, base_table, auth_owner, _options(int(target_table.id)))
        assert r.status_code == 400
        assert "目标表不存在或无权限" in r.json()["detail"]

    def test_update_accepts_cross_table(self, client, ws, base_table, target_table, auth_owner):
        created = _create(client, ws, base_table, auth_owner, {"widgets": [], "schema_version": 1})
        assert created.status_code == 201, created.text
        view = created.json()
        r = client.patch(
            f"{_url(ws, base_table)}/{view['id']}",
            json={"view_options": _options(int(target_table.id))},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert r.json()["view_options"]["widgets"][1]["query"]["table_id"] == int(target_table.id)


# ── 取数期 ────────────────────────────────────────────


class TestCrossTableData:
    def test_reads_target_table_and_keeps_base_filters(self, client, ws, base_table, target_table, auth_owner):
        view = _create(client, ws, base_table, auth_owner, _options(int(target_table.id))).json()
        body = _data(client, ws, base_table, view, auth_owner).json()
        assert body["errors"] == []
        by_id = {item["widget_id"]: item for item in body["items"]}
        assert [item["widget_id"] for item in body["items"]] == ["base", "cross", "cross_table"]
        assert by_id["base"]["dataset"]["value"] == 410
        assert by_id["base"]["meta"]["total"] == len(BASE_ROWS)
        assert by_id["cross"]["dataset"]["value"] == TARGET_SUM
        assert by_id["cross"]["meta"]["total"] == len(TARGET_ROWS)
        assert by_id["cross_table"]["dataset"]["columns"] == ["客户", "合同额"]
        assert by_id["cross_table"]["dataset"]["total"] == len(TARGET_ROWS)

    def test_global_filter_only_applies_to_base_group(self, client, ws, base_table, target_table, auth_owner):
        """基表视图的全局筛选不套到跨表组（字段属于不同表 schema）."""
        view = _create(client, ws, base_table, auth_owner, _options(int(target_table.id))).json()
        body = _data(
            client,
            ws,
            base_table,
            view,
            auth_owner,
            {"globals": {"range": ["2026-01-01", "2026-01-31"]}},
        ).json()
        by_id = {item["widget_id"]: item for item in body["items"]}
        assert by_id["base"]["dataset"]["value"] == 100
        assert by_id["base"]["meta"]["scanned"] == 1
        assert by_id["cross"]["dataset"]["value"] == TARGET_SUM
        assert by_id["cross"]["meta"]["scanned"] == len(TARGET_ROWS)

    def test_hidden_field_on_target_table(self, client, ws, base_table, target_table, db, auth_owner):
        db.add(TablePermission(table_id=target_table.id, hidden_fields={"owner": ["合同额"]}))
        db.commit()
        view = _create(client, ws, base_table, auth_owner, _options(int(target_table.id))).json()
        body = _data(client, ws, base_table, view, auth_owner).json()
        by_id = {item["widget_id"]: item for item in body["items"]}
        assert by_id["cross"]["dataset"]["value"] is None
        assert by_id["cross"]["meta"]["scanned"] == len(TARGET_ROWS)

    def test_trashed_target_degrades_to_error_card(self, client, ws, base_table, target_table, db, auth_owner):
        view = _create(client, ws, base_table, auth_owner, _options(int(target_table.id))).json()
        target_table.trashed_at = datetime.now(UTC)
        db.commit()
        dashboard_cache.clear()
        body = _data(client, ws, base_table, view, auth_owner).json()
        assert [item["widget_id"] for item in body["items"]] == ["base"]
        assert {err["widget_id"] for err in body["errors"]} == {"cross", "cross_table"}
        assert all(err["detail"] == CROSS_TABLE_DENIED for err in body["errors"])

    def test_no_permission_degrades_only_cross_widgets(
        self, client, ws, base_table, target_table, db, auth_owner, auth_viewer
    ):
        """目标表无 READ 权限：跨表组降级，基表卡片照常返回."""
        view = _create(client, ws, base_table, auth_owner, _options(int(target_table.id)), visibility="table").json()
        db.add(TablePermission(table_id=target_table.id, read_role="editor"))
        db.commit()
        dashboard_cache.clear()
        body = _data(client, ws, base_table, view, auth_viewer).json()
        assert body["items"][0]["widget_id"] == "base"
        assert body["items"][0]["dataset"]["value"] == 410
        assert {err["widget_id"] for err in body["errors"]} == {"cross", "cross_table"}
        assert all(err["detail"] == CROSS_TABLE_DENIED for err in body["errors"])

    def test_widget_ids_subset_across_tables(self, client, ws, base_table, target_table, auth_owner):
        view = _create(client, ws, base_table, auth_owner, _options(int(target_table.id))).json()
        body = _data(client, ws, base_table, view, auth_owner, {"widget_ids": ["cross"]}).json()
        assert [item["widget_id"] for item in body["items"]] == ["cross"]
        assert body["errors"] == []


# ── 判定层：resolver 注入 ─────────────────────────────


def test_normalize_with_resolver_keeps_table_id() -> None:
    from cndb.plugins.tables.services.core.dashboard_config import normalize_dashboard_config

    raw = {
        "schema_version": 1,
        "widgets": [
            {
                "id": "cross",
                "type": "kpi",
                "layout": {"x": 0, "y": 0, "w": 3, "h": 4},
                "kpi": {"value": {"field": "合同额", "agg": "sum"}},
                "query": {"table_id": 7},
            }
        ],
    }
    config, err = normalize_dashboard_config(
        raw,
        {"销售额": "number"},
        lambda tid: {"合同额": "number"} if tid == 7 else None,
    )
    assert err is None
    assert config["widgets"][0]["query"]["table_id"] == 7

    config, err = normalize_dashboard_config(raw, {"销售额": "number"}, lambda _tid: None)
    assert config is None
    assert err is not None
    assert err.startswith("widgets[0].query.table_id")
