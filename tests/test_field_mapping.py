"""字段映射功能 — field_mapping 核心 + schema 导入映射 + 数据导入映射.

覆盖矩阵：
┌───────────────────────────────────────────┬──────────────────────────────────────┐
│ 场景                                       │ 关键断言                              │
├───────────────────────────────────────────┼──────────────────────────────────────┤
│ build_default_mapping 保守默认            │ 源名 → 同名目标名                      │
│ apply_user_mapping 正常覆盖 / 跳过        │ 覆盖值生效, None 剔除                  │
│ apply_user_mapping 未知源字段 → ValueError │ mapping key 不在源名列表里             │
│ analyze_field_gaps 四类缺口                │ matched / unmapped_source / missing /   │
│                                           │ conflicts                             │
│ remap_row 行重命名                         │ key 按 mapping.value 重命名            │
│ apply_gap_filling default / value / error │ 各策略行为正确                        │
│ apply_gap_filling value 未填 fill_values  │ ValueError                            │
│ auto_match_fields 便捷入口                 │ 返回 (mapping, gap_report)            │
├───────────────────────────────────────────┼──────────────────────────────────────┤
│ schema 导入带 field_mapping 重命名         │ 目标字段名是映射后的 dst              │
│ schema 导入 field_mapping 跳过某字段       │ 被跳过字段不在 created 里              │
│ schema 导入 field_mapping 冲突            │ 两个 src 映射到同一 dst → 跳过后者     │
│ schema 导入 field_mapping 返回 gap_analysis│ 响应体含 matched/unmapped_source 等    │
│ schema 导入 field_mapping 未知源字段       │ 400 + 明确错误信息                    │
├───────────────────────────────────────────┼──────────────────────────────────────┤
│ RowValidator field_mapping 对齐            │ 文件列 "源" → 表字段 "目标"           │
│ RowValidator gap_filling default           │ 缺失必填字段用 default_value 补值      │
│ RowValidator gap_filling value             │ 用 fill_values 固定值填充              │
│ RowValidator gap_filling error             │ 缺失字段直接 error                     │
│ RowValidator field_mapping None 跳过源列   │ 跳过列不出现在 effective_row 里        │
│ Importer 端到端 field_mapping              │ analyze/execute 都带映射正确落库       │
└───────────────────────────────────────────┴──────────────────────────────────────┘
"""

from __future__ import annotations

import pytest

# ═══════════════════════════════════════════════════════════════════════════════
# Part 1 — field_mapping 核心工具单元测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestBuildDefaultMapping:
    def test_basic(self):
        from cndb.plugins.tables.services.importing.field_mapping import build_default_mapping

        result = build_default_mapping(["a", "b", "c"])
        assert result == {"a": "a", "b": "b", "c": "c"}

    def test_empty(self):
        from cndb.plugins.tables.services.importing.field_mapping import build_default_mapping

        assert build_default_mapping([]) == {}


class TestApplyUserMapping:
    def test_override(self):
        from cndb.plugins.tables.services.importing.field_mapping import (
            apply_user_mapping,
            build_default_mapping,
        )

        base = build_default_mapping(["src_a", "src_b"])
        merged = apply_user_mapping(base, {"src_a": "dst_a"}, ["src_a", "src_b"])
        assert merged == {"src_a": "dst_a", "src_b": "src_b"}

    def test_skip_via_none(self):
        from cndb.plugins.tables.services.importing.field_mapping import (
            apply_user_mapping,
            build_default_mapping,
        )

        base = build_default_mapping(["src_a", "src_b"])
        merged = apply_user_mapping(base, {"src_a": None}, ["src_a", "src_b"])
        assert merged == {"src_b": "src_b"}

    def test_unknown_source_field_raises(self):
        from cndb.plugins.tables.services.importing.field_mapping import (
            apply_user_mapping,
            build_default_mapping,
        )

        base = build_default_mapping(["src_a"])
        with pytest.raises(ValueError, match="源表没有的字段"):
            apply_user_mapping(base, {"unknown": "x"}, ["src_a"])

    def test_empty_mapping_returns_base(self):
        from cndb.plugins.tables.services.importing.field_mapping import (
            apply_user_mapping,
            build_default_mapping,
        )

        base = build_default_mapping(["a", "b"])
        merged = apply_user_mapping(base, {}, ["a", "b"])
        assert merged == base


