"""dashboard 视图配置契约与 API 测试（ADR 0023 P0）.

契约用例与前端共享 ``tests/fixtures/dashboard/schema_cases.json``；
API 覆盖创建 / 更新 / 未知 view_type / 历史 form 视图只读兼容。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, DataView, ViewVisibility
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.dashboard_config import normalize_dashboard_config
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

_CASES: dict[str, Any] = json.loads(
    (Path(__file__).parent / "fixtures" / "dashboard" / "schema_cases.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize("case", _CASES["valid"], ids=[c["name"] for c in _CASES["valid"]])
def test_normalize_dashboard_valid_and_idempotent(case: dict[str, Any]) -> None:
    """合法配置：解析成功，且对归一结果再次归一幂等."""
    config, err = normalize_dashboard_config(case["config"], _CASES["fields"])
    assert err is None
    assert config is not None
    again, err2 = normalize_dashboard_config(config, _CASES["fields"])
    assert err2 is None
    assert again == config


@pytest.mark.parametrize("case", _CASES["invalid"], ids=[c["name"] for c in _CASES["invalid"]])
def test_normalize_dashboard_invalid_path(case: dict[str, Any]) -> None:
    """非法配置：返回错误详情并定位到约定路径."""
    config, err = normalize_dashboard_config(case["config"], _CASES["fields"])
    assert config is None
    assert err is not None
    assert err.startswith(case["path"]), err


# ── 组件级 filters / sortings 校验 ────────────────────


def test_normalize_widget_filters_rejects_bad_shapes() -> None:
    """filters 校验：非数组 / 非对象项 / 缺字段名 / 未知字段 / 未知算子 均报路径."""
    from cndb.plugins.tables.services.core.dashboard_config import _normalize_filters

    fields = {"金额": "number", "日期": "date"}
    assert _normalize_filters(None, "q.filters", fields) == ([], None)
    ok, err = _normalize_filters([{"field_name": "金额", "op": ">=", "value": 1}], "q.filters", fields)
    assert err is None and ok == [{"field_name": "金额", "op": ">=", "value": 1}]

    bad_cases = [
        ("not-a-list", "必须是数组"),
        ([1], "[0]: 必须是对象"),
        ([{"op": ">="}], "[0].field_name: 必须是非空字符串"),
        ([{"field_name": "", "op": ">="}], "[0].field_name: 必须是非空字符串"),
        ([{"field_name": "不存在", "op": ">="}], "字段不存在"),
        ([{"field_name": "金额", "op": "p99"}], "不支持的操作符"),
        ([{"field_name": "金额"}], "不支持的操作符"),
    ]
    for raw, fragment in bad_cases:
        config, message = _normalize_filters(raw, "q.filters", fields)
        assert config is None
        assert fragment in (message or ""), (raw, message)


def test_normalize_widget_sortings_rejects_bad_shapes() -> None:
    """sortings 校验：非数组 / 缺字段名 / 未知字段 / 非法方向 报路径，方向缺省 asc."""
    from cndb.plugins.tables.services.core.dashboard_config import _normalize_sortings

    fields = {"金额": "number"}
    assert _normalize_sortings(None, "q.sortings", fields) == ([], None)
    ok, err = _normalize_sortings([{"field_name": "金额"}], "q.sortings", fields)
    assert err is None and ok == [{"field_name": "金额", "direction": "asc"}]

    bad_cases = [
        ("x", "必须是数组"),
        (["x"], "[0]: 必须是对象"),
        ([{"direction": "asc"}], "[0].field_name: 必须是非空字符串"),
        ([{"field_name": "未知"}], "字段不存在"),
        ([{"field_name": "金额", "direction": "up"}], "必须是 asc/desc"),
    ]
    for raw, fragment in bad_cases:
        config, message = _normalize_sortings(raw, "q.sortings", fields)
        assert config is None
        assert fragment in (message or ""), (raw, message)


def test_normalize_query_shapes_and_limits() -> None:
    """widget.query：缺省给空规格，非对象 / 非法 logic / 越界 limit 报路径."""
    from cndb.plugins.tables.services.core.dashboard_config import _normalize_query

    fields = {"金额": "number"}
    assert _normalize_query(None, "w.query", fields) == (
        {"filters": [], "filter_logic": "AND", "sortings": []},
        None,
    )
    ok, err = _normalize_query({"filter_logic": "OR", "limit": 5}, "w.query", fields)
    assert err is None and ok == {"filters": [], "filter_logic": "OR", "sortings": [], "limit": 5}

    bad = [
        ("x", "必须是对象"),
        ({"filter_logic": "XOR"}, "必须是 AND/OR"),
        ({"limit": 0}, "必须是 1..5000 的整数"),
        ({"limit": 5001}, "必须是 1..5000 的整数"),
        ({"limit": "5"}, "必须是 1..5000 的整数"),
        ({"filters": [{"field_name": "未知", "op": "="}]}, "字段不存在"),
        ({"sortings": [{"field_name": "金额", "direction": "up"}]}, "必须是 asc/desc"),
    ]
    for raw, fragment in bad:
        config, message = _normalize_query(raw, "w.query", fields)
        assert config is None
        assert fragment in (message or ""), (raw, message)


def test_validate_field_ref_rejects_missing() -> None:
    """字段引用校验：空值 / 非字符串 / 不存在字段 均给可定位文案."""
    from cndb.plugins.tables.services.core.dashboard_config import _validate_field_ref

    fields = {"金额": "number"}
    assert _validate_field_ref("金额", "w.chart.y[0]", fields) == ("金额", None)
    for value, expected in ((None, "必须是非空字段名"), ("", "必须是非空字段名"), (1, "必须是非空字段名")):
        got, err = _validate_field_ref(value, "w", fields)
        assert got is None and expected in (err or "")
    got, err = _validate_field_ref("不存在", "w", fields)
    assert got is None and "字段不存在" in (err or "")


# ── API 层 ─────────────────────────────────────────────


@pytest.fixture
def owner(db):
    u = User(username="dash_owner", nickname="Owner")
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
    w = Workspace(name="DashWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="DashTable")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    specs = (
        ("订单号", "text"),
        ("商品类别", "text"),
        ("销售额", "number"),
        ("数量", "number"),
        ("日期", "date"),
        ("评分", "float"),
        ("支付方式", "select"),
    )
    for order, (name, field_type) in enumerate(specs):
        df = DataField(table_id=dt.id, name=name, field_type=field_type, order=order)
        df.ensure_db_name()
        db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


def _view_url(ws: Workspace, table: DataTable) -> str:
    return f"/api/v1/workspaces/{ws.id}/tables/{table.id}/views"


_VALID_OPTIONS: dict[str, Any] = {
    "schema_version": 1,
    "widgets": [
        {
            "id": "kpi-sales",
            "type": "kpi",
            "title": "销售额合计",
            "layout": {"x": 0, "y": 0, "w": 3, "h": 4},
            "kpi": {"value": {"field": "销售额", "agg": "sum"}},
        },
        {
            "id": "sales-chart",
            "type": "chart",
            "layout": {"x": 0, "y": 4, "w": 6, "h": 10},
            "chart": {"type": "bar", "x": "商品类别", "y": ["销售额"], "agg": "sum"},
            "query": {"filters": [{"field_name": "销售额", "op": ">=", "value": 100}]},
        },
    ],
    "global_filters": [{"id": "range", "kind": "date_range", "field": "日期"}],
    "settings": {"refresh_interval": 30, "theme": "light"},
}


class TestDashboardViewsAPI:
    def test_create_dashboard_normalizes_options(self, client, ws, table, auth_owner):
        r = client.post(
            _view_url(ws, table),
            json={"name": "销售画布", "view_type": "dashboard", "view_options": _VALID_OPTIONS},
            headers=auth_owner,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["view_type"] == "dashboard"
        opts = data["view_options"]
        assert opts["schema_version"] == 1
        assert opts["canvas"] == {"cols": 12, "row_height": 40, "gap": 12, "padding": 16}
        assert opts["settings"] == {"refresh_interval": 30, "theme": "light"}
        assert opts["widgets"][0]["kpi"]["value"] == {"field": "销售额", "agg": "sum"}

    def test_create_dashboard_invalid_locates_widget(self, client, ws, table, auth_owner):
        bad = {
            "widgets": [
                {
                    "id": "bad",
                    "type": "chart",
                    "layout": {"x": 0, "y": 0, "w": 6, "h": 8},
                    "chart": {"type": "bar", "x": "商品类别", "y": ["订单号"], "agg": "sum"},
                }
            ]
        }
        r = client.post(
            _view_url(ws, table),
            json={"name": "坏画布", "view_type": "dashboard", "view_options": bad},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "widgets[0].chart.y[0]" in r.json()["detail"]

    def test_update_dashboard_invalid_options(self, client, ws, table, auth_owner):
        created = client.post(
            _view_url(ws, table),
            json={"name": "画布", "view_type": "dashboard", "view_options": _VALID_OPTIONS},
            headers=auth_owner,
        )
        assert created.status_code == 201
        view_id = created.json()["id"]
        r = client.patch(
            f"{_view_url(ws, table)}/{view_id}",
            json={
                "view_options": {
                    "widgets": [
                        {
                            "id": "bad",
                            "type": "kpi",
                            "layout": {"x": 0, "y": 0, "w": 3, "h": 4},
                            "kpi": {
                                "value": {"field": "销售额", "agg": "avg"},
                                "compare": {"mode": "prev_period", "date_field": "商品类别"},
                            },
                        }
                    ]
                }
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "widgets[0].kpi.compare.date_field" in r.json()["detail"]

    def test_update_view_type_unknown_rejected(self, client, ws, table, auth_owner):
        created = client.post(
            _view_url(ws, table),
            json={"name": "画布", "view_type": "dashboard"},
            headers=auth_owner,
        )
        assert created.status_code == 201
        r = client.patch(
            f"{_view_url(ws, table)}/{created.json()['id']}",
            json={"view_type": "radar"},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "radar" in r.json()["detail"]

    def test_create_view_type_unknown_rejected(self, client, ws, table, auth_owner):
        r = client.post(
            _view_url(ws, table),
            json={"name": "未知类型", "view_type": "map"},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "map" in r.json()["detail"]

    def test_historical_form_view_is_readable(self, client, ws, table, auth_owner, db):
        """历史 ``form`` 视图（已不在白名单）仍可读取，不阻断列表/详情."""
        created = client.post(
            _view_url(ws, table),
            json={"name": "历史表单", "view_type": "grid", "visibility": "table"},
            headers=auth_owner,
        )
        assert created.status_code == 201
        dv = db.query(DataView).filter(DataView.id == created.json()["id"]).one()
        dv.view_type = "form"
        dv.visibility = ViewVisibility.TABLE
        db.commit()

        listed = client.get(_view_url(ws, table), headers=auth_owner)
        assert listed.status_code == 200
        assert any(v["view_type"] == "form" for v in listed.json())

        detail = client.get(f"{_view_url(ws, table)}/{dv.id}", headers=auth_owner)
        assert detail.status_code == 200
        assert detail.json()["view_type"] == "form"
