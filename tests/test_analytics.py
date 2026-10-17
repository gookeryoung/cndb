"""analytics 插件测试：受限公式引擎（安全边界）+ 求值统计 + 模板 CRUD 权限.

覆盖：
- 公式引擎：四则 / 括号 / 百分号 / 字段引用 / 白名单函数 / 聚合函数；
- 安全边界：未知函数、属性访问、下划线双前缀、逗号注入、超长公式一律拒绝（不 eval）；
- 求值：逐行派生列、空值剔除、除零 → None；
- 描述统计：count/mean/stdev/四分位；
- API：公式校验、求值、模板 CRUD 与工作区角色门槛（viewer 不可建模板）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.analytics.services import formula
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import create_row
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TEMPLATES = "/api/v1/workspaces/{ws}/analytics/templates"
VALIDATE = "/api/v1/workspaces/{ws}/analytics/validate"
COMPUTE = "/api/v1/workspaces/{ws}/analytics/compute"


# ── 公式引擎（纯函数，不需要 DB）────────────────────


class TestFormulaEngine:
    def test_arithmetic_and_parentheses(self) -> None:
        rows = [{"a": 3, "b": 4}]
        assert formula.evaluate_column("(1 + 2) * 3 - 4 / 2", rows, ["a", "b"]) == [7.0]

    def test_field_reference_and_functions(self) -> None:
        rows = [{"产量": 120, "合格数": 114}]
        out = formula.evaluate_column("round([合格数] / [产量] * 100, 2)", rows, ["产量", "合格数"])
        assert out == [95.0]

    def test_percent_suffix(self) -> None:
        rows = [{"v": 50}]
        assert formula.evaluate_column("20%", rows, ["v"]) == [0.2]

    def test_unary_minus_and_abs_sqrt(self) -> None:
        rows = [{"v": -9.0}]
        assert formula.evaluate_column("sqrt(abs([v]))", rows, ["v"]) == [3.0]

    def test_aggregate_functions_are_whole_column(self) -> None:
        rows = [{"n": 1.0}, {"n": 2.0}, {"n": 3.0}]
        assert formula.evaluate_column("sum([n])", rows, ["n"]) == [6.0, 6.0, 6.0]
        assert formula.evaluate_column("avg([n])", rows, ["n"]) == [2.0, 2.0, 2.0]
        assert formula.evaluate_column("count([n])", rows, ["n"]) == [3.0, 3.0, 3.0]
        assert formula.evaluate_column("min([n])", rows, ["n"]) == [1.0, 1.0, 1.0]
        assert formula.evaluate_column("max([n])", rows, ["n"]) == [3.0, 3.0, 3.0]

    def test_aggregate_over_columns_mixed_with_row_values(self) -> None:
        """典型业务公式：整体合格率（常量）与单行占比并存."""
        rows = [{"产量": 100, "合格数": 96}, {"产量": 100, "合格数": 88}]
        out = formula.evaluate_column("round([合格数] / [产量] * 100, 1)", rows, ["产量", "合格数"])
        assert out == [96.0, 88.0]
        overall = formula.evaluate_column("round(sum([合格数]) / sum([产量]) * 100, 1)", rows, ["产量", "合格数"])
        assert overall == [92.0, 92.0]

    def test_string_number_coercion_and_empty(self) -> None:
        rows = [{"v": "1,200"}, {"v": ""}, {"v": "abc"}]
        assert formula.evaluate_column("[v] * 2", rows, ["v"]) == [2400.0, None, None]

    def test_divide_by_zero_is_none(self) -> None:
        rows = [{"a": 1, "b": 0}]
        assert formula.evaluate_column("[a] / [b]", rows, ["a", "b"]) == [None]

    def test_none_field_value(self) -> None:
        rows = [{"a": None}]
        assert formula.evaluate_column("[a] + 1", rows, ["a"]) == [None]

    # ── 安全边界：任何越权表达式必须被拒绝 ──

    @pytest.mark.parametrize(
        "expr",
        [
            "__import__('os').system('ls')",  # 关键字/内建
            "().__class__.__bases__[0]",  # 属性访问
            "[a] if [b] else [c]",  # 条件表达式
            "1 + 2; 3",  # 语句分隔
            "sum([a], [b])",  # 聚合函数参数必须是字段引用
            "unknown_func([a])",  # 未知函数
            "exec('x')",  # 未知函数
            "round(1, 2, 3)",  # 参数个数越界
            "[unclosed",  # 括号不配对
            "1 #",  # 非法字符
            "lambda x: x",  # lambda
            "pow(2, 3, 4)",  # 参数个数越界
            "sum([a]) + ",  # 表达式不完整
            "a + 1",  # 裸标识符
        ],
    )
    def test_rejects_non_whitelisted_expressions(self, expr: str) -> None:
        with pytest.raises(formula.FormulaError):
            formula.parse(expr)

    def test_rejects_overlong_expression(self) -> None:
        with pytest.raises(formula.FormulaError):
            formula.parse("1 + " * formula.MAX_EXPR_LENGTH)

    def test_rejects_empty_expression(self) -> None:
        with pytest.raises(formula.FormulaError):
            formula.parse("   ")

    def test_unknown_field_raises_at_eval(self) -> None:
        with pytest.raises(formula.FormulaError):
            formula.evaluate_column("[不存在]", [{"a": 1}], ["a"])

    def test_referenced_fields_collects_all(self) -> None:
        node = formula.parse("round([a] / [b], 2) + sum([c])")
        assert formula.referenced_fields(node) == {"a", "b", "c"}

    def test_source_has_no_dynamic_execution(self) -> None:
        """硬性安全约束：求值实现不得调用 eval / exec / compile / __import__ 等动态执行入口."""
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(formula))
        banned = {"eval", "exec", "compile", "__import__", "getattr", "setattr", "globals", "locals"}
        called: set[str] = set()
        for node in ast.walk(tree):
            # 只看裸名调用（如 eval(...)）；re.compile 之类的模块属性调用不算
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called.add(node.func.id)
        assert not (called & banned), f"公式引擎出现动态执行入口: {called & banned}"


# ── API fixtures ─────────────────────────────────────


def make_table(db: Session, ws: Workspace) -> DataTable:
    """建产品批次表（产量 / 合格数 / 单价）并写入 4 行."""
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name="产品批次")
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
    u = User(username="ana_owner", nickname="AnaOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="AnaWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def viewer(db, ws) -> User:
    u = User(username="ana_viewer", nickname="AnaViewer")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(u)
    return u


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


@pytest.fixture
def auth_viewer(client, viewer) -> dict[str, str]:
    return _login(client, viewer.username)


PASS_RATE = {"key": "pass_rate", "label": "合格率(%)", "expr": "round([合格数] / [产量] * 100, 2)"}


class TestValidateEndpoint:
    def test_valid_formula(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        r = client.post(
            VALIDATE.format(ws=ws.id),
            json={"table_id": table.id, "formulas": [PASS_RATE]},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ok"] is True
        assert body["results"][0]["ok"] is True
        assert body["results"][0]["fields"] == ["产量", "合格数"]
        assert "产量" in body["table_fields"]

    def test_unknown_field_reported(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        r = client.post(
            VALIDATE.format(ws=ws.id),
            json={"table_id": table.id, "formulas": [{"key": "x", "expr": "[不多] + 1"}]},
            headers=auth_owner,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert "不多" in body["results"][0]["error"]

    def test_illegal_syntax_reported(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        r = client.post(
            VALIDATE.format(ws=ws.id),
            json={"table_id": None, "formulas": [{"key": "x", "expr": "__import__('os')"}]},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_requires_membership(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        assert client.post(VALIDATE.format(ws=ws.id), json={"formulas": []}).status_code == 401


class TestComputeEndpoint:
    def test_compute_returns_rows_and_stats(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        r = client.post(
            COMPUTE.format(ws=ws.id),
            json={"table_id": table.id, "formulas": [PASS_RATE], "fields": ["批次号", "产量"]},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 4
        assert body["truncated"] is False
        assert body["rows"][0]["pass_rate"] == 96.0
        assert body["rows"][1]["pass_rate"] == 89.0
        assert set(body["rows"][0]) == {"id", "批次号", "产量", "pass_rate"}
        stat = next(c for c in body["columns"] if c["key"] == "pass_rate")
        assert stat["count"] == 4
        assert stat["min"] == 80.0
        assert stat["max"] == 96.0
        assert stat["mean"] == pytest.approx(89.75)
        assert stat["median"] == pytest.approx(91.5)

    def test_compute_rejects_illegal_formula(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        r = client.post(
            COMPUTE.format(ws=ws.id),
            json={"table_id": table.id, "formulas": [{"key": "boom", "expr": "__import__('os')"}]},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_compute_rejects_duplicate_keys(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        r = client.post(
            COMPUTE.format(ws=ws.id),
            json={"table_id": table.id, "formulas": [PASS_RATE, PASS_RATE]},
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_unknown_table_404(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        r = client.post(
            COMPUTE.format(ws=ws.id),
            json={"table_id": 999999, "formulas": []},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_viewer_can_compute(self, client: TestClient, ws: Workspace, table: DataTable, auth_viewer) -> None:
        r = client.post(
            COMPUTE.format(ws=ws.id),
            json={"table_id": table.id, "formulas": [PASS_RATE]},
            headers=auth_viewer,
        )
        assert r.status_code == 200


class TestTemplateCrud:
    def test_create_and_list(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        payload = {
            "name": "批次合格率分布",
            "description": "按批次看合格率",
            "table_id": table.id,
            "config": {
                "formulas": [PASS_RATE],
                "chart": {"type": "histogram", "x": "pass_rate", "title": "合格率分布"},
                "fields": ["批次号", "产量", "合格数"],
                "limit": 500,
            },
        }
        r = client.post(TEMPLATES.format(ws=ws.id), json=payload, headers=auth_owner)
        assert r.status_code == 201, r.text
        tpl = r.json()
        assert tpl["name"] == "批次合格率分布"
        assert tpl["config"]["formulas"][0]["key"] == "pass_rate"
        assert tpl["config"]["chart"]["type"] == "histogram"

        listed = client.get(TEMPLATES.format(ws=ws.id), headers=auth_owner).json()
        assert [t["id"] for t in listed] == [tpl["id"]]

    def test_create_rejects_bad_formula(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={
                "name": "非法",
                "table_id": table.id,
                "config": {"formulas": [{"key": "x", "expr": "[产量] / [无]"}]},
            },
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "无" in r.json()["detail"]

    def test_create_rejects_chart_ref_to_unknown_field(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={
                "name": "图表引用错",
                "table_id": table.id,
                "config": {"formulas": [PASS_RATE], "chart": {"type": "bar", "x": "不存在", "y": "pass_rate"}},
            },
            headers=auth_owner,
        )
        assert r.status_code == 400

    def test_update_keeps_config_and_revalidates(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        tpl = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "初版", "table_id": table.id, "config": {"formulas": [PASS_RATE]}},
            headers=auth_owner,
        ).json()
        r = client.put(
            TEMPLATES.format(ws=ws.id) + f"/{tpl['id']}",
            json={"name": "改版", "config": {"formulas": [{"key": "rate2", "expr": "round([合格数] / [产量], 3)"}]}},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["name"] == "改版"
        assert body["config"]["formulas"][0]["key"] == "rate2"

        bad = client.put(
            TEMPLATES.format(ws=ws.id) + f"/{tpl['id']}",
            json={"config": {"formulas": [{"key": "x", "expr": "eval('1')"}]}},
            headers=auth_owner,
        )
        assert bad.status_code == 400

    def test_delete_template(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        tpl = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "待删", "table_id": table.id, "config": {"formulas": [PASS_RATE]}},
            headers=auth_owner,
        ).json()
        url = TEMPLATES.format(ws=ws.id) + f"/{tpl['id']}"
        assert client.delete(url, headers=auth_owner).status_code == 204
        assert client.get(url, headers=auth_owner).status_code == 404

    def test_viewer_cannot_mutate_but_can_read(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner, auth_viewer
    ) -> None:
        tpl = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "只读", "table_id": table.id, "config": {"formulas": [PASS_RATE]}},
            headers=auth_owner,
        ).json()
        assert client.get(TEMPLATES.format(ws=ws.id), headers=auth_viewer).status_code == 200
        assert (
            client.post(
                TEMPLATES.format(ws=ws.id),
                json={"name": "x", "config": {"formulas": []}},
                headers=auth_viewer,
            ).status_code
            == 403
        )
        assert client.delete(TEMPLATES.format(ws=ws.id) + f"/{tpl['id']}", headers=auth_viewer).status_code == 403

    def test_non_member_403(self, client: TestClient, ws: Workspace, db: Session, auth_headers) -> None:
        """auth_headers 的 testuser 不是本工作区成员."""
        assert client.get(TEMPLATES.format(ws=ws.id), headers=auth_headers).status_code == 403

    def test_template_scoped_to_workspace(
        self, client: TestClient, ws: Workspace, table: DataTable, db: Session, owner: User, auth_owner
    ) -> None:
        """模板不可跨工作区访问."""
        other = Workspace(name="OtherWS", created_by_id=owner.id)
        db.add(other)
        db.flush()
        db.add(WorkspaceMember(workspace_id=other.id, user_id=owner.id, role=WorkspaceRole.OWNER))
        db.commit()

        tpl = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "本区", "table_id": table.id, "config": {"formulas": [PASS_RATE]}},
            headers=auth_owner,
        ).json()
        assert client.get(TEMPLATES.format(ws=other.id) + f"/{tpl['id']}", headers=auth_owner).status_code == 404

    def test_create_with_unknown_table_404(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "表不存在", "table_id": 999999, "config": {"formulas": []}},
            headers=auth_owner,
        )
        assert r.status_code == 404