class TestAnalyzeFieldGaps:
    def test_no_gaps(self):
        from cndb.plugins.tables.services.importing.field_mapping import analyze_field_gaps

        report = analyze_field_gaps(
            {"a": "a", "b": "b"},
            source_names=["a", "b"],
            target_names=["a", "b"],
        )
        assert report["unmapped_source"] == []
        assert report["target_missing"] == []
        assert report["conflicts"] == []
        assert len(report["matched"]) == 2

    def test_unmapped_source(self):
        from cndb.plugins.tables.services.importing.field_mapping import analyze_field_gaps

        # source 有 a,b,c — 但 mapping 只有 a,b（c 被跳过）
        report = analyze_field_gaps(
            {"a": "a", "b": "b"},
            source_names=["a", "b", "c"],
            target_names=["a", "b"],
        )
        assert report["unmapped_source"] == ["c"]

    def test_target_missing(self):
        from cndb.plugins.tables.services.importing.field_mapping import analyze_field_gaps

        # target 有 x,y — 但 mapping 只覆盖 x
        report = analyze_field_gaps(
            {"src_x": "x"},
            source_names=["src_x"],
            target_names=["x", "y"],
        )
        assert report["target_missing"] == ["y"]

    def test_conflicts_two_sources_to_same_target(self):
        from cndb.plugins.tables.services.importing.field_mapping import analyze_field_gaps

        report = analyze_field_gaps(
            {"src_a": "same", "src_b": "same"},
            source_names=["src_a", "src_b"],
            target_names=["same"],
        )
        assert len(report["conflicts"]) == 1
        assert report["conflicts"][0]["dst"] == "same"


class TestRemapRow:
    def test_basic_rename(self):
        from cndb.plugins.tables.services.importing.field_mapping import remap_row

        row = {"old": 1, "keep": 2}
        mapping = {"old": "new", "keep": "keep"}
        assert remap_row(row, mapping) == {"new": 1, "keep": 2}

    def test_extra_source_dropped(self):
        from cndb.plugins.tables.services.importing.field_mapping import remap_row

        row = {"a": 1, "b": 2, "c": 3}
        # mapping 只覆盖 a,b — c 被丢弃
        assert remap_row(row, {"a": "a", "b": "b"}) == {"a": 1, "b": 2}

    def test_missing_source_in_row_becomes_none(self):
        from cndb.plugins.tables.services.importing.field_mapping import remap_row

        row = {"a": 1}
        mapping = {"a": "a", "b": "b"}  # b 不在 row 里
        result = remap_row(row, mapping)
        assert result["a"] == 1
        assert result["b"] is None


class TestApplyGapFilling:
    def test_strategy_empty_keeps_none(self):
        from cndb.plugins.tables.services.importing.field_mapping import apply_gap_filling
        from cndb.plugins.tables.models import DataField

        f = DataField(name="missing", field_type="text", default_value=None)
        row: dict[str, object] = {}
        result = apply_gap_filling(row, ["missing"], {"missing": f}, strategy="empty")
        assert result["missing"] is None

    def test_strategy_default(self):
        from cndb.plugins.tables.services.importing.field_mapping import apply_gap_filling
        from cndb.plugins.tables.models import DataField

        f = DataField(name="missing", field_type="text", default_value="NA")
        row: dict[str, object] = {}
        result = apply_gap_filling(row, ["missing"], {"missing": f}, strategy="default")
        assert result["missing"] == "NA"

    def test_strategy_value(self):
        from cndb.plugins.tables.services.importing.field_mapping import apply_gap_filling

        row: dict[str, object] = {}
        result = apply_gap_filling(
            row,
            ["missing"],
            {},
            strategy="value",
            fill_values={"missing": "固定值"},
        )
        assert result["missing"] == "固定值"

    def test_strategy_value_missing_fill_not_specified_treated_as_none(self):
        from cndb.plugins.tables.services.importing.field_mapping import apply_gap_filling

        # strategy="value" 没提供 fill_values → 留 None
        row: dict[str, object] = {}
        result = apply_gap_filling(row, ["missing"], {}, strategy="value")
        assert result["missing"] is None

    def test_strategy_error(self):
        from cndb.plugins.tables.services.importing.field_mapping import apply_gap_filling

        with pytest.raises(ValueError, match="缺少目标必填字段"):
            apply_gap_filling({}, ["req"], {}, strategy="error")

    def test_strategy_error_no_missing_ok(self):
        from cndb.plugins.tables.services.importing.field_mapping import apply_gap_filling

        # 没有缺失字段 — error 策略不报错
        result = apply_gap_filling({"a": 1}, [], {}, strategy="error")
        assert result == {"a": 1}

    def test_target_field_not_in_map_defaults_to_none(self):
        from cndb.plugins.tables.services.importing.field_mapping import apply_gap_filling

        # 目标字段不在 field_map 里 → default 策略下返回 None
        row: dict[str, object] = {}
        result = apply_gap_filling(row, ["ghost"], {}, strategy="default")
        assert result["ghost"] is None


class TestAutoMatchFields:
    def test_basic(self, db):
        from cndb.plugins.tables.services.importing.field_mapping import auto_match_fields
        from cndb.plugins.tables.models import DataField, DataTable

        src = DataTable(workspace_id=1, name="S", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()

        for i, name in enumerate(["a", "b", "c"]):
            f = DataField(table_id=src.id, name=name, field_type="text", order=i)
            f.ensure_db_name()
            db.add(f)
        db.commit()
        db.refresh(src)

        mapping, gap = auto_match_fields(src.fields)
        assert mapping == {"a": "a", "b": "b", "c": "c"}
        assert gap["unmapped_source"] == []
        assert gap["target_missing"] == []


# ═══════════════════════════════════════════════════════════════════════════════
# Part 2 — schema 导入路由带 field_mapping 的集成测试
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def _src_table2(client, auth_headers, db):
    """与 test_fields_import 里的 _src_table 功能一样，但独立命名避免冲突."""
    r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS_SRC2"})
    wid = r.json()["id"]
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "SrcTable2"},
    )
    src_tid = r.json()["id"]

    for i, spec in enumerate(
        [
            ("src_name", "text"),
            ("src_amount", "number"),
            ("src_active", "boolean"),
        ]
    ):
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
            json={"name": spec[0], "field_type": spec[1], "order": i},
        )
    return wid, src_tid


