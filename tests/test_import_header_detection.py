"""表头行自动识别 —— 判定层 / 解析层 / 两个导入入口接口 / 迁移.

需求：导入数据表时自动识别表头所在行，兼容导入表顶部有标题/合并行的情况，
并把识别结果与概率提示给用户（前端据此展示并允许改选）。
"""

from __future__ import annotations

import io
import json

import pytest
from openpyxl import Workbook

from cndb.plugins.tables.services.importing.importer import Importer
from cndb.plugins.tables.services.transfer import (
    HeaderDetection,
    detect_header_row,
    parse_file_to_rows,
    parse_file_to_rows_with_detection,
)
from tests.helpers import wait_import_settled

# ── 测试辅助 ──────────────────────────────────────


def _csv(text: str) -> bytes:
    return text.encode("utf-8")


def _xlsx_bytes(rows: list[list], *, merged_title: str | None = None) -> bytes:
    """构造 xlsx；merged_title 非空时把 A1:C1 合并并写入标题."""
    wb = Workbook()
    ws = wb.active
    if merged_title is not None:
        ws.append([merged_title, None, None])
        ws.merge_cells("A1:C1")
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _make_workspace(client, auth_headers, name: str) -> int:
    resp = client.post("/api/v1/workspaces", json={"name": name}, headers=auth_headers)
    assert resp.status_code in (200, 201), resp.text
    return int(resp.json()["id"])


def _make_table(client, auth_headers, ws_id: int, fields: list[tuple[str, str]]) -> int:
    table = client.post(
        f"/api/v1/workspaces/{ws_id}/tables",
        json={"name": "导入目标表", "description": ""},
        headers=auth_headers,
    ).json()
    for order, (name, ftype) in enumerate(fields, start=1):
        resp = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{table['id']}/fields",
            json={"name": name, "field_type": ftype, "order": order},
            headers=auth_headers,
        )
        assert resp.status_code in (200, 201), resp.text
    return int(table["id"])


# ── 判定层 ────────────────────────────────────────


class TestDetectHeaderRow:
    def test_plain_table_first_row_is_header(self):
        detection = detect_header_row([["产品", "价格", "库存"], ["手机", 2999, 100], ["笔记本", 8999, 50]])
        assert isinstance(detection, HeaderDetection)
        assert detection.row == 1
        assert detection.confidence >= 0.9
        assert detection.requires_review is False
        assert detection.skipped_rows == 0
        assert "第 1 行" in detection.message
        assert detection.candidates[0].row == 1

    def test_merged_title_row_is_skipped(self):
        """顶部 A1:D1 合并标题（值只写在 A1）→ 应识别第 2 行为表头."""
        rows = [
            ["2024 年销售报表", None, None, None],
            ["产品", "价格", "库存", "备注"],
            ["手机", 2999, 100, "a"],
            ["笔记本", 8999, 50, "b"],
        ]
        detection = detect_header_row(rows)
        assert detection is not None
        assert detection.row == 2
        assert detection.confidence >= 0.9
        assert detection.skipped_rows == 1
        assert "已跳过上方 1 行" in detection.message

    def test_multiple_title_rows(self):
        rows = [
            ["公司销售数据", None, None],
            ["2024Q1", None, None],
            ["产品", "价格", "库存"],
            ["手机", 1, 2],
        ]
        detection = detect_header_row(rows)
        assert detection is not None
        assert detection.row == 3
        assert detection.skipped_rows == 2

    def test_all_text_table_stays_confident(self):
        """全文本表格（姓名/部门）没有类型反差，仍应保持较高置信度."""
        detection = detect_header_row([["姓名", "部门"], ["张三", "研发"], ["李四", "市场"]])
        assert detection is not None
        assert detection.row == 1
        assert detection.confidence >= 0.6

    def test_numeric_table_without_header_is_low_confidence(self):
        """纯数值表格没有表头 → 概率应被校准到低值并建议人工确认."""
        detection = detect_header_row([[1, 2, 3], [4, 5, 6], [7, 8, 9]])
        assert detection is not None
        assert detection.requires_review is True
        assert detection.confidence <= 0.5

    def test_single_row_capped_confidence(self):
        detection = detect_header_row([["a", "b"]])
        assert detection is not None
        assert detection.row == 1
        assert detection.confidence <= 0.6
        assert detection.requires_review is True
        assert detection.candidates[0].confidence == detection.confidence

    def test_empty_rows_returns_none(self):
        assert detect_header_row([]) is None

    def test_preferred_index_overrides_best(self):
        detection = detect_header_row([["a", "b"], ["1", "2"], ["3", "4"]], preferred_index=1)
        assert detection is not None
        assert detection.row == 2
        assert any(c.row == 2 for c in detection.candidates)

    def test_preferred_index_out_of_range_raises(self):
        with pytest.raises(ValueError, match="超出可识别范围"):
            detect_header_row([["a", "b"], ["1", "2"]], preferred_index=5)

    def test_candidates_limited_and_sorted(self):
        rows = [[f"c{i}", f"d{i}"] for i in range(10)] + [["a", "b"]]
        detection = detect_header_row(rows)
        assert detection is not None
        assert len(detection.candidates) <= 5
        confidences = [c.confidence for c in detection.candidates]
        assert confidences == sorted(confidences, reverse=True)


