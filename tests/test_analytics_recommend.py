"""analytics 智能推荐 + 模板复制测试.

覆盖：
- 字段画像：角色判定（metric/dimension/time/identifier/ignored）、基数、完整度、示例值；
- 推荐配置：公式可被受限引擎 parse 且只引用可见字段、图表 / 汇总引用合法；
- 典型示例：非空、id 唯一、每个示例配置都能通过 ``normalize_config`` 语义校验；
- 边界：空表稳定返回、结果确定性、viewer 可读、非成员 403、表不存在 404；
- 模板复制：默认名 / 重名递增 / 显式命名 / 权限 / 原模板不受影响。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.analytics.schemas import TemplateConfig
from cndb.plugins.analytics.services import formula as formula_service
from cndb.plugins.analytics.services import recommend as recommend_service
from cndb.plugins.analytics.services import templates as template_service
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import create_row
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

RECOMMEND = "/api/v1/workspaces/{ws}/analytics/recommendations"
TEMPLATES = "/api/v1/workspaces/{ws}/analytics/templates"

TABLE_FIELDS: list[tuple[str, str]] = [
    ("订单编号", "text"),
    ("产品分类", "select"),
    ("生产日期", "date"),
    ("销售额", "number"),
    ("数量", "number"),
    ("利润率", "percentage"),
    ("备注", "longtext"),
]

TABLE_ROWS: list[dict[str, object]] = [
    {
        "订单编号": "SO-001",
        "产品分类": "华东",
        "生产日期": "2024-01-05",
        "销售额": 1200,
        "数量": 10,
        "利润率": 0.25,
        "备注": "重点客户",
    },
    {
        "订单编号": "SO-002",
        "产品分类": "华南",
        "生产日期": "2024-02-08",
        "销售额": 800,
        "数量": 8,
        "利润率": 0.2,
        "备注": "新客",
    },
    {
        "订单编号": "SO-003",
        "产品分类": "华北",
        "生产日期": "2024-03-12",
        "销售额": 1500,
        "数量": 15,
        "利润率": 0.3,
        "备注": "",
    },
    {
        "订单编号": "SO-004",
        "产品分类": "华东",
        "生产日期": "2024-04-20",
        "销售额": 500,
        "数量": 5,
        "利润率": 0.15,
        "备注": "复购",
    },
]

TEMPLATE_CONFIG = {
    "formulas": [{"key": "pass_rate", "label": "合格率(%)", "expr": "round([销售额] / [数量] * 100, 2)"}],
    "chart": {"type": "bar", "x": "产品分类", "y": "销售额", "aggregation": "sum"},
}


# ── fixtures ─────────────────────────────────────────


def _new_table(db: Session, ws: Workspace, name: str) -> DataTable:
    """建表元数据 + 物理表（无数据行）."""
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for field_name, field_type in TABLE_FIELDS:
        field = DataField(table_id=dt.id, name=field_name, field_type=field_type)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db.get_bind(), dt)
    return dt


def make_table(db: Session, ws: Workspace) -> DataTable:
    """建销售明细表（编号 / 分类 / 日期 / 数值 / 百分比）并写入 4 行."""
    dt = _new_table(db, ws, "销售明细")
    for values in TABLE_ROWS:
        create_row(db.get_bind(), dt, values, db=db)
    db.commit()
    return dt


@pytest.fixture
def owner(db) -> User:
    user = User(username="rec_owner", nickname="RecOwner")
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def ws(db, owner) -> Workspace:
    workspace = Workspace(name="RecWS", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def viewer(db, ws) -> User:
    user = User(username="rec_viewer", nickname="RecViewer")
    user.set_password("passw0rd")
    db.add(user)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def table(db, ws) -> DataTable:
    return make_table(db, ws)


def _login(client: TestClient, username: str) -> dict[str, str]:
    response = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def auth_owner(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


@pytest.fixture
def auth_viewer(client, viewer) -> dict[str, str]:
    return _login(client, viewer.username)


# ── 辅助断言 ──────────────────────────────────────────


def _normalize_body(body: dict[str, object], field_names: list[str]) -> dict[str, object]:
    """把推荐响应的公式 / 图表 / 汇总喂给 normalize_config，验证语义合法."""
    chart = body["chart"]
    summary = body["summary"]
    config = TemplateConfig(
        formulas=body["formulas"],  # type: ignore[arg-type]
        chart=chart["chart"] if isinstance(chart, dict) else None,  # type: ignore[index]
        summary=summary["summary"] if isinstance(summary, dict) else None,  # type: ignore[index]
    )
    return template_service.normalize_config(config, field_names)


def _normalize_example(example: dict[str, object], field_names: list[str]) -> dict[str, object]:
    """示例配置必须能直接落成模板."""
    config = TemplateConfig(
        formulas=example["formulas"],  # type: ignore[arg-type]
        chart=example["chart"],  # type: ignore[arg-type]
        summary=example["summary"],  # type: ignore[arg-type]
    )
    return template_service.normalize_config(config, field_names)


def _fields_by_name(body: dict[str, object]) -> dict[str, dict[str, object]]:
    return {field["name"]: field for field in body["fields"]}  # type: ignore[index]


# ── 字段画像 / 推荐内容 ───────────────────────────────


class TestRecommendEndpoint:
    def test_field_profiles_and_roles(self, client: TestClient, ws: Workspace, table: DataTable, auth_owner) -> None:
        """字段角色按类型与名称判定，画像基于实际抽样数据."""
        response = client.get(RECOMMEND.format(ws=ws.id), params={"table_id": table.id}, headers=auth_owner)
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["table_id"] == table.id
        assert body["row_count"] == 4
        assert body["sampled_rows"] == 4
        assert body["truncated"] is False

        fields = _fields_by_name(body)
        assert fields["订单编号"]["role"] == "identifier"
        assert fields["产品分类"]["role"] == "dimension"
        assert fields["生产日期"]["role"] == "time"
        assert fields["销售额"]["role"] == "metric"
        assert fields["数量"]["role"] == "metric"
        assert fields["利润率"]["role"] == "metric"
        assert fields["备注"]["role"] == "dimension"

        assert fields["订单编号"]["cardinality"] == 4
        assert fields["产品分类"]["cardinality"] == 3
        assert fields["产品分类"]["sample_values"] == ["华东", "华南", "华北"]
        assert fields["备注"]["completeness"] == pytest.approx(0.75)
        assert fields["销售额"]["completeness"] == 1.0
        assert all(field["reason"] for field in body["fields"])

    def test_formulas_parse_and_reference_visible_fields(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        """推荐公式不超过 4 条、key 唯一、表达式可 parse 且只引用可见字段."""
        body = client.get(RECOMMEND.format(ws=ws.id), params={"table_id": table.id}, headers=auth_owner).json()
        field_names = [field["name"] for field in body["fields"]]
        formulas = body["formulas"]

        assert 1 <= len(formulas) <= recommend_service.MAX_FORMULAS
        keys = [formula["key"] for formula in formulas]
        assert len(set(keys)) == len(keys)
        assert keys == [f"metric_{index}" for index in range(1, len(keys) + 1)]

        for item in formulas:
            node = formula_service.parse(item["expr"])
            assert formula_service.referenced_fields(node) <= set(field_names)
            assert item["label"]
            assert item["reason"]

        # 数值合计 / 百分比均值 / 数值比率三类都有业务含义
        exprs = [item["expr"] for item in formulas]
        assert "sum([销售额])" in exprs
        assert any("avg([利润率])" in expr for expr in exprs)
        assert "round([销售额]/[数量],2)" in exprs

    def test_chart_and_summary_are_normalizable(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        """推荐图表 / 分组汇总引用合法，可通过模板配置语义校验."""
        body = client.get(RECOMMEND.format(ws=ws.id), params={"table_id": table.id}, headers=auth_owner).json()
        field_names = [field["name"] for field in body["fields"]]

        chart = body["chart"]
        assert chart["chart"]["type"] == "bar"
        assert chart["chart"]["x"] == "产品分类"
        assert chart["chart"]["y"] == "销售额"
        assert chart["chart"]["aggregation"] == "sum"
        assert chart["reason"]

        summary = body["summary"]["summary"]
        assert summary["group_by"] == "产品分类"
        assert summary["sort_by"] == "sum(销售额)"
        assert summary["sort_order"] == "desc"
        assert summary["top_n"] == 10
        assert [(m["field"], m["agg"]) for m in summary["metrics"]] == [
            ("销售额", "sum"),
            ("产品分类", "count"),
        ]

        normalized = _normalize_body(body, field_names)
        assert normalized["chart"]["x"] == "产品分类"
        assert normalized["summary"]["metrics"][0]["field"] == "销售额"

    def test_examples_non_empty_and_normalizable(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        """典型示例至少 1 个，每个都带 overview 且配置可被 create_template 接受."""
        body = client.get(RECOMMEND.format(ws=ws.id), params={"table_id": table.id}, headers=auth_owner).json()
        field_names = [field["name"] for field in body["fields"]]
        examples = body["examples"]

        assert examples
        ids = [example["id"] for example in examples]
        assert len(set(ids)) == len(ids)
        assert "overview" in ids
        # 该表维度 / 数值 / 时间齐全，典型示例应覆盖分类对比、占比、趋势、比率
        assert {"category_compare", "metric_distribution", "composition", "trend", "ratio"} <= set(ids)

        for example in examples:
            assert example["name"]
            assert example["reason"]
            normalized = _normalize_example(example, field_names)
            assert set(normalized) == {"formulas", "chart", "summary", "fields", "limit"}

    def test_recommendations_are_deterministic(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_owner
    ) -> None:
        """同一张表多次请求结果完全一致（无随机性）."""
        url = RECOMMEND.format(ws=ws.id)
        first = client.get(url, params={"table_id": table.id}, headers=auth_owner).json()
        second = client.get(url, params={"table_id": table.id}, headers=auth_owner).json()
        assert first == second

    def test_empty_table_is_stable(self, db: Session, client: TestClient, ws: Workspace, auth_owner) -> None:
        """空表也要返回完整结构：画像 completeness=0，不崩溃."""
        empty = _new_table(db, ws, "空表")
        response = client.get(RECOMMEND.format(ws=ws.id), params={"table_id": empty.id}, headers=auth_owner)
        assert response.status_code == 200, response.text
        body = response.json()

        assert body["row_count"] == 0
        assert body["sampled_rows"] == 0
        assert body["truncated"] is False
        assert body["fields"]
        for field in body["fields"]:
            assert field["cardinality"] == 0
            assert field["completeness"] == 0.0
            assert field["sample_values"] == []
        assert body["examples"]
        field_names = [field["name"] for field in body["fields"]]
        for example in body["examples"]:
            _normalize_example(example, field_names)

    def test_viewer_can_read_recommendations(
        self, client: TestClient, ws: Workspace, table: DataTable, auth_viewer
    ) -> None:
        response = client.get(RECOMMEND.format(ws=ws.id), params={"table_id": table.id}, headers=auth_viewer)
        assert response.status_code == 200, response.text

    def test_non_member_403(self, client: TestClient, ws: Workspace, table: DataTable, auth_headers) -> None:
        """auth_headers 的 testuser 不是本工作区成员."""
        response = client.get(RECOMMEND.format(ws=ws.id), params={"table_id": table.id}, headers=auth_headers)
        assert response.status_code == 403

    def test_unknown_table_404(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        response = client.get(RECOMMEND.format(ws=ws.id), params={"table_id": 999999}, headers=auth_owner)
        assert response.status_code == 404

    def test_missing_table_id_422(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        response = client.get(RECOMMEND.format(ws=ws.id), headers=auth_owner)
        assert response.status_code == 422


class TestRoleRules:
    """角色判定的纯函数规则（不依赖 DB）."""

    @pytest.mark.parametrize(
        ("name", "field_type", "cardinality", "sampled_rows", "expected"),
        [
            ("销售额", "number", 10, 10, "metric"),
            ("利润率", "percentage", 10, 10, "metric"),
            ("生产日期", "date", 10, 10, "time"),
            ("更新时间", "datetime", 10, 10, "time"),
            ("产品分类", "select", 5, 10, "dimension"),
            ("是启用", "boolean", 2, 10, "dimension"),
            ("备注", "longtext", 8, 10, "dimension"),
            ("附件", "attachment", 0, 0, "ignored"),
            ("封面", "image", 0, 0, "ignored"),
            ("原始数据", "json", 0, 0, "ignored"),
            ("订单ID", "text", 3, 4, "identifier"),
            ("批次编号", "text", 3, 4, "identifier"),
            ("订单序号", "text", 3, 4, "identifier"),
            ("valid", "text", 3, 4, "dimension"),
            ("高基数文本", "text", 51, 100, "identifier"),
        ],
    )
    def test_classify_role(
        self, name: str, field_type: str, cardinality: int, sampled_rows: int, expected: str
    ) -> None:
        assert recommend_service.classify_role(name, field_type, cardinality, sampled_rows) == expected


def _profile(name: str, role: str, field_type: str = "text") -> dict[str, object]:
    """构造推荐纯函数所需的字段画像（只含函数读取的键）."""
    return {"name": name, "role": role, "field_type": field_type}


class TestPureFunctionBranches:
    """图表 / 汇总 / 典型示例 / 字段画像的兜底分支（纯函数，不依赖 DB）."""

    def test_chart_time_plus_metric_prefers_line(self) -> None:
        result = recommend_service.recommend_chart(
            [_profile("生产日期", "time", "date"), _profile("销售额", "metric", "number")]
        )
        assert result is not None
        assert result["chart"]["type"] == "line"
        assert result["chart"]["x"] == "生产日期"
        assert result["chart"]["y"] == "销售额"
        assert "趋势" in result["reason"]

    def test_chart_two_metrics_prefers_scatter(self) -> None:
        result = recommend_service.recommend_chart(
            [_profile("销售额", "metric", "number"), _profile("数量", "metric", "number")]
        )
        assert result is not None
        assert result["chart"]["type"] == "scatter"
        assert result["chart"]["x"] == "销售额"
        assert result["chart"]["y"] == "数量"

    def test_chart_single_metric_prefers_histogram(self) -> None:
        result = recommend_service.recommend_chart([_profile("销售额", "metric", "number")])
        assert result is not None
        assert result["chart"]["type"] == "histogram"

    def test_chart_dimension_only_counts(self) -> None:
        result = recommend_service.recommend_chart([_profile("产品分类", "dimension", "select")])
        assert result is not None
        assert result["chart"]["type"] == "bar"
        assert result["chart"]["aggregation"] == "count"

    def test_chart_identifier_only_falls_back_to_count(self) -> None:
        result = recommend_service.recommend_chart([_profile("订单编号", "identifier")])
        assert result is not None
        assert result["chart"]["y"] == "订单编号"
        assert result["chart"]["aggregation"] == "count"

    def test_chart_percentage_metric_uses_avg(self) -> None:
        result = recommend_service.recommend_chart(
            [_profile("产品分类", "dimension", "select"), _profile("利润率", "metric", "percentage")]
        )
        assert result is not None
        assert result["chart"]["aggregation"] == "avg"

    def test_chart_empty_profiles_returns_none(self) -> None:
        assert recommend_service.recommend_chart([]) is None

    def test_summary_time_field_used_as_group(self) -> None:
        result = recommend_service.recommend_summary(
            [_profile("生产日期", "time", "date"), _profile("销售额", "metric", "number")]
        )
        assert result is not None
        assert result["summary"]["group_by"] == "生产日期"

    def test_summary_metric_only_uses_global_aggregate(self) -> None:
        result = recommend_service.recommend_summary([_profile("利润率", "metric", "percentage")])
        assert result is not None
        assert result["summary"]["group_by"] is None
        assert result["summary"]["top_n"] is None
        assert result["summary"]["sort_by"] is None
        assert result["summary"]["metrics"] == [{"field": "利润率", "agg": "avg", "label": ""}]

    def test_summary_without_group_or_metric_returns_none(self) -> None:
        assert recommend_service.recommend_summary([_profile("订单编号", "identifier")]) is None

    def test_examples_overview_without_group_or_metric(self) -> None:
        examples = recommend_service.build_examples([_profile("订单编号", "identifier")])
        assert [example["id"] for example in examples] == ["overview"]
        assert examples[0]["summary"]["group_by"] is None
        assert examples[0]["chart"] is None

    def test_examples_empty_profiles(self) -> None:
        examples = recommend_service.build_examples([])
        assert len(examples) == 1
        assert examples[0]["formulas"] == []
        assert examples[0]["summary"] is None

    def test_examples_weather_profile_appends_range_example(self) -> None:
        """同表存在最高 / 最低气温 + 时间字段 → 追加昼夜温差领域示例（公式可解析）."""
        profiles = [
            _profile("城市", "partition_dimension"),
            _profile("日期", "time", "date"),
            _profile("最高气温", "metric", "float"),
            _profile("最低气温", "metric", "float"),
            _profile("平均气温", "metric", "float"),
        ]
        examples = recommend_service.build_examples(profiles)
        ids = [example["id"] for example in examples]
        assert "weather_range" in ids
        assert len(ids) == len(set(ids))  # id 唯一
        example = next(e for e in examples if e["id"] == "weather_range")
        assert example["formulas"] == [
            {
                "key": "temp_range",
                "label": "昼夜温差",
                "expr": "round([最高气温] - [最低气温], 2)",
                "order_by": "日期",
                "partition_by": "城市",
            }
        ]
        for spec in example["formulas"]:
            formula_service.parse(spec["expr"])  # 语法可解析
        assert example["summary"] is not None
        assert example["summary"]["group_by"] == "城市"
        assert example["chart"]["series"] == "城市"

    def test_examples_generic_profile_skips_domain_examples(self) -> None:
        """通用业务表（无气温字段名）不追加任何领域示例."""
        profiles = [
            _profile("订单编号", "identifier"),
            _profile("产品分类", "dimension", "select"),
            _profile("生产日期", "time", "date"),
            _profile("销售额", "metric", "number"),
            _profile("数量", "metric", "number"),
        ]
        ids = [example["id"] for example in recommend_service.build_examples(profiles)]
        assert "weather_range" not in ids

    def test_formulas_single_metric_skips_ratio(self) -> None:
        formulas = recommend_service.recommend_formulas([_profile("销售额", "metric", "number")])
        assert [item["expr"] for item in formulas] == ["sum([销售额])", "round([销售额]/sum([销售额])*100,2)"]

    def test_formulas_ratio_falls_back_to_first_two_metrics(self) -> None:
        formulas = recommend_service.recommend_formulas(
            [_profile("甲指标", "metric", "number"), _profile("乙指标", "metric", "number")]
        )
        assert "round([甲指标]/[乙指标],2)" in [item["expr"] for item in formulas]

    def test_formulas_deduplicate_identical_expressions(self) -> None:
        profiles = [_profile("销售额", "metric", "number"), _profile("销售额", "metric", "number")]
        exprs = [item["expr"] for item in recommend_service.recommend_formulas(profiles)]
        assert len(exprs) == len(set(exprs))

    def test_profile_fields_handles_containers_and_duplicates(self) -> None:
        fields = [
            DataField(name="标签", field_type="json"),
            DataField(name="销售额", field_type="number"),
            DataField(name="是否启用", field_type="boolean"),
        ]
        rows: list[dict[str, object]] = [
            {"标签": [], "销售额": None, "是否启用": True},
            {"标签": {"a": 1}, "销售额": 10, "是否启用": False},
            {"标签": "x", "销售额": 10, "是否启用": True},
            {"标签": "y", "销售额": 20, "是否启用": False},
        ]
        profiles = {item["name"]: item for item in recommend_service.profile_fields(fields, rows)}

        assert profiles["标签"]["role"] == "ignored"
        assert "不参与常规统计分析" in profiles["标签"]["reason"]
        assert profiles["标签"]["sample_values"] == ['{"a": 1}', "x", "y"]
        assert profiles["销售额"]["sample_values"] == ["10", "20"]
        assert profiles["销售额"]["completeness"] == 0.75
        assert profiles["是否启用"]["sample_values"] == ["是", "否"]

    def test_profile_fields_high_cardinality_identifier_reason(self) -> None:
        rows = [{"备注": f"值{index}"} for index in range(51)]
        profiles = recommend_service.profile_fields([DataField(name="备注", field_type="text")], rows)
        assert profiles[0]["role"] == "identifier"
        assert "唯一值较多" in profiles[0]["reason"]

    def test_unknown_field_type_falls_back_to_dimension(self) -> None:
        assert recommend_service.classify_role("自定义", "custom_type", 3, 4) == "dimension"


# ── 模板复制 ──────────────────────────────────────────


def _create_template(client: TestClient, ws_id: int, headers: dict[str, str], name: str) -> dict[str, object]:
    response = client.post(
        TEMPLATES.format(ws=ws_id),
        json={"name": name, "description": "描述", "table_id": None, "config": TEMPLATE_CONFIG},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


class TestDuplicateTemplate:
    def test_duplicate_default_name_and_increment(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        """默认命名「原名 副本」，重名自动追加 (2)、(3)… 且列表出现多个模板."""
        original = _create_template(client, ws.id, auth_owner, "销售分析")
        url = TEMPLATES.format(ws=ws.id) + f"/{original['id']}/duplicate"

        first = client.post(url, headers=auth_owner)
        assert first.status_code == 201, first.text
        assert first.json()["name"] == "销售分析 副本"

        second = client.post(url, headers=auth_owner)
        assert second.status_code == 201, second.text
        assert second.json()["name"] == "销售分析 副本 (2)"

        third = client.post(url, headers=auth_owner)
        assert third.status_code == 201, third.text
        assert third.json()["name"] == "销售分析 副本 (3)"

        listed = client.get(TEMPLATES.format(ws=ws.id), headers=auth_owner).json()
        assert len(listed) == 4
        assert {tpl["name"] for tpl in listed} == {
            "销售分析",
            "销售分析 副本",
            "销售分析 副本 (2)",
            "销售分析 副本 (3)",
        }

    def test_duplicate_with_custom_name(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        original = _create_template(client, ws.id, auth_owner, "月度分析")
        url = TEMPLATES.format(ws=ws.id) + f"/{original['id']}/duplicate"
        response = client.post(url, json={"name": "自定义副本"}, headers=auth_owner)
        assert response.status_code == 201, response.text
        assert response.json()["name"] == "自定义副本"

        # 显式名称为空串时回退自动命名
        fallback = client.post(url, json={"name": ""}, headers=auth_owner)
        assert fallback.status_code == 201, fallback.text
        assert fallback.json()["name"] == "月度分析 副本"

    def test_duplicate_long_name_terminates(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        """200 字上限的模板名复制不能因截断后重名进入死循环."""
        long_name = "分析" * 100
        original = _create_template(client, ws.id, auth_owner, long_name)
        url = TEMPLATES.format(ws=ws.id) + f"/{original['id']}/duplicate"

        first = client.post(url, headers=auth_owner)
        assert first.status_code == 201, first.text
        second = client.post(url, headers=auth_owner)
        assert second.status_code == 201, second.text
        names = {first.json()["name"], second.json()["name"]}
        assert len(names) == 2
        assert all(len(name) <= 200 and name != long_name for name in names)

    def test_duplicate_copies_config_and_metadata(
        self, client: TestClient, ws: Workspace, table: DataTable, owner: User, auth_owner
    ) -> None:
        """复制 config / table_id / description，创建人改为当前用户，原模板不受影响."""
        response = client.post(
            TEMPLATES.format(ws=ws.id),
            json={
                "name": "带表模板",
                "description": "原始说明",
                "table_id": table.id,
                "config": TEMPLATE_CONFIG,
            },
            headers=auth_owner,
        )
        assert response.status_code == 201, response.text
        original = response.json()
        copy = client.post(TEMPLATES.format(ws=ws.id) + f"/{original['id']}/duplicate", headers=auth_owner).json()

        assert copy["id"] != original["id"]
        assert copy["name"] == "带表模板 副本"
        assert copy["description"] == "原始说明"
        assert copy["table_id"] == table.id
        assert copy["config"] == original["config"]
        assert copy["created_by_id"] == owner.id
        assert copy["updated_by_id"] == owner.id

        # 修改副本不影响原模板
        updated = client.put(
            TEMPLATES.format(ws=ws.id) + f"/{copy['id']}",
            json={"name": "副本改名", "config": {"formulas": []}},
            headers=auth_owner,
        )
        assert updated.status_code == 200, updated.text
        origin_again = client.get(TEMPLATES.format(ws=ws.id) + f"/{original['id']}", headers=auth_owner).json()
        assert origin_again["name"] == original["name"]
        assert origin_again["config"] == original["config"]

    def test_viewer_cannot_duplicate(self, client: TestClient, ws: Workspace, auth_owner, auth_viewer) -> None:
        original = _create_template(client, ws.id, auth_owner, "只读模板")
        response = client.post(TEMPLATES.format(ws=ws.id) + f"/{original['id']}/duplicate", headers=auth_viewer)
        assert response.status_code == 403

    def test_duplicate_unknown_template_404(self, client: TestClient, ws: Workspace, auth_owner) -> None:
        response = client.post(TEMPLATES.format(ws=ws.id) + "/999999/duplicate", headers=auth_owner)
        assert response.status_code == 404

    def test_non_member_cannot_duplicate(self, client: TestClient, ws: Workspace, auth_owner, auth_headers) -> None:
        original = _create_template(client, ws.id, auth_owner, "跨区模板")
        response = client.post(TEMPLATES.format(ws=ws.id) + f"/{original['id']}/duplicate", headers=auth_headers)
        assert response.status_code == 403