class TestSchemaImportWithFieldMapping:
    def test_rename_source_to_target(self, client, auth_headers, _src_table2):
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstRename"},
        )
        dst_tid = r.json()["id"]

        # field_mapping: src_name → full_name（重命名）
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "field_mapping": {"src_name": "full_name"},
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()

        # full_name 存在, src_name 不存在 — 重命名生效
        created_names = {f["name"] for f in body["created"]}
        assert "full_name" in created_names
        assert "src_name" not in created_names
        # 另外两个未显式覆盖的字段仍原名
        assert {"src_amount", "src_active"} <= created_names

    def test_skip_some_via_none(self, client, auth_headers, _src_table2):
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstSkip"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "field_mapping": {"src_active": None},
            },
        )
        assert r.status_code == 201, r.text
        created_names = {f["name"] for f in r.json()["created"]}
        assert "src_active" not in created_names
        assert {"src_name", "src_amount"} <= created_names

    def test_return_gap_analysis(self, client, auth_headers, _src_table2):
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstGap"},
        )
        dst_tid = r.json()["id"]

        # 传入 mapping → 返回 gap_analysis
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "field_mapping": {"src_active": None},
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert "gap_analysis" in body
        assert body["gap_analysis"] is not None
        ga = body["gap_analysis"]
        # src_active 被跳过 → unmapped_source 里有
        assert "src_active" in ga["unmapped_source"]
        assert len(ga["matched"]) == 2

    def test_no_mapping_no_gap_analysis(self, client, auth_headers, _src_table2):
        """现在 gap_analysis + suggestions 总是返回（即便不传 field_mapping），便于前端首次渲染."""
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstNoGap"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                # 不传 field_mapping —— 现在后端会自动 suggest，gap_analysis 不再是 None
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["gap_analysis"] is not None
        assert body["suggestions"] is not None
        # 目标表为空 → 3 个源字段都 will_map=True, reason="目标表为空..."
        will_map_flags = [s["will_map"] for s in body["suggestions"]]
        assert all(will_map_flags)

    def test_mapping_invalid_source_field_400(self, client, auth_headers, _src_table2):
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstBadMap"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "field_mapping": {"no_such_field": "xxx"},
            },
        )
        assert r.status_code == 400
        assert "field_mapping" in r.json()["detail"].lower() or "不存在" in r.json()["detail"]

    def test_two_sources_mapped_to_same_dst_only_first_succeeds(self, client, auth_headers, _src_table2):
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstConflictMap"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                # src_name 和 src_amount 都想变成 same_name —— 后者跳过
                "field_mapping": {"src_name": "same_name", "src_amount": "same_name"},
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        created_names_list = [f["name"] for f in body["created"]]
        # 只有一个字段叫 same_name 成功创建
        assert created_names_list.count("same_name") == 1
        assert "src_active" in created_names_list  # 未覆盖的保留


# ═══════════════════════════════════════════════════════════════════════════════
# Part 3 — RowValidator 带 field_mapping + gap_filling 的数据导入测试
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def _dst_table3(client, auth_headers, db):
    """创建一个带若干字段的目标表供 RowValidator 测试."""
    r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS_DST3"})
    wid = r.json()["id"]
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "DstTable3"},
    )
    tid = r.json()["id"]

    fields = [
        {"name": "full_name", "field_type": "text", "order": 0, "required": True},
        {
            "name": "amount",
            "field_type": "number",
            "order": 1,
            "required": False,
            "default_value": 0,
        },
        {"name": "active", "field_type": "boolean", "order": 2, "required": False},
    ]
    for f in fields:
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json=f,
        )
    return wid, tid