# ── 解析层（共用入口） ────────────────────────────


class TestParseWithDetection:
    def test_csv_title_row_skipped(self):
        rows, cols, fmt, detection = parse_file_to_rows_with_detection(
            "2024年销售报表\n产品,价格,库存\n手机,2999,100\n",
            format="csv",
        )
        assert fmt == "csv"
        assert cols == ["产品", "价格", "库存"]
        assert rows == [{"产品": "手机", "价格": "2999", "库存": "100"}]
        assert detection is not None and detection.row == 2

    def test_csv_explicit_header_row(self):
        """用户改选表头行后，按指定行切分（此处把第 2 行数据当表头）."""
        rows, cols, _fmt, detection = parse_file_to_rows_with_detection(
            "产品,价格,库存\n手机,2999,100\n笔记本,8999,50\n",
            format="csv",
            header_row=2,
        )
        assert cols == ["手机", "2999", "100"]
        assert rows == [{"手机": "笔记本", "2999": "8999", "100": "50"}]
        assert detection is not None and detection.row == 2

    def test_csv_header_row_out_of_range(self):
        with pytest.raises(ValueError, match="超出文件非空行数"):
            parse_file_to_rows_with_detection("产品,价格\n手机,1\n", format="csv", header_row=9)

    def test_csv_header_row_invalid(self):
        with pytest.raises(ValueError, match="从 1 开始"):
            parse_file_to_rows_with_detection("产品,价格\n手机,1\n", format="csv", header_row=0)

    def test_csv_header_row_beyond_scan_raises(self):
        with pytest.raises(ValueError, match="前 20 个非空行"):
            parse_file_to_rows_with_detection("产品,价格\n手机,1\n", format="csv", header_row=25)

    def test_xlsx_merged_title_row_skipped(self):
        raw = _xlsx_bytes(
            [["产品", "价格", "库存"], ["手机", 2999, 100], ["笔记本", 8999, 50]],
            merged_title="2024 年销售报表",
        )
        rows, cols, fmt, detection = parse_file_to_rows_with_detection(raw, format="xlsx")
        assert fmt == "xlsx"
        assert cols == ["产品", "价格", "库存"]
        assert len(rows) == 2
        assert detection is not None and detection.row == 2
        assert detection.confidence >= 0.9

    def test_xlsx_explicit_header_row(self):
        raw = _xlsx_bytes([["产品", "价格"], ["手机", 2999], ["笔记本", 8999]])
        rows, cols, _fmt, detection = parse_file_to_rows_with_detection(raw, format="xlsx", header_row=2)
        assert cols == ["手机", "2999"]
        assert len(rows) == 1
        assert detection is not None and detection.row == 2

    def test_json_has_no_header_detection(self):
        rows, cols, _fmt, detection = parse_file_to_rows_with_detection('[{"a": 1}]', format="json")
        assert rows == [{"a": 1}]
        assert cols == ["a"]
        assert detection is None

    def test_legacy_parse_file_to_rows_unchanged(self):
        """旧三返回值入口保持兼容，且默认已启用自动识别."""
        rows, cols, fmt = parse_file_to_rows("标题\n产品,价格\n手机,1\n", format="csv")
        assert fmt == "csv"
        assert cols == ["产品", "价格"]
        assert rows == [{"产品": "手机", "价格": "1"}]

    def test_importer_csv_title_row_skipped(self):
        rows, cols, detection = Importer._parse_csv("2024报表\n产品,价格\n手机,1\n")
        assert cols == ["产品", "价格"]
        assert rows == [{"产品": "手机", "价格": "1"}]
        assert detection is not None and detection.row == 2

    def test_importer_xlsx_merged_title_row_skipped(self):
        raw = _xlsx_bytes([["产品", "价格"], ["手机", 2999]], merged_title="销售报表")
        rows, cols, detection = Importer._parse_xlsx(raw)
        assert cols == ["产品", "价格"]
        assert rows == [{"产品": "手机", "价格": 2999}]
        assert detection is not None and detection.row == 2


