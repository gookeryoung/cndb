"""analytics 插件补充覆盖率测试：公式引擎边界 / 求值分支 / 统计与分组汇总 / 模板配置校验.

仅覆盖既有实现中未被 tests/test_analytics.py 触达的分支，不改变任何行为。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.analytics.services import compute as compute_svc
from cndb.plugins.analytics.services import formula
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import create_row
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TEMPLATES = "/api/v1/workspaces/{ws}/analytics/templates"
COMPUTE = "/api/v1/workspaces/{ws}/analytics/compute"


# ── 纯函数：公式引擎边界 ──────────────────────────────


class TestFormulaEdges:
    def test_empty_field_reference_rejected(self) -> None:
        with pytest.raises(formula.FormulaError):
            formula.parse("[]")

    def test_missing_close_paren_rejected(self) -> None:
        with pytest.raises(formula.FormulaError):
            formula.parse("round(1, 2")

    def test_unary_operators_parse_and_eval(self) -> None:
        assert formula.parse("-3") == ("unary", "-", ("num", 3.0))
        assert formula.parse("+3") == ("unary", "+", ("num", 3.0))
        assert formula.evaluate_column("-[v]", [{"v": 5}], ["v"]) == [-5.0]
        assert formula.evaluate_column("+[v]", [{"v": 5}], ["v"]) == [5.0]

    def test_zero_arg_call_rejected(self) -> None:
        with pytest.raises(formula.FormulaError):
            formula.parse("round()")

    def test_aggregate_requires_field_argument(self) -> None:
        with pytest.raises(formula.FormulaError):
            formula.parse("sum(1)")

    def test_referenced_fields_unary_and_percent(self) -> None:
        assert formula.referenced_fields(formula.parse("-[a]%")) == {"a"}

    def test_validate_formula_ok_and_raises(self) -> None:
        assert formula.validate_formula("1 + 2") is None
        with pytest.raises(formula.FormulaError):
            formula.validate_formula("(")

    def test_bool_values_coerced_to_number(self) -> None:
        rows = [{"v": True}, {"v": False}]
        assert formula.evaluate_column("[v]", rows, ["v"]) == [1.0, 0.0]

    def test_aggregate_unknown_field_raises(self) -> None:
        with pytest.raises(formula.FormulaError):
            formula.evaluate_column("sum([nope])", [{"a": 1}], ["a"])

    def test_aggregate_column_skips_non_numeric(self) -> None:
        rows = [{"n": 1}, {"n": None}, {"n": "x"}, {"n": 2}]
        assert formula.evaluate_column("sum([n])", rows, ["n"]) == [3.0, 3.0, 3.0, 3.0]

    def test_unary_and_percent_none_propagate(self) -> None:
        assert formula.evaluate_column("-[v]", [{"v": None}], ["v"]) == [None]
        assert formula.evaluate_column("[v]%", [{"v": None}], ["v"]) == [None]

    def test_aggregate_all_non_numeric_is_none(self) -> None:
        rows = [{"n": None}, {"n": "x"}]
        assert formula.evaluate_column("min([n])", rows, ["n"]) == [None, None]

    def test_scalar_arg_none_returns_none(self) -> None:
        assert formula.evaluate_column("abs([v])", [{"v": None}], ["v"]) == [None]

    def test_pow_ceil_floor(self) -> None:
        rows = [{"a": 1}]
        assert formula.evaluate_column("pow(2, 3)", rows, ["a"]) == [8.0]
        assert formula.evaluate_column("ceil(1.2)", rows, ["a"]) == [2.0]
        assert formula.evaluate_column("floor(1.8)", rows, ["a"]) == [1.0]

    def test_evaluate_value(self) -> None:
        assert formula.evaluate_value("sum([n])", [{"n": 1}, {"n": 2}, {"n": 3}], ["n"]) == 6.0
        assert formula.evaluate_value("[a] * 2", [{"a": 3}], ["a"]) == 6.0
        assert formula.evaluate_value("1 + 1", [], []) is None


# ── 纯函数：compute 服务内部工具 ─────────────────────


class TestComputeServiceUnits:
    def test_quantile_empty_and_single(self) -> None:
        assert compute_svc._quantile([], 0.5) is None
        assert compute_svc._quantile([5.0], 0.5) == 5.0

    def test_stat_block_without_numbers(self) -> None:
        stat = compute_svc._stat_block("k", "", "formula", [None, None])
        assert stat["count"] == 0
        assert stat["missing"] == 2
        assert "mean" not in stat

    def test_aggregate_non_numeric_and_empty(self) -> None:
        assert compute_svc._aggregate(["x", None, 2], "sum") == 2.0
        assert compute_svc._aggregate(["x"], "sum") is None
        assert compute_svc._aggregate([3, 1, 2], "min") == 1.0

    def test_aggregate_unsupported_kind_raises(self) -> None:
        with pytest.raises(formula.FormulaError):
            compute_svc._aggregate([1], "median")

    def test_group_label_blank(self) -> None:
        assert compute_svc._group_label(None) == compute_svc.EMPTY_GROUP_LABEL
        assert compute_svc._group_label("   ") == compute_svc.EMPTY_GROUP_LABEL


# ── API fixtures ─────────────────────────────────────


def make_table(db: Session, ws: Workspace, name: str = "产品批次") -> DataTable:
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for fname, ftype in [("批次号", "text"), ("产量", "number"), ("合格数", "number"), ("单价", "number")]:
        f = DataField(table_id=dt.id, name=fname, field_type=ftype)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    for values in (
        {"批次号": "B-001", "产量": 100, "合格数": 96, "单价": 12.5},
        {"批次号": "B-002", "产量": 200, "合格数": 178, "单价": 12.0},
        {"批次号": "B-003", "产量": 150, "合格数": 141, "单价": 13.0},
        {"批次号": "B-004", "产量": 50, "合格数": 40, "单价": 11.5},
    ):
        create_row(engine, dt, values, db=db)
    db.commit()
    return dt


@pytest.fixture
def owner(db) -> User:
    u = User(username="ana_extra_owner", nickname="AnaExtraOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="AnaExtraWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws) -> DataTable:
    return make_table(db, ws)


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_owner(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


PASS_RATE = {"key": "pass_rate", "label": "合格率(%)", "expr": "round([合格数] / [产量] * 100, 2)"}


# ── 分组汇总边界（compute 端点） ─────────────────────


class TestComputeSummaryEdges:
    def test_summary_duplicate_metric_key_gets_index(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        summary = {
            "group_by": "批次号",
            "metrics": [{"field": "产量", "agg": "sum"}, {"field": "产量", "agg": "sum"}],
        }
        r = client.post(
            COMPUTE.format(ws=ws.id),
            json={"table_id": table.id, "formulas": [], "summary": summary},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert [c["key"] for c in r.json()["summary"]["columns"]] == ["sum(产量)", "sum(产量)#2"]

    def test_summary_without_metrics_400(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        r = client.post(
            COMPUTE.format(ws=ws.id),
            json={"table_id": table.id, "summary": {"metrics": []}},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "至少需要一个指标" in r.json()["detail"]

    def test_summary_unmatched_sort_by_is_ignored(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        summary = {
            "group_by": "批次号",
            "metrics": [{"field": "产量", "agg": "sum"}],
            "sort_by": "zzz_not_a_metric",
        }
        r = client.post(
            COMPUTE.format(ws=ws.id),
            json={"table_id": table.id, "formulas": [PASS_RATE], "summary": summary},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert r.json()["summary"]["group_count"] == 4


# ── 模板配置校验边界（templates 端点） ────────────────


class TestTemplateConfigEdges:
    def test_duplicate_formula_key_400(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={
                "name": "键重复",
                "table_id": table.id,
                "config": {
                    "formulas": [
                        {"key": "dup", "expr": "[产量] + 1"},
                        {"key": "dup", "expr": "[产量] + 2"},
                    ]
                },
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "公式键重复" in r.json()["detail"]

    def test_summary_bad_aggregation_400(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={
                "name": "汇总聚合错",
                "table_id": table.id,
                "config": {"formulas": [PASS_RATE], "summary": {"metrics": [{"field": "产量", "agg": "median"}]}},
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "聚合方式非法" in r.json()["detail"]

    def test_summary_bad_sort_order_400(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={
                "name": "排序方向错",
                "table_id": table.id,
                "config": {
                    "formulas": [PASS_RATE],
                    "summary": {"metrics": [{"field": "产量", "agg": "sum"}], "sort_order": "up"},
                },
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "排序方向非法" in r.json()["detail"]

    def test_summary_sort_by_unknown_400(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={
                "name": "排序指标不存在",
                "table_id": table.id,
                "config": {
                    "formulas": [PASS_RATE],
                    "summary": {"metrics": [{"field": "产量", "agg": "sum"}], "sort_by": "不存在的指标"},
                },
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "排序指标不存在" in r.json()["detail"]

    def test_update_description_and_table_without_config(
        self, client: TestClient, db: Session, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        tpl = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "初版", "table_id": table.id, "config": {"formulas": [PASS_RATE]}},
            headers=auth_owner,
        ).json()
        other = make_table(db, ws, name="另一张表")
        r = client.put(
            TEMPLATES.format(ws=ws.id) + f"/{tpl['id']}",
            json={"description": "新描述", "table_id": other.id},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "初版"
        assert body["description"] == "新描述"
        assert body["table_id"] == other.id
        # config 未传 → 保持原配置
        assert body["config"]["formulas"][0]["key"] == "pass_rate"