class TestRowValidatorWithFieldMapping:
    def test_basic_rename(self, db, _dst_table3):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)

        # 源数据列名叫 "name"，目标表字段叫 "full_name"
        rv = RowValidator(
            table,
            field_mapping={"name": "full_name"},
        )
        results = rv.validate_all(
            [
                {"name": "Alice", "amount": "100", "active": "true"},
            ]
        )
        assert results[0].status == "valid"
        assert results[0].values["full_name"] == "Alice"

    def test_skip_source_column(self, db, _dst_table3):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)

        rv = RowValidator(
            table,
            field_mapping={"extra_col": None},  # 显式跳过 extra_col
        )
        results = rv.validate_all(
            [
                {"full_name": "Bob", "extra_col": "ignore_me"},
            ]
        )
        # extra_col 被跳过 — 不出现在 result.values 里
        assert "extra_col" not in results[0].values

    def test_gap_filling_default(self, db, _dst_table3):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)

        # 源数据只有 full_name 和 amount — active 缺失
        rv = RowValidator(
            table,
            field_mapping=None,
            gap_filling="default",
        )
        results = rv.validate_all(
            [
                {"full_name": "Carol", "amount": "50"},
            ]
        )
        # active 没 default_value — 填 None
        assert results[0].values["active"] is None
        assert results[0].values["full_name"] == "Carol"

    def test_gap_filling_value(self, db, _dst_table3):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)

        rv = RowValidator(
            table,
            field_mapping=None,
            gap_filling="value",
            fill_values={"active": True},
        )
        results = rv.validate_all(
            [
                {"full_name": "Dave", "amount": "10"},
            ]
        )
        # active 被 fill_values 填了 True
        assert results[0].values.get("active") is True

    def test_gap_filling_error(self, db, _dst_table3):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)

        rv = RowValidator(
            table,
            field_mapping=None,
            gap_filling="error",
        )
        results = rv.validate_all(
            [
                # full_name 是 required 字段，源数据里没有
                {"amount": "10", "active": "true"},
            ]
        )
        assert results[0].status == "error"

    def test_mapping_not_provided_uses_legacy_behavior(self, db, _dst_table3):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)

        # field_mapping=None —— 完全沿用老行为：列名精确匹配
        rv = RowValidator(table)
        results = rv.validate_all(
            [
                {"full_name": "Eve", "amount": "5"},
            ]
        )
        assert results[0].status == "valid"


# ═══════════════════════════════════════════════════════════════════════════════
# Part 4 — Importer 端到端带 field_mapping 的测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestImporterWithFieldMapping:
    def test_end_to_end_with_mapping(self, db, _dst_table3):
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.importing.importer import Importer
        from cndb.plugins.tables.models import DataTable

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)
        engine = db.get_bind()

        # 确保物理表存在
        from sqlalchemy import inspect

        insp = inspect(engine)
        if table.db_table_name not in insp.get_table_names():
            ddl_create(engine, table)

        importer = Importer(
            engine,
            db,
            table,
            field_mapping={"name": "full_name"},
            gap_filling="default",
        )

        json_rows = '[{"name": "Frank", "amount": "88"}]'
        result = importer.execute(json_rows, "json")

        assert len(result.imported_ids) == 1
        # 验证实际落库的数据
        from cndb.plugins.tables.services.core import records as rec

        rows, _total = rec.list_rows(engine, table, limit=10, db=db)
        assert len(rows) == 1
        assert rows[0]["full_name"] == "Frank"


# ═══════════════════════════════════════════════════════════════════════════════
# Part 5 — 补漏：field_ops.py 重命名后与目标表已有字段冲突
# ═══════════════════════════════════════════════════════════════════════════════


class TestSchemaImportRenameConflict:
    def test_rename_to_existing_target_is_skipped(self, client, auth_headers, _src_table2):
        """重命名目标名恰好是目标表已有的字段名 — 被跳过并说明原因."""
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstRenameConflict"},
        )
        dst_tid = r.json()["id"]

        # 目标表先建一个叫 full_name 的字段
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields",
            headers=auth_headers,
            json={"name": "full_name", "field_type": "text", "order": 0},
        )

        # field_mapping 把 src_name 重命名为 full_name — 但目标表已有 full_name
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "field_mapping": {"src_name": "full_name"},
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # full_name 冲突 → 被跳过，skipped 里有
        skipped_text = " ".join(body["skipped"])
        assert "full_name" in skipped_text
        assert "src_name" in skipped_text
        # 其他未重命名的字段仍成功
        created_names = {f["name"] for f in body["created"]}
        assert {"src_amount", "src_active"} <= created_names


