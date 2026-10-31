"""检查动作测试：table/* 与 document/*（ADR 0076 C4 / C5 / D7）."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pytest

from cndb.core.config import settings
from cndb.plugins.files.models import FileOwner
from cndb.plugins.pipeline.services.checks.base import CheckContext, resolve_fields
from cndb.plugins.pipeline.services.checks.document import broken_refs, chart_blocks, links
from cndb.plugins.pipeline.services.checks.table import duplicates, null_rate, stale, value_range
from cndb.plugins.pipeline.services.errors import CheckError
from cndb.plugins.tables.models import DataView
from tests.pipeline_helpers import add_rows, make_document, make_table, make_user, make_workspace


@pytest.fixture
def owner(db):
    return make_user(db, "pipeline_check_owner")


@pytest.fixture
def ws(db, owner):
    return make_workspace(db, owner, "PipelineCheckWS")


@pytest.fixture
def people(db, ws):
    """人员表：文本 / 数值 / 日期 / 日期时间 / 时间戳各一列."""
    return make_table(
        db,
        ws,
        "人员",
        [
            ("姓名", "text"),
            ("城市", "text"),
            ("年龄", "number"),
            ("入职", "date"),
            ("更新", "datetime"),
            ("秒", "timestamp"),
        ],
    )


def _params(**kwargs) -> dict:
    return {key: value for key, value in kwargs.items() if value is not None}


class TestNullRate:
    def test_finding_when_rate_exceeds(self, db, ws, people):
        add_rows(
            db,
            people,
            [
                {"姓名": "张三", "城市": "北京", "年龄": 20},
                {"姓名": "李四", "城市": None, "年龄": 30},
                {"姓名": "王五", "城市": None, "年龄": 40},
            ],
        )
        ctx = CheckContext(db, ws.id)
        findings = list(null_rate.run(ctx, _params(table="人员", fields=["城市"], max_rate=0.5)))
        assert len(findings) == 1
        assert findings[0].locator == {"field_name": "城市"}
        assert findings[0].detail["null_count"] == 2

    def test_no_finding_when_rate_ok(self, db, ws, people):
        add_rows(db, people, [{"姓名": "张三", "城市": "北京", "年龄": 20}])
        ctx = CheckContext(db, ws.id)
        assert list(null_rate.run(ctx, _params(table="人员", fields=["城市"], max_rate=0.05))) == []

    def test_empty_table_no_finding(self, db, ws, people):
        ctx = CheckContext(db, ws.id)
        assert list(null_rate.run(ctx, _params(table="人员", fields=["城市"]))) == []

    def test_unknown_table(self, db, ws):
        ctx = CheckContext(db, ws.id)
        with pytest.raises(CheckError):
            list(null_rate.run(ctx, _params(table="不存在")))


class TestDuplicates:
    def test_duplicate_group(self, db, ws, people):
        add_rows(
            db,
            people,
            [
                {"姓名": "张三", "城市": "北京"},
                {"姓名": "张三", "城市": "上海"},
                {"姓名": "李四", "城市": "广州"},
            ],
        )
        ctx = CheckContext(db, ws.id)
        findings = list(duplicates.run(ctx, _params(table="人员", fields=["姓名"])))
        assert len(findings) == 1
        assert findings[0].detail["group_size"] == 2
        assert len(findings[0].locator["row_ids"]) == 2

    def test_ignore_case_and_whitespace(self, db, ws, people):
        add_rows(db, people, [{"姓名": "abc"}, {"姓名": " ABC "}])
        ctx = CheckContext(db, ws.id)
        findings = list(
            duplicates.run(
                ctx,
                _params(table="人员", fields=["姓名"], ignore_case=True, ignore_whitespace=True),
            )
        )
        assert len(findings) == 1

    def test_scan_truncated_adds_info(self, db, ws, people):
        add_rows(db, people, [{"姓名": "a"}, {"姓名": "b"}, {"姓名": "b"}])
        ctx = CheckContext(db, ws.id, max_scan_rows=2)
        findings = list(duplicates.run(ctx, _params(table="人员", fields=["姓名"])))
        assert any(item.severity == "info" and item.detail.get("truncated") for item in findings)

    def test_scan_rows_paginates(self, db, ws, people):
        add_rows(db, people, [{"姓名": "a"}, {"姓名": "b"}])
        ctx = CheckContext(db, ws.id)
        result = ctx.scan_rows(people, people.active_fields(), batch_size=1)
        assert len(result.rows) == 2
        assert result.truncated is False

    def test_all_fields_default(self, db, ws, people):
        add_rows(db, people, [{"姓名": "a"}, {"姓名": "a"}])
        ctx = CheckContext(db, ws.id)
        assert list(duplicates.run(ctx, _params(table="人员", fields=["all"]))) != []


class TestValueRange:
    def test_numeric_bounds(self, db, ws, people):
        add_rows(db, people, [{"年龄": 10}, {"年龄": 20}, {"年龄": 40}])
        ctx = CheckContext(db, ws.id)
        findings = list(value_range.run(ctx, _params(table="人员", fields=["年龄"], min="18", max="35")))
        assert {item.detail["bound"] for item in findings} == {"min", "max"}
        assert all(item.detail["count"] == 1 for item in findings)

    def test_date_and_datetime_bounds(self, db, ws, people):
        add_rows(
            db,
            people,
            [
                {"入职": date(2010, 1, 1), "更新": datetime(2010, 1, 1)},
                {"入职": date(2024, 1, 1), "更新": datetime(2024, 1, 1)},
            ],
        )
        ctx = CheckContext(db, ws.id)
        date_findings = list(value_range.run(ctx, _params(table="人员", fields=["入职"], min="2020-01-01")))
        datetime_findings = list(
            value_range.run(ctx, _params(table="人员", fields=["更新"], min="2020-01-01T00:00:00Z"))
        )
        assert len(date_findings) == 1
        assert len(datetime_findings) == 1

    def test_timestamp_bounds(self, db, ws, people):
        add_rows(db, people, [{"秒": 0}, {"秒": 1_700_000_000}])
        ctx = CheckContext(db, ws.id)
        assert len(list(value_range.run(ctx, _params(table="人员", fields=["秒"], min="1000")))) == 1
        assert len(list(value_range.run(ctx, _params(table="人员", fields=["秒"], max="2020-01-01T00:00:00Z")))) == 1

    def test_fields_default_filters_types(self, db, ws):
        """``all`` 只保留区间类型字段（文本 / 时间戳等不参与日期阈值解析）."""
        table = make_table(db, ws, "日期表", [("入职", "date"), ("更新", "datetime"), ("备注", "text")])
        add_rows(db, table, [{"入职": date(2000, 1, 1), "更新": datetime(2000, 1, 1)}])
        ctx = CheckContext(db, ws.id)
        findings = list(value_range.run(ctx, _params(table="日期表", min="2001-01-01")))
        assert {item.locator["field_name"] for item in findings} == {"入职", "更新"}

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"fields": ["年龄"]}, "至少需要"),
            ({"fields": ["年龄"], "min": "1", "max": "0"}, "min 大于 max"),
            ({"fields": ["年龄"], "min": ""}, "不能为空"),
            ({"fields": ["年龄"], "min": "abc"}, "不是数值"),
            ({"fields": ["入职"], "min": "not-a-date"}, "不是 ISO 日期"),
            ({"fields": ["更新"], "min": "not-a-datetime"}, "不是 ISO 日期时间"),
            ({"fields": ["秒"], "min": "not-a-time"}, "不是整数秒"),
            ({"fields": ["姓名"], "min": "1"}, "不支持该检查"),
        ],
    )
    def test_invalid_bounds(self, db, ws, people, params: dict, expected: str):
        ctx = CheckContext(db, ws.id)
        with pytest.raises(CheckError) as exc:
            list(value_range.run(ctx, _params(table="人员", **params)))
        assert expected in exc.value.detail


class TestStale:
    def test_date_stale(self, db, ws, people):
        add_rows(db, people, [{"入职": date(2000, 1, 1)}])
        ctx = CheckContext(db, ws.id)
        findings = list(stale.run(ctx, _params(table="人员", field="入职", max_age_days=30)))
        assert len(findings) == 1
        assert findings[0].detail["age_days"] > 30

    def test_fresh_and_future(self, db, ws, people):
        add_rows(db, people, [{"入职": date.today()}])
        ctx = CheckContext(db, ws.id)
        assert list(stale.run(ctx, _params(table="人员", field="入职", max_age_days=30))) == []
        add_rows(db, people, [{"入职": date(2100, 1, 1)}])
        assert list(stale.run(ctx, _params(table="人员", field="入职", max_age_days=0))) == []

    def test_datetime_and_timestamp(self, db, ws, people):
        add_rows(db, people, [{"更新": datetime(2000, 1, 1), "秒": 0}])
        ctx = CheckContext(db, ws.id)
        assert len(list(stale.run(ctx, _params(table="人员", field="更新")))) == 1
        assert len(list(stale.run(ctx, _params(table="人员", field="秒")))) == 1

    def test_empty_and_invalid(self, db, ws, people):
        ctx = CheckContext(db, ws.id)
        assert list(stale.run(ctx, _params(table="人员", field="入职"))) == []
        with pytest.raises(CheckError):
            list(stale.run(ctx, _params(table="人员", field="入职", max_age_days=-1)))
        with pytest.raises(CheckError):
            list(stale.run(ctx, _params(table="人员", field="姓名")))
        with pytest.raises(CheckError):
            list(stale.run(ctx, _params(table="人员", field="不存在")))


class TestResolveFields:
    def test_unknown_or_non_physical_field(self, db, ws, owner):
        table = make_table(db, ws, "含查找", [("名称", "text")])
        from cndb.plugins.tables.models import DataField

        lookup = DataField(table_id=table.id, name="查找", field_type="lookup", order=1)
        lookup.ensure_db_name()
        db.add(lookup)
        db.commit()
        db.refresh(table)
        with pytest.raises(CheckError, match="不存在"):
            resolve_fields(table, ["不存在"])
        with pytest.raises(CheckError, match="无物理列"):
            resolve_fields(table, ["查找"])

    def test_all_returns_physical_fields(self, db, ws, people):
        names = [field.name for field in resolve_fields(people, ["all"])]
        assert "姓名" in names and "年龄" in names

    def test_missing_physical_table(self, db, ws, people):
        from cndb.plugins.tables.services.core import ddl

        ddl.drop_table(db.get_bind(), people.db_table_name)
        ddl.invalidate_reflected_table(people.db_table_name)
        ctx = CheckContext(db, ws.id)
        with pytest.raises(CheckError, match="物理表"):
            ctx.reflect(people)


class TestDocumentBrokenRefs:
    def test_table_and_file_refs(self, db, ws, owner):
        doc = make_document(
            db,
            ws,
            "引用文档",
            "{{table:999999}}\n\n![x](file:missing.png)",
            user=owner,
        )
        ctx = CheckContext(db, ws.id)
        findings = list(broken_refs.run(ctx, {"scopes": ["table", "file"]}))
        assert {item.locator["scope"] for item in findings} == {"table", "file"}
        assert findings[0].target_id == doc.id

    def test_valid_table_and_view_refs(self, db, ws, owner):
        table = make_table(db, ws, "引用表", [("名称", "text")])
        view = DataView(table_id=table.id, name="默认", owner_id=owner.id)
        db.add(view)
        db.commit()
        db.refresh(view)
        make_document(db, ws, "引用文档", "{{table:" + str(table.id) + "|view=" + str(view.id) + "}}", user=owner)
        ctx = CheckContext(db, ws.id)
        assert list(broken_refs.run(ctx, {"scopes": ["table"]})) == []

        make_document(db, ws, "坏视图", "{{table:" + str(table.id) + "|view=999999}}", user=owner)
        assert len(list(broken_refs.run(ctx, {"scopes": ["table"]}))) == 1

    def test_file_owner_and_real_file(self, db, ws, owner):
        db.add(FileOwner(file_key="owned.png", workspace_id=ws.id))
        upload_dir = Path(settings.UPLOAD_DIR) / str(ws.id)
        upload_dir.mkdir(parents=True, exist_ok=True)
        (upload_dir / "on-disk.png").write_bytes(b"x")
        db.commit()
        make_document(
            db,
            ws,
            "附件",
            "![a](file:owned.png)\n\n![b](file:on-disk.png)",
            user=owner,
        )
        ctx = CheckContext(db, ws.id)
        assert list(broken_refs.run(ctx, {"scopes": ["file"]})) == []

    def test_chart_scope_and_unknown_scope(self, db, ws, owner):
        make_document(
            db,
            ws,
            "坏图表",
            '```chart\n{"version": 1, "template": "nope", "config": {}}\n```',
            user=owner,
        )
        ctx = CheckContext(db, ws.id)
        findings = list(broken_refs.run(ctx, {"scopes": ["chart"]}))
        assert len(findings) == 1
        assert "图表模板引用失效" in findings[0].message
        assert findings[0].locator["block_index"] == 0
        assert findings[0].locator["template"] == ""
        with pytest.raises(CheckError, match="不支持的范围"):
            list(broken_refs.run(ctx, {"scopes": ["unknown"]}))


class TestDocumentChartBlocks:
    def test_valid_block(self, db, ws, owner):
        make_document(
            db,
            ws,
            "正常图表",
            '```chart\n{"version": 1, "template": "stacked-bar-horizontal", "config": {}}\n```',
            user=owner,
        )
        ctx = CheckContext(db, ws.id)
        assert list(chart_blocks.run(ctx, {})) == []

    def test_block_count_and_size_and_error(self, db, ws, owner):
        block = '```chart\n{"version": 1, "template": "stacked-bar-horizontal", "config": {}}\n```'
        make_document(db, ws, "多块", f"{block}\n\n{block}", user=owner)
        make_document(db, ws, "坏块", "```chart\nnot-json\n```", user=owner)
        ctx = CheckContext(db, ws.id)
        findings = list(chart_blocks.run(ctx, {"max_blocks": 1, "max_block_bytes": 10}))
        locators = [item.locator for item in findings]
        assert any(loc.get("error") == "json_invalid" for loc in locators)
        assert any(item.detail.get("limit") == 10 and "size" in item.detail for item in findings)
        assert any(item.detail.get("count") == 2 for item in findings)

    def test_ignores_archived_and_folder(self, db, ws, owner):
        block = "```chart\nnot-json\n```"
        make_document(db, ws, "归档", block, user=owner, status="archived")
        make_document(db, ws, "文件夹", block, user=owner, is_folder=True)
        ctx = CheckContext(db, ws.id)
        assert list(chart_blocks.run(ctx, {})) == []


class TestDocumentLinks:
    def test_broken_link(self, db, ws, owner):
        make_document(db, ws, "源文档", "[[不存在的文档]]", user=owner)
        ctx = CheckContext(db, ws.id)
        findings = list(links.run(ctx, {}))
        assert len(findings) == 1
        assert findings[0].locator["target"] == "不存在的文档"

    def test_valid_link_and_code_fence(self, db, ws, owner):
        make_document(db, ws, "目标文档", "正文", user=owner)
        make_document(db, ws, "源文档", "[[目标文档#节]]\n\n```\n[[不存在的文档]]\n```", user=owner)
        ctx = CheckContext(db, ws.id)
        assert list(links.run(ctx, {})) == []