# ── 接口层：工作区「导入数据表」（新建表） ──────────


class TestImportFileHeaderRowApi:
    def test_analyze_detects_and_exposes_probability(self, client, auth_headers):
        ws_id = _make_workspace(client, auth_headers, "header-detect-ws")
        raw = _xlsx_bytes(
            [["产品", "价格", "库存"], ["手机", 2999, 100], ["笔记本", 8999, 50]],
            merged_title="2024 年销售报表",
        )
        resp = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("销售.xlsx", raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["header_row"] == 2
        detection = data["header_detection"]
        assert detection["row"] == 2
        assert detection["skipped_rows"] == 1
        assert 0 < detection["confidence"] <= 0.99
        assert detection["candidates"][0]["row"] == 2
        assert "表头" in detection["message"]
        assert [c["name"] for c in data["columns"]] == ["产品", "价格", "库存"]
        # 样本数据从表头下方开始，标题行不会混入数据
        assert data["sample_rows"][0]["产品"] == "手机"

    def test_analyze_respects_explicit_header_row(self, client, auth_headers):
        ws_id = _make_workspace(client, auth_headers, "header-override-ws")
        csv_bytes = _csv("产品,价格\n手机,2999\n笔记本,8999\n")
        resp = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("data.csv", csv_bytes, "text/csv")},
            data={"header_row": "2"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["header_row"] == 2
        assert [c["name"] for c in data["columns"]] == ["手机", "2999"]
        assert data["total_rows"] == 1

    def test_analyze_invalid_header_row_returns_400(self, client, auth_headers):
        ws_id = _make_workspace(client, auth_headers, "header-invalid-ws")
        resp = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("data.csv", _csv("产品,价格\n手机,1\n"), "text/csv")},
            data={"header_row": "0"},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "从 1 开始" in resp.json()["detail"]

    def test_analyze_json_has_null_detection(self, client, auth_headers):
        ws_id = _make_workspace(client, auth_headers, "header-json-ws")
        resp = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file/analyze",
            files={"file": ("data.json", json.dumps([{"a": 1}]).encode(), "application/json")},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["header_detection"] is None
        assert data["header_row"] is None

    def test_create_table_uses_detected_header(self, client, auth_headers):
        ws_id = _make_workspace(client, auth_headers, "header-create-ws")
        raw = _xlsx_bytes(
            [["产品", "价格"], ["手机", 2999], ["笔记本", 8999]],
            merged_title="价格表",
        )
        resp = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            files={"file": ("价格表.xlsx", raw, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
            data={"table_name": "价格表"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["imported_rows"] == 2
        assert data["field_count"] == 2
        assert data["header_row"] == 2
        assert data["header_detection"]["row"] == 2

    def test_create_table_respects_explicit_header_row(self, client, auth_headers):
        ws_id = _make_workspace(client, auth_headers, "header-create-override-ws")
        csv_bytes = _csv("产品,价格\n手机,2999\n笔记本,8999\n")
        resp = client.post(
            f"/api/v1/workspaces/{ws_id}/import-file",
            files={"file": ("data.csv", csv_bytes, "text/csv")},
            data={"table_name": "改选表头", "header_row": "2"},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["imported_rows"] == 1
        assert [c["name"] for c in data["columns"]] == ["手机", "2999"]


# ── 接口层：已有表「导入 / 导出 → 导入」 ───────────


class TestExistingTableHeaderRowApi:
    def _base(self, client, auth_headers) -> tuple[int, int]:
        ws_id = _make_workspace(client, auth_headers, "existing-header-ws")
        table_id = _make_table(client, auth_headers, ws_id, [("产品", "text"), ("价格", "number")])
        return ws_id, table_id

    def _analyze(self, client, auth_headers, ws_id: int, table_id: int, data: dict | None = None):
        base = f"/api/v1/workspaces/{ws_id}/tables/{table_id}"
        resp = client.post(
            f"{base}/import/analyze",
            files={"file": ("销售.csv", _csv("2024年销售报表\n产品,价格\n手机,2999\n"), "text/csv")},
            data=data or {},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        task_id = resp.json()["task_id"]
        detail = wait_import_settled(client, f"{base}/import/async/{task_id}", auth_headers)
        return base, task_id, detail

    def test_analyze_report_exposes_header_detection(self, client, auth_headers):
        ws_id, table_id = self._base(client, auth_headers)
        _base_url, _task_id, detail = self._analyze(client, auth_headers, ws_id, table_id)
        assert detail["status"] == "pending_confirm", detail.get("error_message")
        report = detail["validation_report"]
        assert report["header_row"] == 2
        assert report["header_detection"]["row"] == 2
        assert report["header_detection"]["confidence"] > 0.8
        assert report["valid_count"] == 1

    def test_confirm_imports_rows_below_detected_header(self, client, auth_headers):
        ws_id, table_id = self._base(client, auth_headers)
        base, task_id, detail = self._analyze(client, auth_headers, ws_id, table_id)
        assert detail["status"] == "pending_confirm"
        resp = client.post(f"{base}/import/{task_id}/confirm", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        detail = wait_import_settled(client, f"{base}/import/async/{task_id}", auth_headers)
        assert detail["status"] == "done", detail.get("error_message")
        assert detail["imported_rows"] == 1
        rows = client.post(f"{base}/records/list", json={"limit": 10, "offset": 0}, headers=auth_headers).json()
        assert rows["total"] == 1
        assert rows["items"][0]["产品"] == "手机"

    def test_reanalyze_with_new_header_row(self, client, auth_headers):
        ws_id, table_id = self._base(client, auth_headers)
        base, task_id, detail = self._analyze(client, auth_headers, ws_id, table_id)
        assert detail["validation_report"]["header_row"] == 2

        resp = client.post(
            f"{base}/import/{task_id}/reanalyze",
            params={"header_row": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        detail = wait_import_settled(client, f"{base}/import/async/{task_id}", auth_headers)
        assert detail["status"] == "pending_confirm", detail.get("error_message")
        assert detail["validation_report"]["header_row"] == 1

    def test_reanalyze_rejects_invalid_header_row(self, client, auth_headers):
        ws_id, table_id = self._base(client, auth_headers)
        base, task_id, _detail = self._analyze(client, auth_headers, ws_id, table_id)
        resp = client.post(
            f"{base}/import/{task_id}/reanalyze",
            params={"header_row": 0},
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_confirm_override_header_row(self, client, auth_headers):
        """确认阶段覆盖表头行：execute 按新行解析（此例第 1 行无有效列 → 0 行导入）."""
        ws_id, table_id = self._base(client, auth_headers)
        base, task_id, detail = self._analyze(client, auth_headers, ws_id, table_id)
        assert detail["status"] == "pending_confirm"
        resp = client.post(
            f"{base}/import/{task_id}/confirm",
            params={"header_row": 1},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        detail = wait_import_settled(client, f"{base}/import/async/{task_id}", auth_headers)
        # 表头行 1 只有一列标题：两条数据行仍会各生成一行（产品/价格成为未知列被丢弃），
        # 与默认识别第 2 行时的 1 行导入形成对照，证明覆盖参数确实生效
        assert detail["status"] == "done", detail.get("error_message")
        assert detail["imported_rows"] == 2