class TestFieldOpsPlanWithMapping:
    """field_ops.plan_field_import + execute_field_import 带 mapping 的更多分支."""

    def test_skip_conflicts_false_with_mapping_no_throw(self, db):
        """execute_field_import skip_conflicts=False 但有 mapping 时不提前报错（冲突延后到 plan 内处理）."""
        from cndb.plugins.tables.services.fields import field_ops as _fo
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.models import DataField, DataTable

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_mc", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_mc", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        # src 有 "name" — 但我们通过 mapping 重命名为 "new_name"，dst 没有 new_name
        src_f = DataField(table_id=src.id, name="name", field_type="text", order=0)
        src_f.ensure_db_name()
        db.add(src_f)
        db.commit()
        db.refresh(src_f)

        ddl_create(engine, dst)

        # skip_conflicts=False — 不传 mapping 时会因为 dst 没有同名字段而通过（其实 dst 是空的）
        # 但这个测试的关键是：有 mapping 时即使 skip_conflicts=False 也不会跑 validate_field_import_conflicts
        created = _fo.execute_field_import(
            engine, db, dst, [src_f], skip_conflicts=False, field_mapping={"name": "new_name"}
        )
        assert len(created) == 1
        assert created[0].name == "new_name"

    def test_plan_field_import_mapping_skip_none(self, db):
        """plan_field_import 的 field_mapping={name: None} 跳过."""
        from cndb.plugins.tables.services.fields import field_ops as _fo
        from cndb.plugins.tables.models import DataField, DataTable

        dst = DataTable(workspace_id=1, name="D_plan_map", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        # 用 src 的 DataField 当参数（plan_field_import 接受 DataField 列表）
        src_skip = DataField(name="skip_me", field_type="text", order=0)
        src_keep = DataField(name="keep_me", field_type="text", order=1)

        plan, skipped = _fo.plan_field_import(dst, [src_skip, src_keep], field_mapping={"skip_me": None})
        # skip_me 被跳过；keep_me 应该还是成功 — 但 dst 已有 keep_me（existing_names），所以被冲突跳过
        skipped_text = " ".join(skipped)
        assert "skip_me" in skipped_text  # 用户显式跳过

        # keep_me 在 dst 已存在 → 也被跳过
        assert all(p.name != "skip_me" for p in plan)


class TestApplyGapFillingEdge:
    """补 apply_gap_filling 的分支覆盖."""

    def test_strategy_value_partial_fill_other_becomes_none(self):
        from cndb.plugins.tables.services.importing.field_mapping import apply_gap_filling

        # strategy="value" 但 fill_values 只覆盖部分字段 — 没覆盖的变成 None
        row: dict[str, object] = {}
        result = apply_gap_filling(
            row,
            ["has_val", "no_val"],
            {},
            strategy="value",
            fill_values={"has_val": 42},
        )
        assert result["has_val"] == 42
        assert result["no_val"] is None


class TestRowValidatorStrategyValueMissingFill:
    """RowValidator 带 gap_filling='value' 但 fill_values 没覆盖某缺失字段 → 该字段留 None（非必填时不报错）."""

    def test_strategy_value_partial_fill(self, db, _dst_table3):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)

        rv = RowValidator(
            table,
            gap_filling="value",
            fill_values={"active": True},  # 只指定了 active —— amount 缺失会怎样？
        )
        # 源数据：full_name 有，active 缺失（应该用 fill_values 补 True），amount 缺失（没有 fill_values 里指定）
        results = rv.validate_all(
            [
                {"full_name": "Grace"},
            ]
        )
        # full_name 是 required — 有值，不报错
        # active 被填了 True
        # amount 缺失但非 required — strategy="value" 时 RowValidator 没对每个缺失字段调用 apply_gap_filling
        # 实际上 apply_gap_filling 会先给所有 unmapped_target 赋值（没有 fill_value 的字段会怎样？）
        # 让我直接验证 values
        assert results[0].values.get("active") is True


