"""评分矩阵（ADR 0136）——矩阵视图配置校验 + 单元格 upsert 接口测试."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import TablePermission
from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"
FIELDS = TABLES + "/{tb}/fields"
RECORDS = TABLES + "/{tb}/records"
VIEWS = TABLES + "/{tb}/views"
UPSERT = RECORDS + "/matrix-upsert"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _setup(client: TestClient, auth: dict[str, str]) -> tuple[int, int]:
    wid = client.post("/api/v1/workspaces", headers=auth, json={"name": "WS_SCORE"}).json()["id"]
    tid = client.post(TABLES.format(ws=wid), headers=auth, json={"name": "部门绩效评分"}).json()["id"]
    for order, (name, ftype, cfg) in enumerate(
        [
            ("部门", "select", {"options": ["研发部", "市场部", "财务部"]}),
            ("月份", "date", {}),
            ("得分", "number", {}),
            ("说明", "text", {}),
        ]
    ):
        r = client.post(
            FIELDS.format(ws=wid, tb=tid),
            headers=auth,
            json={"name": name, "field_type": ftype, "config": cfg, "order": order},
        )
        assert r.status_code == 201, r.text
    return wid, tid


def _list_rows(client: TestClient, auth: dict[str, str], wid: int, tid: int) -> list[dict]:
    r = client.get(RECORDS.format(ws=wid, tb=tid), headers=auth, params={"limit": 100})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _matrix_payload(**overrides) -> dict:
    payload = {
        "row_field": "部门",
        "row_value": "研发部",
        "month_field": "月份",
        "month": "2026-11",
        "value_field": "得分",
        "value": 88,
    }
    payload.update(overrides)
    return payload


class TestMatrixViewConfig:
    def test_valid_config_accepted(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            VIEWS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={
                "name": "评分矩阵",
                "view_type": "matrix",
                "view_options": {
                    "row_field": "部门",
                    "column_field": "月份",
                    "date_granularity": "month",
                    "value_field": "得分",
                    "period_start": "2026-01",
                    "period_end": "2026-12",
                },
            },
        )
        assert r.status_code == 201, r.text

    def test_rejects_invalid_row_field_type(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            VIEWS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={
                "name": "坏矩阵",
                "view_type": "matrix",
                "view_options": {
                    "row_field": "说明",
                    "column_field": "月份",
                    "value_field": "得分",
                    "period_start": "2026-01",
                    "period_end": "2026-12",
                },
            },
        )
        assert r.status_code == 400
        assert "行字段必须是单选" in r.json()["detail"]

    def test_rejects_filters(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            VIEWS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={
                "name": "带筛选矩阵",
                "view_type": "matrix",
                "filters": [{"field_name": "部门", "op": "=", "value": "研发部"}],
                "view_options": {
                    "row_field": "部门",
                    "column_field": "月份",
                    "value_field": "得分",
                    "period_start": "2026-01",
                    "period_end": "2026-12",
                },
            },
        )
        assert r.status_code == 400
        assert "不支持视图筛选" in r.json()["detail"]

    def test_rejects_month_span_over_24(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            VIEWS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={
                "name": "超长矩阵",
                "view_type": "matrix",
                "view_options": {
                    "row_field": "部门",
                    "column_field": "月份",
                    "value_field": "得分",
                    "period_start": "2024-01",
                    "period_end": "2026-12",
                },
            },
        )
        assert r.status_code == 400
        assert "最多 24 个月" in r.json()["detail"]

    def test_rejects_empty_row_options(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            FIELDS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={"name": "空选项部门", "field_type": "select", "config": {}, "order": 3},
        )
        assert r.status_code == 201, r.text
        r = client.post(
            VIEWS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={
                "name": "空选项矩阵",
                "view_type": "matrix",
                "view_options": {
                    "row_field": "空选项部门",
                    "column_field": "月份",
                    "value_field": "得分",
                    "period_start": "2026-01",
                    "period_end": "2026-12",
                },
            },
        )
        assert r.status_code == 400
        assert "固定选项" in r.json()["detail"]


class TestMatrixUpsert:
    def test_create_cell_stores_first_day_of_month(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload())
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["action"] == "created"
        rows = _list_rows(client, auth_headers, wid, tid)
        assert len(rows) == 1
        assert rows[0]["部门"] == "研发部"
        assert rows[0]["月份"] == "2026-11-01"
        assert rows[0]["得分"] == 88

    def test_update_existing_mid_month_row(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            RECORDS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={"values": {"部门": "研发部", "月份": "2026-11-15", "得分": 70}},
        )
        assert r.status_code == 201, r.text
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(value=90))
        assert r.status_code == 200, r.text
        assert r.json()["action"] == "updated"
        rows = _list_rows(client, auth_headers, wid, tid)
        assert len(rows) == 1
        assert rows[0]["月份"] == "2026-11-15"
        assert rows[0]["得分"] == 90

    def test_clear_existing_cell(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        client.post(
            RECORDS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={"values": {"部门": "研发部", "月份": "2026-11-01", "得分": 70}},
        )
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(value=None))
        assert r.status_code == 200, r.text
        rows = _list_rows(client, auth_headers, wid, tid)
        assert rows[0]["得分"] is None

    def test_empty_and_no_row_is_noop(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            UPSERT.format(ws=wid, tb=tid),
            headers=auth_headers,
            json=_matrix_payload(month="2026-12", value=None),
        )
        assert r.status_code == 204, r.text
        assert _list_rows(client, auth_headers, wid, tid) == []

    def test_duplicate_rows_rejected_without_write(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        for day in ("2026-11-05", "2026-11-20"):
            client.post(
                RECORDS.format(ws=wid, tb=tid),
                headers=auth_headers,
                json={"values": {"部门": "研发部", "月份": day, "得分": 60}},
            )
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(value=99))
        assert r.status_code == 409, r.text
        assert len(r.json()["row_ids"]) == 2
        rows = _list_rows(client, auth_headers, wid, tid)
        assert {row["得分"] for row in rows} == {60}

    def test_invalid_row_option_rejected(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            UPSERT.format(ws=wid, tb=tid),
            headers=auth_headers,
            json=_matrix_payload(row_value="不存在的部门"),
        )
        assert r.status_code == 400, r.text

    def test_invalid_month_rejected(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(month="2026-13"))
        assert r.status_code == 400, r.text

    def test_rejects_wrong_field_type(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(
            UPSERT.format(ws=wid, tb=tid),
            headers=auth_headers,
            json=_matrix_payload(value_field="部门"),
        )
        assert r.status_code == 400, r.text

    def test_viewer_creates_change_request(self, client: TestClient, db: Session, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        viewer = _make_user(db, "score_viewer")
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        viewer_auth = _login(client, viewer.username)

        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=viewer_auth, json=_matrix_payload())
        assert r.status_code == 202, r.text
        assert "change_request" in r.json()
        assert _list_rows(client, auth_headers, wid, tid) == []

    def test_row_rules_disable_matrix_write_except_bypass(
        self, client: TestClient, db: Session, auth_headers: dict[str, str]
    ):
        wid, tid = _setup(client, auth_headers)
        db.add(
            TablePermission(
                table_id=tid,
                read_role="viewer",
                hidden_fields={},
                row_filters=[{"field_name": "部门", "op": "=", "value": "研发部"}],
                row_filter_type="AND",
            )
        )
        db.commit()
        # owner 豁免行规则：照常写入
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload())
        assert r.status_code == 201, r.text

        viewer = _make_user(db, "score_rule_viewer")
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        viewer_auth = _login(client, viewer.username)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=viewer_auth, json=_matrix_payload(row_value="市场部"))
        assert r.status_code == 403
        assert "行级权限" in r.json()["detail"]

    def test_hidden_value_field_rejected(self, client: TestClient, db: Session, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        viewer = _make_user(db, "score_hidden_viewer")
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.add(
            TablePermission(
                table_id=tid,
                read_role="viewer",
                hidden_fields={"viewer": ["得分"]},
                row_filters=[],
                row_filter_type="AND",
            )
        )
        db.commit()
        viewer_auth = _login(client, viewer.username)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=viewer_auth, json=_matrix_payload())
        assert r.status_code == 403
        assert "隐藏" in r.json()["detail"]

    def test_table_detail_exposes_row_rules_active(self, client: TestClient, db: Session, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.get(TABLES.format(ws=wid) + f"/{tid}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["row_rules_active"] is False

        db.add(
            TablePermission(
                table_id=tid,
                read_role="viewer",
                hidden_fields={},
                row_filters=[{"field_name": "部门", "op": "=", "value": "研发部"}],
                row_filter_type="AND",
            )
        )
        db.commit()
        r = client.get(TABLES.format(ws=wid) + f"/{tid}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["row_rules_active"] is True


class TestMonthBounds:
    def test_parses_month_range(self):
        from datetime import date

        from cndb.plugins.tables.services.core.records import month_bounds

        assert month_bounds("2026-11") == (date(2026, 11, 1), date(2026, 12, 1))
        assert month_bounds("2026-12") == (date(2026, 12, 1), date(2027, 1, 1))

    def test_rejects_invalid_month(self):
        import pytest

        from cndb.plugins.tables.services.core.records import month_bounds

        for bad in ("2026-13", "2026/11", "2026-1", "", "abcd-01"):
            with pytest.raises(ValueError):
                month_bounds(bad)


def test_update_view_rejects_enabling_filters(client: TestClient, auth_headers: dict[str, str]):
    """更新已有矩阵视图时同样执行评分矩阵组合校验（更新路径不能绕过）."""
    wid, tid = _setup(client, auth_headers)
    r = client.post(
        VIEWS.format(ws=wid, tb=tid),
        headers=auth_headers,
        json={
            "name": "只读矩阵",
            "view_type": "matrix",
            "view_options": {
                "row_field": "部门",
                "column_field": "月份",
            },
        },
    )
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    r = client.patch(
        VIEWS.format(ws=wid, tb=tid) + f"/{vid}",
        headers=auth_headers,
        json={
            "filters": [{"field_name": "部门", "op": "=", "value": "研发部"}],
            "view_options": {
                "row_field": "部门",
                "column_field": "月份",
                "value_field": "得分",
                "period_start": "2026-01",
                "period_end": "2026-12",
            },
        },
    )
    assert r.status_code == 400, r.text
    assert "不支持视图筛选" in r.json()["detail"]


def test_create_cell_with_other_required_field_returns_400(client: TestClient, auth_headers: dict[str, str]):
    wid, tid = _setup(client, auth_headers)
    r = client.post(
        FIELDS.format(ws=wid, tb=tid),
        headers=auth_headers,
        json={"name": "评分人", "field_type": "text", "required": True, "order": 3},
    )
    assert r.status_code == 201, r.text
    r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload())
    assert r.status_code == 400, r.text


class TestMatrixViewOptionsHelper:
    """直接测试矩阵配置校验的边界分支（避免只靠路由侧覆盖）."""

    @staticmethod
    def _fields():
        from cndb.plugins.tables.models import DataField

        def f(name: str, ftype: str, config: dict | None = None) -> DataField:
            return DataField(name=name, field_type=ftype, config=config or {})

        return {
            "部门": f("部门", "select", {"options": ["研发部"]}),
            "空部门": f("空部门", "select", {}),
            "月份": f("月份", "date"),
            "得分": f("得分", "number"),
            "说明": f("说明", "text"),
        }

    def _validate(self, options: dict, filters=None):
        from cndb.plugins.tables.routers.views import _validate_matrix_score_options

        return _validate_matrix_score_options(options, filters or [], self._fields())

    def test_no_value_field_is_readonly_ok(self):
        assert self._validate({"row_field": "部门", "column_field": "月份"}) is None

    def test_missing_axes(self):
        assert "必须配置行分组字段" in self._validate({"value_field": "得分"})

    def test_missing_field_refs(self):
        assert "字段不存在" in self._validate(
            {
                "row_field": "不存在",
                "column_field": "月份",
                "value_field": "得分",
                "period_start": "2026-01",
                "period_end": "2026-12",
            }
        )

    def test_wrong_field_types(self):
        base = {
            "row_field": "部门",
            "column_field": "月份",
            "value_field": "得分",
            "period_start": "2026-01",
            "period_end": "2026-12",
        }
        assert "行字段必须是单选" in self._validate({**base, "row_field": "说明"})
        assert "月份字段必须是日期" in self._validate({**base, "column_field": "说明"})
        assert "评分字段必须是数字" in self._validate({**base, "value_field": "说明"})
        assert "日期聚合方式" in self._validate({**base, "date_granularity": "day"})

    def test_filters_rejected(self):
        assert "不支持视图筛选" in self._validate(
            {
                "row_field": "部门",
                "column_field": "月份",
                "value_field": "得分",
                "period_start": "2026-01",
                "period_end": "2026-12",
            },
            filters=[{"field_name": "部门", "op": "=", "value": "研发部"}],
        )

    def test_empty_options_rejected(self):
        assert "固定选项" in self._validate(
            {
                "row_field": "空部门",
                "column_field": "月份",
                "value_field": "得分",
                "period_start": "2026-01",
                "period_end": "2026-12",
            }
        )

    def test_period_validation(self):
        base = {"row_field": "部门", "column_field": "月份", "value_field": "得分"}
        assert "必须配置起止月份" in self._validate({**base, "period_start": "2026-01"})
        assert "必须配置起止月份" in self._validate({**base, "period_start": "2026/01", "period_end": "2026-12"})
        assert "必须配置起止月份" in self._validate({**base, "period_start": "abcd-01", "period_end": "2026-12"})
        assert "不能晚于" in self._validate({**base, "period_start": "2026-12", "period_end": "2026-01"})
        assert "最多 24 个月" in self._validate({**base, "period_start": "2024-01", "period_end": "2026-12"})


def test_find_month_key_rows_missing_fields_returns_empty(db: Session):
    from datetime import date

    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.records import find_month_key_rows

    t = DataTable(workspace_id=1, name="无字段表", owner_id=1)
    t.ensure_db_name()
    db.add(t)
    db.commit()
    assert find_month_key_rows(db.get_bind(), t, "部门", "研发部", "月份", date(2026, 11, 1), date(2026, 12, 1)) == []


class TestMatrixUpsertBranches:
    def test_missing_field_rejected(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(row_field="不存在"))
        assert r.status_code == 400
        assert "字段不存在" in r.json()["detail"]

    def test_same_fields_rejected(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(month_field="部门"))
        assert r.status_code == 400
        assert "必须是不同字段" in r.json()["detail"]

    def test_month_field_wrong_type_rejected(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(month_field="说明"))
        assert r.status_code == 400
        assert "月份字段必须是日期" in r.json()["detail"]

    def test_empty_row_value_rejected(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        client.post(
            FIELDS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={"name": "空部门", "field_type": "select", "config": {}, "order": 3},
        )
        r = client.post(
            UPSERT.format(ws=wid, tb=tid),
            headers=auth_headers,
            json=_matrix_payload(row_field="空部门", row_value=""),
        )
        assert r.status_code == 400
        assert "不能为空" in r.json()["detail"]

    def test_create_runtime_error_returns_500(self, client: TestClient, auth_headers: dict[str, str], monkeypatch):
        from cndb.plugins.tables.routers import records as records_router

        wid, tid = _setup(client, auth_headers)
        monkeypatch.setattr(records_router, "create_row", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload())
        assert r.status_code == 500

    def test_create_none_returns_500(self, client: TestClient, auth_headers: dict[str, str], monkeypatch):
        from cndb.plugins.tables.routers import records as records_router

        wid, tid = _setup(client, auth_headers)
        monkeypatch.setattr(records_router, "create_row", lambda *a, **k: None)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload())
        assert r.status_code == 500

    def _existing_row(self, client, auth_headers):
        wid, tid = _setup(client, auth_headers)
        client.post(
            RECORDS.format(ws=wid, tb=tid),
            headers=auth_headers,
            json={"values": {"部门": "研发部", "月份": "2026-11-01", "得分": 70}},
        )
        return wid, tid

    def test_update_not_found_branch(self, client: TestClient, auth_headers: dict[str, str], monkeypatch):
        from cndb.plugins.tables.routers import records as records_router

        wid, tid = self._existing_row(client, auth_headers)
        monkeypatch.setattr(records_router, "_row_write_decision", lambda *a, **k: records_router.ROW_WRITE_NOT_FOUND)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(value=90))
        assert r.status_code == 404

    def test_update_denied_branch(self, client: TestClient, auth_headers: dict[str, str], monkeypatch):
        from cndb.plugins.tables.routers import records as records_router

        wid, tid = self._existing_row(client, auth_headers)
        monkeypatch.setattr(records_router, "_row_write_decision", lambda *a, **k: records_router.ROW_WRITE_DENIED)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(value=90))
        assert r.status_code == 403

    def test_update_change_request_branch(self, client: TestClient, db: Session, auth_headers: dict[str, str]):
        wid, tid = self._existing_row(client, auth_headers)
        viewer = _make_user(db, "score_update_viewer")
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        viewer_auth = _login(client, viewer.username)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=viewer_auth, json=_matrix_payload(value=90))
        assert r.status_code == 202, r.text
        assert "change_request" in r.json()

    def test_update_value_error_branch(self, client: TestClient, auth_headers: dict[str, str], monkeypatch):
        from cndb.plugins.tables.routers import records as records_router

        wid, tid = self._existing_row(client, auth_headers)
        monkeypatch.setattr(records_router, "update_row", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad")))
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(value=90))
        assert r.status_code == 400

    def test_update_none_branch(self, client: TestClient, auth_headers: dict[str, str], monkeypatch):
        from cndb.plugins.tables.routers import records as records_router

        wid, tid = self._existing_row(client, auth_headers)
        monkeypatch.setattr(records_router, "update_row", lambda *a, **k: None)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(value=90))
        assert r.status_code == 404

    def test_row_and_value_field_type_rejected(self, client: TestClient, auth_headers: dict[str, str]):
        wid, tid = _setup(client, auth_headers)
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(row_field="说明"))
        assert r.status_code == 400
        assert "对象字段必须是单选" in r.json()["detail"]
        r = client.post(UPSERT.format(ws=wid, tb=tid), headers=auth_headers, json=_matrix_payload(value_field="说明"))
        assert r.status_code == 400
        assert "得分字段必须是数字" in r.json()["detail"]


def test_row_rules_active_from_rule_rows(client: TestClient, db: Session, auth_headers: dict[str, str]):
    """只有 RowPermission、没有默认档 row_filters 时也算启用了行级规则."""
    from cndb.plugins.tables.models import RowAction, RowPermission, RowSubject

    wid, tid = _setup(client, auth_headers)
    db.add(
        RowPermission(
            table_id=tid,
            subject_type=RowSubject.USER,
            subject_id="1",
            action=RowAction.VIEW,
            filters=[{"field_name": "部门", "op": "=", "value": "研发部"}],
        )
    )
    db.commit()
    r = client.get(TABLES.format(ws=wid) + f"/{tid}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["row_rules_active"] is True


def test_find_month_key_rows_missing_physical_column_returns_empty(db: Session):
    from datetime import date

    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
    from cndb.plugins.tables.services.core.records import find_month_key_rows

    t = DataTable(workspace_id=1, name="缺列表", owner_id=1)
    t.ensure_db_name()
    db.add(t)
    db.flush()
    # 物理表先建（空表），再挂一个 db_column_name 不存在的字段，模拟历史脏数据
    ddl_create(db.get_bind(), t)
    db.add(DataField(table_id=t.id, name="部门", field_type="text", db_column_name="missing_col"))
    db.add(DataField(table_id=t.id, name="月份", field_type="date", db_column_name="missing_month"))
    db.commit()
    db.refresh(t)
    assert find_month_key_rows(db.get_bind(), t, "部门", "研发部", "月份", date(2026, 11, 1), date(2026, 12, 1)) == []
