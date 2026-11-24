"""服务端聚合 / 分组（需求 0147）+ 字段级校验规则（需求 0146）.

覆盖：
- 聚合：count / sum / avg / min / max / distinct、分组、空值分组、排序、limit、
  total_groups、行级权限过滤、lookup 字段 400、扫描超限 400、参数校验
- 校验规则：正则命中 / 不命中（自定义文案）、条件必填（create 与 update 合并语义）、
  空值不参与模式校验、多值逐项、坏正则降级、导入与直编同口径
"""

from __future__ import annotations

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, TablePermission
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.field_rules import (
    check_pattern,
    check_required_when,
    validate_row_constraints,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="agg_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth(client, owner):
    r = client.post("/api/v1/accounts/auth/login", json={"login": "agg_owner", "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="AggWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws):
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="聚合表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for order, (name, ftype) in enumerate([("分组", "text"), ("金额", "number")]):
        f = DataField(table_id=dt.id, name=name, field_type=ftype, order=order)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    for group, amount in (("A", 10), ("A", 20), ("B", 5), (None, 7)):
        rec.create_row(engine, dt, {"分组": group, "金额": amount}, db=db)
    return dt


# ── 聚合：服务层 ─────────────────────────────────────


class TestAggregateRows:
    def test_group_count_and_sum(self, db, table):
        result = rec.aggregate_rows(
            db.get_bind(),
            table,
            group_by=["分组"],
            metrics=[{"field": "金额", "agg": "sum"}, {"agg": "count"}],
            db=db,
        )
        by_group = {row["group"]["分组"]: row["metrics"] for row in result["rows"]}
        assert by_group["A"]["sum_金额"] == 30
        assert by_group["A"]["count"] == 2
        assert by_group["B"]["sum_金额"] == 5
        # 空值分组如实保留
        assert by_group[None]["sum_金额"] == 7
        assert result["total_groups"] == 3

    def test_metrics_without_group(self, db, table):
        result = rec.aggregate_rows(
            db.get_bind(),
            table,
            metrics=[
                {"field": "金额", "agg": "sum"},
                {"field": "金额", "agg": "avg"},
                {"field": "金额", "agg": "min"},
                {"field": "金额", "agg": "max"},
                {"field": "分组", "agg": "distinct"},
            ],
            db=db,
        )
        assert len(result["rows"]) == 1
        metrics = result["rows"][0]["metrics"]
        assert metrics["sum_金额"] == 42
        assert metrics["avg_金额"] == 10.5
        assert metrics["min_金额"] == 5
        assert metrics["max_金额"] == 20
        # COUNT(DISTINCT col) 与 count 一致：只计非空（A / B）
        assert result["total_groups"] == 1

    def test_order_by_metric_and_limit(self, db, table):
        result = rec.aggregate_rows(
            db.get_bind(),
            table,
            group_by=["分组"],
            metrics=[{"field": "金额", "agg": "sum"}],
            order_by={"by": "metric", "index": 0, "direction": "desc"},
            limit=2,
            db=db,
        )
        assert [row["metrics"]["sum_金额"] for row in result["rows"]] == [30, 7]
        assert result["total_groups"] == 3

    def test_filters_apply(self, db, table):
        result = rec.aggregate_rows(
            db.get_bind(),
            table,
            metrics=[{"field": "金额", "agg": "sum"}],
            filters=[{"field_name": "分组", "op": "eq", "value": "A"}],
            db=db,
        )
        assert result["rows"][0]["metrics"]["sum_金额"] == 30
        assert result["matched_rows"] == 2

    def test_lookup_field_rejected(self, db, table):
        field = next(f for f in table.fields if f.name == "分组")
        field.field_type = "formula"
        db.commit()
        db.refresh(table)
        with pytest.raises(ValueError, match="没有物理列"):
            rec.aggregate_rows(db.get_bind(), table, group_by=["分组"], db=db)

    def test_unknown_field_rejected(self, db, table):
        with pytest.raises(ValueError, match="不存在"):
            rec.aggregate_rows(db.get_bind(), table, group_by=["不存在"], db=db)

    def test_bad_agg_rejected(self, db, table):
        with pytest.raises(ValueError, match="不支持的聚合方式"):
            rec.aggregate_rows(db.get_bind(), table, metrics=[{"field": "金额", "agg": "median"}], db=db)

    def test_sum_requires_field(self, db, table):
        with pytest.raises(ValueError, match="需要指定字段"):
            rec.aggregate_rows(db.get_bind(), table, metrics=[{"agg": "sum"}], db=db)

    def test_scan_limit_rejected(self, db, table):
        with pytest.raises(ValueError, match="超过上限"):
            rec.aggregate_rows(db.get_bind(), table, metrics=[{"agg": "count"}], max_rows=1, db=db)

    def test_row_scope_excludes_rows(self, db, table):
        db.add(
            TablePermission(
                table_id=table.id,
                row_filters=[{"field_name": "分组", "op": "eq", "value": "A"}],
                row_filter_type="AND",
            )
        )
        db.commit()
        viewer = User(username="agg_viewer", nickname="V")
        viewer.set_password("passw0rd")
        db.add(viewer)
        db.flush()
        db.add(WorkspaceMember(workspace_id=table.workspace_id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()

        result = rec.aggregate_rows(db.get_bind(), table, metrics=[{"agg": "count"}], db=db, user=viewer)
        assert result["rows"][0]["metrics"]["count"] == 2
        assert result["matched_rows"] == 2


# ── 聚合：接口 ───────────────────────────────────────


class TestAggregateApi:
    def test_endpoint_ok(self, client, ws, table, auth):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/aggregate",
            json={
                "group_by": ["分组"],
                "metrics": [{"field": "金额", "agg": "sum"}],
                "order_by": {"by": "group", "index": 0, "direction": "asc"},
            },
            headers=auth,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total_groups"] == 3
        assert body["metrics"][0] == {"alias": "sum_金额", "agg": "sum", "field": "金额"}

    def test_endpoint_unknown_field_400(self, client, ws, table, auth):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/aggregate",
            json={"group_by": ["不存在"], "metrics": [{"agg": "count"}]},
            headers=auth,
        )
        assert r.status_code == 400

    def test_endpoint_bad_payload_422(self, client, ws, table, auth):
        r = client.post(
            f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/aggregate",
            json={"limit": 0},
            headers=auth,
        )
        assert r.status_code == 422


# ── 字段级校验规则（0146）────────────────────────────


class TestFieldRules:
    def _table_with_rules(self, db, ws) -> DataTable:
        engine = db.get_bind()
        dt = DataTable(workspace_id=ws.id, name="规则表")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        code = DataField(table_id=dt.id, name="编号", field_type="text", order=0)
        code.ensure_db_name()
        code.config = {"validation": {"pattern": r"^[A-Z]{2}\d{4}$", "message": "编号格式应为 AB1234"}}
        status = DataField(table_id=dt.id, name="状态", field_type="text", order=1)
        status.ensure_db_name()
        done_at = DataField(table_id=dt.id, name="完成时间", field_type="text", order=2)
        done_at.ensure_db_name()
        done_at.config = {"required_when": {"field": "状态", "op": "eq", "value": "已完成"}}
        db.add_all([code, status, done_at])
        db.commit()
        db.refresh(dt)
        ddl.create_table(engine, dt)
        return dt

    def test_pattern_passes(self, db, ws):
        table = self._table_with_rules(db, ws)
        row = rec.create_row(db.get_bind(), table, {"编号": "AB1234"}, db=db)
        assert row["编号"] == "AB1234"

    def test_pattern_rejects_with_custom_message(self, db, ws):
        table = self._table_with_rules(db, ws)
        with pytest.raises(ValueError, match="编号格式应为 AB1234"):
            rec.create_row(db.get_bind(), table, {"编号": "abc"}, db=db)

    def test_required_when_on_create(self, db, ws):
        table = self._table_with_rules(db, ws)
        with pytest.raises(ValueError, match="必填"):
            rec.create_row(db.get_bind(), table, {"状态": "已完成"}, db=db)
        # 条件未命中 → 可空
        row = rec.create_row(db.get_bind(), table, {"状态": "进行中"}, db=db)
        assert row is not None

    def test_required_when_uses_merged_values_on_update(self, db, ws):
        table = self._table_with_rules(db, ws)
        row = rec.create_row(db.get_bind(), table, {"状态": "进行中"}, db=db)
        # 只改状态：合并后的行值里"完成时间"仍为空 → 必须拦下
        with pytest.raises(ValueError, match="必填"):
            rec.update_row(db.get_bind(), table, row["id"], {"状态": "已完成"}, db=db)
        # 同时给出完成时间 → 通过
        ok = rec.update_row(db.get_bind(), table, row["id"], {"状态": "已完成", "完成时间": "2026-11-24"}, db=db)
        assert ok["状态"] == "已完成"

    def test_blank_value_skips_pattern(self, db, ws):
        table = self._table_with_rules(db, ws)
        assert check_pattern(next(f for f in table.fields if f.name == "编号"), "") is None
        assert check_pattern(next(f for f in table.fields if f.name == "编号"), None) is None

    def test_multivalue_pattern_each_item(self, db, ws):
        table = self._table_with_rules(db, ws)
        field = next(f for f in table.fields if f.name == "编号")
        with pytest.raises(ValueError):
            check_pattern(field, ["AB1234", "bad"])

    def test_bad_regex_degrades(self, db, ws):
        table = self._table_with_rules(db, ws)
        field = next(f for f in table.fields if f.name == "编号")
        field.config = {"validation": {"pattern": "([unclosed"}}
        db.commit()
        assert check_pattern(field, "anything") is None

    def test_required_when_operators(self, db, ws):
        table = self._table_with_rules(db, ws)
        field = next(f for f in table.fields if f.name == "完成时间")
        for op, watched, expected_raise in (
            ("is_empty", None, True),
            ("is_not_empty", "x", True),
            ("in", "已完成", True),
            ("not_in", "进行中", True),
        ):
            field.config = {"required_when": {"field": "状态", "op": op, "value": "已完成"}}
            if op == "in":
                field.config["required_when"]["value"] = ["已完成", "关闭"]
            db.commit()
            if expected_raise:
                with pytest.raises(ValueError):
                    check_required_when(field, {"状态": watched})
            else:
                check_required_when(field, {"状态": watched})

    def test_import_validator_uses_same_rules(self, db, ws):
        """导入校验与直编同口径：坏编号在导入阶段就是 error 而不是落库后才发现."""
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        table = self._table_with_rules(db, ws)
        validator = RowValidator(table)
        results = validator.validate_all([{"编号": "bad", "状态": "进行中"}])
        assert results[0].status == "error"
        assert any("编号格式" in issue.message for issue in results[0].issues)

    def test_validate_row_constraints_api(self, db, ws):
        table = self._table_with_rules(db, ws)
        validate_row_constraints(table, {"编号": "AB1234", "状态": "进行中"})
        with pytest.raises(ValueError):
            validate_row_constraints(table, {"编号": "bad"})