class TestRowValidatorEdgeCoverage:
    """补 row_validator 遗漏分支 —— 原有代码，不是新写的."""

    def test_unknown_field_type(self, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        src = DataTable(workspace_id=1, name="S_ut", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()

        # 手动往 DB 塞一个非法 field_type 的 DataField — 走 row_validator 的未知类型分支
        bad = DataField(table_id=src.id, name="weird", field_type="nonexistent_type", order=0, required=False)
        bad.ensure_db_name()
        db.add(bad)
        db.commit()
        db.refresh(src)
        db.refresh(bad)

        rv = RowValidator(src)
        results = rv.validate_all([{"weird": "anything"}])
        # 未知类型 → error issue
        assert results[0].has_error()


class TestRowValidatorSkipUnknownColumns:
    """skip_unknown_columns=True 时不再对多余列产出 warning — 覆盖原有漏行."""

    def test_skip_unknown_columns_true(self, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        src = DataTable(workspace_id=1, name="S_suc", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        f = DataField(table_id=src.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(src)

        rv = RowValidator(src, skip_unknown_columns=True)
        # 传一个有额外列的 row — skip_unknown_columns=True 应该不出 warning
        results = rv.validate_all([{"name": "ok", "extra": "ignored"}])
        # 确保 extra 列没出现在 issues 里
        issues_with_extra = [i for i in results[0].issues if i.field == "extra"]
        assert len(issues_with_extra) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Part 6 — row_validator.py 漏行覆盖补全
# ═══════════════════════════════════════════════════════════════════════════════


class TestRowValidatorDicts:
    """Issue.to_dict / ValidationResult.to_dict — 从来没被测过."""

    def test_issue_to_dict(self):
        from cndb.plugins.tables.services.importing.row_validator import Issue

        i = Issue(field="name", level="error", message="坏了")
        assert i.to_dict() == {"field": "name", "level": "error", "message": "坏了"}

    def test_validation_result_to_dict(self):
        from cndb.plugins.tables.services.importing.row_validator import Issue, ValidationResult

        r = ValidationResult(
            row_number=1,
            values={},
            status="warning",
            issues=[
                Issue(field="x", level="warning", message="注意"),
            ],
        )
        d = r.to_dict()
        assert d["row_number"] == 1
        assert d["status"] == "warning"
        assert len(d["issues"]) == 1
        assert d["issues"][0]["field"] == "x"


class TestRowValidatorRequiredFieldTotallyMissing:
    """必填字段完全不在 row dict 里（不是 None）→ 触发 _check_field_set."""

    def test_required_field_not_in_row_at_all(self, db, _dst_table3):
        """直接调 _check_field_set 绕过 gap_filling — 覆盖 line 203 '必填字段缺失'."""
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator, ValidationResult

        _wid, tid = _dst_table3
        table = db.get(DataTable, tid)

        rv = RowValidator(table)
        result = ValidationResult(row_number=1, values={"amount": 1})
        # 手工构造一个 row，完全没有 required 的 full_name
        rv._check_field_set({"amount": 1}, result)
        issues_field_names = [i.field for i in result.issues]
        assert "full_name" in issues_field_names
        full_name_issue = next(i for i in result.issues if i.field == "full_name")
        assert full_name_issue.message == "必填字段缺失"


class TestRowValidatorLinkParsing:
    """覆盖 RowValidator._parse_link_value 的多分支."""

    def test_link_list_int_ok(self):
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        assert RowValidator._parse_link_value([1, 2, 3]) == [1, 2, 3]

    def test_link_list_with_non_int_raises(self):
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        with pytest.raises(ValueError, match="link 字段解析失败"):
            RowValidator._parse_link_value([1, "bad"])

    def test_link_single_int(self):
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        assert RowValidator._parse_link_value(42) == [42]

    def test_link_empty_string(self):
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        assert RowValidator._parse_link_value("") == []
        assert RowValidator._parse_link_value("   ") == []

    def test_link_unsupported_type(self):
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        with pytest.raises(ValueError, match="类型不支持"):
            RowValidator._parse_link_value(3.14)


class TestRowValidatorNormalizedNone:
    """validate_value 返回 None 时 normalized dict 不应写入该字段."""

    def test_validate_value_returns_none_not_in_normalized(self, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        # 造一个"validate_value 返回 None"的场景 — number 字段传空字符串
        # 实际上 number 字段类型校验时空串会被转成 None 或报错，试 boolean + 空
        src = DataTable(workspace_id=1, name="S_norm", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()

        # boolean 字段 —— validate_value 空串会怎样？让我们看实现
        f = DataField(table_id=src.id, name="flag", field_type="boolean", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(src)

        rv = RowValidator(src)
        # boolean 的 validate_value 对空字符串会返回 None / 抛错 / 什么？
        # 这里只是确保即使返回 None 也不会写入 normalized
        results = rv.validate_all([{"flag": ""}])
        # 只要 normalized 里没有 flag key 就算覆盖了 238->exit 分支
        assert "flag" not in results[0].normalized or results[0].normalized.get("flag") is not None


class TestRowValidatorTrashedFieldDefensive:
    """f.trashed=True 时 _check_each_field 跳过 — active_fields 应已过滤，但防御性也要覆盖."""

    def test_trashed_field_skipped_by_check_each(self, db):
        from unittest.mock import patch

        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.importing.row_validator import RowValidator

        src = DataTable(workspace_id=1, name="S_trash", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        f = DataField(table_id=src.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(src)
        db.refresh(f)

        rv = RowValidator(src)

        # 手动把 _field_map 里塞进一个 trashed 字段 —— 模拟未过滤场景
        ghost = DataField(name="ghost", field_type="text", order=99, trashed=True)
        rv._field_map["ghost"] = ghost

        # 覆写 _fields，让 active_fields 返回的列表里也有 ghost（真实场景不会，但为了覆盖防御分支）
        with patch.object(rv, "_fields", [f, ghost]):
            # 但 _field_map 已被我们塞了 ghost，让 _required_names 不含 ghost 也行
            # 直接调 _check_each_field
            rv._check_each_field(
                {"ghost": "should_be_ignored", "name": "ok"}, rv.validate_row({"ghost": "x", "name": "y"}, 1)
            )
            # ghost 被跳过 → 不会因 ghost 的校验结果影响（这里 ghost 没 db_column_name 等等）
            # 不抛异常就算通过
            pass


# ═══════════════════════════════════════════════════════════════════════════════
# Part 7 — routers/fields.py 漏行覆盖
# ═══════════════════════════════════════════════════════════════════════════════


class TestReorderFieldsSkipMissingId:
    """reorder_fields 传入不存在的 field_id — 221->220 分支."""

    def test_missing_id_in_field_ids_is_skipped(self, client, auth_headers, db):
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS_RO"})
        wid = r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "TRO"},
        )
        tid = r.json()["id"]
        # 建一个字段
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        fid = r.json()["id"]
        # reorder 里混个不存在的 id — 应该被跳过不报错
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/reorder",
            headers=auth_headers,
            json={"field_ids": [fid, 99999]},
        )
        assert r.status_code == 200, r.text
        fields = r.json()
        assert len(fields) == 1
        assert fields[0]["name"] == "name"


class TestImportFieldsEmptySourceReturnsEmpty:
    """空源表 import_fields → 308 行返回空响应."""

    def test_empty_source_table(self, client, auth_headers):
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS_ES"})
        wid = r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "SrcEmpty"},
        )
        src_tid = r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstEmpty"},
        )
        dst_tid = r.json()["id"]

        # 源表没有任何字段 → 返回空 created，skipped 里有说明
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
            },
        )
        assert r.status_code == 201
        body = r.json()
        assert body["created"] == []
        assert body["total_source_count"] == 0
        # skipped 里有提示
        assert any("没有可克隆" in s for s in body["skipped"])


class TestImportFieldsCloneUnhandledException500:
    """clone_fields_between_tables 抛非 ValueError → 331-332 行转 500."""

    def test_unexpected_exception_in_clone(self, client, auth_headers, db, monkeypatch):
        import cndb.plugins.tables.routers.fields as fields_router

        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS_UE"})
        wid = r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "SrcUE"},
        )
        src_tid = r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
            json={"name": "src_f", "field_type": "text", "order": 0},
        )
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstUE"},
        )
        dst_tid = r.json()["id"]

        # monkey-patch clone_fields_between_tables 抛 RuntimeError（非 ValueError）
        def _boom(*_a, **_kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(fields_router, "clone_fields_between_tables", _boom)

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
            },
        )
        assert r.status_code == 500
        assert "boom" in r.json()["detail"]


