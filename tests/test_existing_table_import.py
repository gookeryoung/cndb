"""「已有数据表更新」失败修复的回归测试.

线上故障：**新建表导入可以，已有数据表更新不行**。

根因（已复现）：`add_text_field` 策略自动新增列时，类型推断对**非标量值**做了 `str(...)`：
WPS 单元格图片（DISPIMG）解析出的图片元数据是 list，被推断成 `text`；
而实际值仍是 list → 写入时 SQLite 直接抛
``Error binding parameter N: type 'list' is not supported``。
新建表时列与文件同源、类型一致，所以"新表可以"；已有表缺列才会走这条自动新增分支。

修复：
1. 自动新增列识别非标量样本 —— 图片元数据 → ``image``，其它 list/dict → ``json``；
2. ``DiffReporter.infer_new_column_type`` 的允许集合补上 image/attachment/json；
3. 标量字段类型（base）遇到 list/dict 时序列化为 JSON 字符串兜底，
   即使目标列已存在且是 text 也不会把整次导入打崩。
"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.tables.services.importing.diff_reporter import DiffReporter
from cndb.plugins.tables.services.importing.importer import (
    _infer_column_type_with_non_scalar,
    _looks_like_image_metadata,
)

IMAGE_META = [
    {
        "file_key": "abc.png",
        "filename": "image1.png",
        "size": 33094,
        "mime_type": "image/png",
        "created_at": "2026-10-15T15:54:38+00:00",
    }
]


class TestNonScalarColumnTypeInference:
    def test_image_metadata_detected(self):
        assert _looks_like_image_metadata(IMAGE_META)
        assert _looks_like_image_metadata(IMAGE_META[0])
        assert not _looks_like_image_metadata("普通文本")
        assert not _looks_like_image_metadata([1, 2, 3])

    def test_image_metadata_maps_to_image_field(self):
        # text 推断结果被非标量样本修正为 image（该类型不占物理列，值存关联表）
        assert _infer_column_type_with_non_scalar("text", IMAGE_META) == "image"

    def test_other_non_scalar_maps_to_json_field(self):
        assert _infer_column_type_with_non_scalar("text", [["a", "b"]]) == "json"
        assert _infer_column_type_with_non_scalar("text", [{"k": "v"}]) == "json"

    def test_scalar_columns_keep_inferred_type(self):
        assert _infer_column_type_with_non_scalar("text", []) == "text"
        assert _infer_column_type_with_non_scalar("number", []) == "number"
        assert _infer_column_type_with_non_scalar("select", []) == "select"

    def test_diff_reporter_allows_image_and_attachment(self):
        """允许集合里必须包含 image/attachment，否则会被强制降级为 text."""
        assert DiffReporter.infer_new_column_type(["普通文本"])[0] == "text"


class TestScalarFallbackSerialization:
    """标量列收到 list/dict：序列化为 JSON 字符串，而不是让 SQLite 绑参崩掉."""

    def test_text_field_serializes_list(self):
        from cndb.plugins.tables.field_types import default_registry

        text_field = default_registry.get("text")
        assert text_field is not None
        out = text_field.validate_value(IMAGE_META, {})
        assert isinstance(out, str)
        assert json.loads(out)[0]["file_key"] == "abc.png"

    def test_longtext_field_serializes_dict(self):
        from cndb.plugins.tables.field_types import default_registry

        longtext = default_registry.get("longtext")
        assert longtext is not None
        out = longtext.validate_value({"a": [1, 2]}, {})
        assert isinstance(out, str)
        assert json.loads(out) == {"a": [1, 2]}

    def test_none_still_none(self):
        from cndb.plugins.tables.field_types import default_registry

        assert default_registry.get("text").validate_value(None, {}) is None


class TestExistingTableImportWithNonScalarColumn:
    """端到端：已有表缺列 + add_text_field + 非标量值 → 导入必须成功（修复前绑参报错）."""

    def _make_table(self, client, auth_headers, fields: list[tuple[str, str]]) -> tuple[int, int]:
        ws = client.post("/api/v1/workspaces", json={"name": "existing-ws"}, headers=auth_headers).json()
        table = client.post(
            f"/api/v1/workspaces/{ws['id']}/tables",
            json={"name": "已有表", "description": ""},
            headers=auth_headers,
        ).json()
        order = 1
        for name, ftype in fields:
            resp = client.post(
                f"/api/v1/workspaces/{ws['id']}/tables/{table['id']}/fields",
                json={"name": name, "field_type": ftype, "order": order},
                headers=auth_headers,
            )
            assert resp.status_code in (200, 201), resp.text
            order += 1
        return int(ws["id"]), int(table["id"])

    def test_json_list_value_into_missing_column(self, client, auth_headers):
        """文件里有 list 值、表里没这列 → 自动新增为 json 字段并成功落库."""
        ws_id, table_id = self._make_table(client, auth_headers, [("序号", "number")])

        payload = [{"序号": 1, "标签": ["a", "b"]}, {"序号": 2, "标签": ["c"]}]
        base = f"/api/v1/workspaces/{ws_id}/tables/{table_id}"
        task = client.post(
            f"{base}/import/analyze",
            files={"file": ("data.json", json.dumps(payload).encode(), "application/json")},
            data={"unknown_cols_strategy": "add_text_field", "match_keys": json.dumps(["序号"])},
            headers=auth_headers,
        ).json()
        task_id = task["task_id"]

        detail = client.get(f"{base}/import/async/{task_id}", headers=auth_headers).json()
        assert detail["status"] == "pending_confirm", detail
        report = detail["validation_report"]
        planned = {c["name"]: c["field_type"] for c in report.get("planned_columns", [])}
        assert planned.get("标签") == "json", planned

        resp = client.post(f"{base}/import/{task_id}/confirm", headers=auth_headers)
        assert resp.status_code == 200, resp.text

        detail = client.get(f"{base}/import/async/{task_id}", headers=auth_headers).json()
        assert detail["status"] == "done", detail.get("error_message")
        assert "type 'list' is not supported" not in json.dumps(detail)

        rows = client.post(f"{base}/records/list", json={"limit": 10, "offset": 0}, headers=auth_headers).json()
        assert rows["total"] == 2
        stored = rows["items"][0]["标签"]
        assert json.loads(stored) == ["a", "b"]


class TestTextColumnReceivingImageMetadata:
    """目标列已存在且是 text：图片元数据被序列化，不中断导入（兜底路径）."""

    def test_text_column_gets_json_string(self, client, auth_headers, db):
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.core import records as rec

        ws = client.post("/api/v1/workspaces", json={"name": "text-col-ws"}, headers=auth_headers).json()
        table = client.post(
            f"/api/v1/workspaces/{ws['id']}/tables",
            json={"name": "text列表", "description": ""},
            headers=auth_headers,
        ).json()
        client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{table['id']}/fields",
            json={"name": "图1", "field_type": "text", "order": 1},
            headers=auth_headers,
        )

        dt = db.get(DataTable, table["id"])
        assert dt is not None
        ids = rec.bulk_create(db.get_bind(), dt, [{"图1": IMAGE_META}], db=db)
        assert ids, "text 列收到 list 应被序列化后成功写入"

        rows = client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{table['id']}/records/list",
            json={"limit": 10, "offset": 0},
            headers=auth_headers,
        ).json()
        assert json.loads(rows["items"][0]["图1"])[0]["file_key"] == "abc.png"


@pytest.mark.parametrize(
    ("value", "expected_type"),
    [
        (IMAGE_META, "image"),
        ([{"普通": "对象"}], "json"),
        (["纯字符串"], "json"),
    ],
)
def test_inference_matrix(value, expected_type):
    assert _infer_column_type_with_non_scalar("text", [value]) == expected_type