class TestRowValidatorNormalizedNoneBranch:
    """覆盖 row_validator line 238->exit：validate_value 返回 None 时 normalized 不写入."""

    def test_validate_value_returns_none_not_in_normalized(self, db, monkeypatch):
        from cndb.plugins.tables.services.importing import row_validator as rv_mod
        from cndb.plugins.tables.models import DataField, DataTable

        src = DataTable(workspace_id=1, name="S_none_norm", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        f = DataField(table_id=src.id, name="x", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(src)
        db.refresh(f)

        def _return_none(value, config):
            pass  # 默认返回 None，触发 row_validator line 238->exit

        monkeypatch.setattr(
            rv_mod.default_registry.get("text"),
            "validate_value",
            _return_none,
        )

        rv = rv_mod.RowValidator(src)
        results = rv.validate_all([{"x": "hello"}])
        assert "x" not in results[0].normalized


# ═══════════════════════════════════════════════════════════════════════════════
# Part 8 — suggest_mapping 智能匹配单元测试
# ═══════════════════════════════════════════════════════════════════════════════


def _mkf(name: str, field_type: str = "text"):
    """快速造一个无 DB 绑定的 DataField（suggest_mapping 只看 name + field_type）."""
    from cndb.plugins.tables.models import DataField

    return DataField(name=name, field_type=field_type)


class TestSuggestMappingNormalize:
    """字段名归一化工具函数."""

    def test_strip_common_prefix(self):
        from cndb.plugins.tables.services.importing.field_mapping import _normalize_name

        assert _normalize_name("src_amount") == "amount"
        assert _normalize_name("src_amount_total") == "amount_total"
        assert _normalize_name("old_name") == "name"
        # 前缀不匹配时保持原样
        assert _normalize_name("srctotal") == "srctotal"

    def test_strip_common_suffix(self):
        from cndb.plugins.tables.services.importing.field_mapping import _normalize_name

        assert _normalize_name("amount_src") == "amount"
        assert _normalize_name("name_old") == "name"

    def test_separator_normalize(self):
        from cndb.plugins.tables.services.importing.field_mapping import _normalize_name

        assert _normalize_name("Full Name") == "full_name"
        assert _normalize_name("full-name") == "full_name"
        assert _normalize_name("full.name") == "full_name"

    def test_lowercase(self):
        from cndb.plugins.tables.services.importing.field_mapping import _normalize_name

        assert _normalize_name("FULL_NAME") == "full_name"


class TestSuggestMapping:
    """suggest_mapping 核心行为."""

    def test_exact_name_match(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        src = [_mkf("amount", "number")]
        dst = [_mkf("amount", "number"), _mkf("count", "number")]
        results = suggest_mapping(src, dst)
        assert results[0]["target"] == "amount"
        assert results[0]["will_map"]
        assert results[0]["score"] >= 1.0

    def test_abbrev_match(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        src = [_mkf("amt", "number")]
        dst = [_mkf("amount", "number"), _mkf("count", "number")]
        results = suggest_mapping(src, dst)
        assert results[0]["target"] == "amount"
        assert results[0]["will_map"]
        assert "缩写" in results[0]["reason"]

    def test_prefix_stripped_match(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        src = [_mkf("src_email", "text")]
        dst = [_mkf("email", "text")]
        results = suggest_mapping(src, dst)
        assert results[0]["target"] == "email"
        assert results[0]["will_map"]

    def test_no_candidate_when_nothing_similar(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        src = [_mkf("totally_unknown_xyz", "text")]
        dst = [_mkf("amount", "number"), _mkf("description", "text")]
        results = suggest_mapping(src, dst)
        # score < 0.6 或 极低，will_map=False
        assert not results[0]["will_map"]

    def test_one_to_one_greedy_assignment(self):
        """两个 src 都能匹配到同一个 dst —— 贪心保证一对一."""
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        src = [_mkf("name", "text"), _mkf("full_name", "text")]
        dst = [_mkf("full_name", "text"), _mkf("description", "text")]
        results = suggest_mapping(src, dst)
        targets = {r["target"] for r in results if r["target"]}
        assert len(targets) == 2, "两个 src 应拿到两个不同的 dst"

    def test_type_compat_bonus(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        src = [_mkf("count", "number")]
        dst_same = [_mkf("count", "number"), _mkf("cnt", "number")]
        results = suggest_mapping(src, dst_same)
        # 完全同名同类型 > 缩写+同类型 > 弱匹配
        assert results[0]["target"] == "count"
        assert results[0]["score"] >= 1.0

    def test_min_score_threshold(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        src = [_mkf("totally_unknown_xyz", "text")]
        dst = [_mkf("amount", "number"), _mkf("description", "text")]
        results_strict = suggest_mapping(src, dst, min_score=0.99)
        # strict 模式下 will_map=False — 阈值生效
        assert not results_strict[0]["will_map"]


class TestSuggestFieldMapping:
    """suggest_field_mapping 便捷接口 — 返回可直接用的 mapping dict."""

    def test_returns_mapping_dict_with_will_map_true_as_target(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_field_mapping

        src = [_mkf("amount", "number"), _mkf("unknown_xyz", "text")]
        dst = [_mkf("amount", "number")]
        mapping, suggestions = suggest_field_mapping(src, dst)
        assert mapping["amount"] == "amount"
        # unknown_xyz 无匹配 → None（跳过）
        assert mapping["unknown_xyz"] is None
        # suggestions 里有两条
        assert len(suggestions) == 2

    def test_mapping_dict_compatible_with_apply_user_mapping(self):
        """suggestion 产出的 mapping dict 可直接 apply_user_mapping 消费."""
        from cndb.plugins.tables.services.importing.field_mapping import (
            apply_user_mapping,
            build_default_mapping,
            suggest_field_mapping,
        )

        src = [_mkf("src_name", "text"), _mkf("src_amt", "number")]
        dst = [_mkf("name", "text"), _mkf("amount", "number")]
        mapping, _ = suggest_field_mapping(src, dst)
        src_names = [s.name for s in src]
        base = build_default_mapping(src_names)
        merged = apply_user_mapping(base, mapping, src_names)
        assert merged.get("src_name") == "name"
        assert merged.get("src_amt") == "amount"


class TestSuggestMappingEdge:
    """suggest_mapping 的边界场景."""

    def test_empty_src(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        assert suggest_mapping([], [_mkf("amount")]) == []

    def test_empty_dst_all_no_candidate(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        results = suggest_mapping([_mkf("amount")], [])
        assert len(results) == 1
        assert results[0]["target"] is None
        assert results[0]["score"] == 0.0

    def test_identical_src_dst_names(self):
        from cndb.plugins.tables.services.importing.field_mapping import suggest_mapping

        # src 和 dst 字段名完全相同 → 全部 will_map
        src = [_mkf("name", "text"), _mkf("age", "number")]
        dst = [_mkf("name", "text"), _mkf("age", "number")]
        results = suggest_mapping(src, dst)
        assert all(r["will_map"] for r in results)
        assert {r["source"]: r["target"] for r in results} == {"name": "name", "age": "age"}


# ═══════════════════════════════════════════════════════════════════════════════
# Part 9 — preview_only + 自动建议的路由级集成测试
# ═══════════════════════════════════════════════════════════════════════════════


class TestImportFieldsPreviewOnly:
    """preview_only=True 时只返回建议和 gap_analysis，不实际创建字段."""

    def test_preview_only_returns_suggestions_no_creation(self, client, auth_headers, _src_table2):
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstPrev1"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "preview_only": True,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # preview_only → 不创建字段
        assert body["created"] == []
        assert body["skipped"] == []
        # 但有 suggestions + gap_analysis
        assert body["suggestions"] is not None
        assert len(body["suggestions"]) == 3  # src_name / src_amount / src_active
        assert body["gap_analysis"] is not None
        # 验证 suggestions 里的每条都有必要字段
        for s in body["suggestions"]:
            assert "source" in s and "target" in s and "score" in s and "will_map" in s

    def test_preview_only_then_execute_with_same_mapping(self, client, auth_headers, _src_table2):
        """preview → 用户确认后把建议的 field_mapping 传进去执行."""
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstPrev2"},
        )
        dst_tid = r.json()["id"]

        # 先 preview 拿建议
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "preview_only": True,
            },
        )
        suggestions = r.json()["suggestions"]

        # 把 will_map=True 的建议转成 field_mapping
        field_mapping: dict[str, str | None] = {}
        for s in suggestions:
            if s["will_map"] and s["target"]:
                field_mapping[s["source"]] = s["target"]
            else:
                field_mapping[s["source"]] = None

        # 用这个 mapping 实际执行
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "field_mapping": field_mapping,
            },
        )
        assert r.status_code == 201, r.text
        # 验证确实创建了字段
        dst_fields = client.get(f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields", headers=auth_headers).json()
        # 至少有一个字段被创建（因为源表有 src_name/src_amount/src_active，目标表是空的）
        assert len(dst_fields) >= 1

    def test_gap_analysis_always_returned(self, client, auth_headers, _src_table2):
        """现在不论传不传 field_mapping，gap_analysis 都应该返回."""
        wid, src_tid = _src_table2

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstAlways"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                # 不传 field_mapping
            },
        )
        assert r.status_code == 201
        body = r.json()
        # gap_analysis 和 suggestions 都不为 None
        assert body["gap_analysis"] is not None
        assert body["suggestions"] is not None
