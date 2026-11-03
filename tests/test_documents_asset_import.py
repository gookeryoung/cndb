"""原件族导入测试（ADR 0025）：PDF / Office / 图片原样存档 + 原件端点 + 只读守卫.

判定层（格式注册表 / 分派）与接口层（导入 / 预览 / 覆盖 / 权限 / 下载 / 彻底删除）分开写，
与 ADR 0025 §7 的测试清单一一对应。
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import quopri
import re
import struct
import zipfile
import zlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from cndb.core.config import settings
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.services.importers import formats, reader
from cndb.plugins.documents.services.importers.errors import UnsupportedImport
from cndb.plugins.documents.services.preview import office as office_preview
from cndb.plugins.files.models import FileOwner
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
ANALYZE = DOCS + "/import/files/analyze"
IMPORT = DOCS + "/import/files"

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n%%EOF\n"
XLSX_BYTES = b"PK\x03\x04fake-xlsx-payload"
PPTX_BYTES = b"PK\x03\x04fake-pptx-payload"


def _png_bytes() -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        head = struct.pack(">I", len(payload)) + kind + payload
        return head + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
        + chunk(b"IEND", b"")
    )


PNG_BYTES = _png_bytes()


def _xlsx_bytes() -> bytes:
    """构造真实 xlsx：两个工作表（含日期 / 数值 / 空表）+ 一个会转义的单元格."""
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "销售明细"
    sheet.append(["月份", "金额", "日期", "备注"])
    sheet.append(["一月", 1200.5, dt.date(2026, 1, 31), "<script>alert(1)</script>"])
    sheet.append([])
    sheet.append(["二月", 99, None, None])
    workbook.create_sheet("备注空表")
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _docx_bytes(*, with_image: bool = True) -> bytes:
    """构造真实 docx：标题 / 段落 / 列表 / 表格 / 可选内嵌图片."""
    from docx import Document as DocxDocument

    document = DocxDocument()
    document.add_heading("项目说明", level=1)
    document.add_paragraph("正文段落")
    document.add_paragraph("第一条", style="List Bullet")
    document.add_paragraph("第二条", style="List Bullet")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "字段"
    table.cell(0, 1).text = "取值"
    table.cell(1, 0).text = "版本"
    table.cell(1, 1).text = "v1"
    if with_image:
        document.add_picture(io.BytesIO(PNG_BYTES))
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


XLSX_REAL_BYTES = _xlsx_bytes()
DOCX_REAL_BYTES = _docx_bytes()


def _login(client, username: str, password: str = "passw0rd") -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "asset_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    workspace = Workspace(name="原件库", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def auth(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


def _files(*entries: tuple[str, bytes, str]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (name, data, ctype)) for name, data, ctype in entries]


def _tree(client, ws_id: int, auth) -> list[dict]:
    r = client.get(DOCS.format(ws=ws_id) + "/tree", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _flat(nodes: list[dict], out: list[dict] | None = None) -> list[dict]:
    out = [] if out is None else out
    for node in nodes:
        out.append(node)
        _flat(node.get("children") or [], out)
    return out


def _import_one(client, ws_id: int, auth, name: str, data: bytes, ctype: str, **form) -> dict:
    r = client.post(
        IMPORT.format(ws=ws_id),
        files=_files((name, data, ctype)),
        data={"paths": name, **form},
        headers=auth,
    )
    assert r.status_code == 200, r.text
    return r.json()


def _doc(client, ws_id: int, auth) -> dict:
    nodes = [node for node in _flat(_tree(client, ws_id, auth)) if not node["is_folder"]]
    assert len(nodes) == 1, nodes
    return nodes[0]


# ── 判定层：格式注册表 / 分派 ──


class TestFormats:
    def test_registry_covers_required_formats(self):
        assert formats.asset_format("a.pdf").content_type == "pdf"  # type: ignore[union-attr]
        assert formats.asset_format("A.PDF").mime == "application/pdf"  # type: ignore[union-attr]
        assert formats.asset_format("a.PNG").content_type == "image"  # type: ignore[union-attr]
        assert formats.asset_format("a.jpg").mime == "image/jpeg"  # type: ignore[union-attr]
        assert formats.asset_format("a.svg").mime == "image/svg+xml"  # type: ignore[union-attr]
        assert formats.asset_format("a.xlsx").content_type == "xlsx"  # type: ignore[union-attr]
        assert formats.asset_format("a.ppt").content_type == "pptx"  # type: ignore[union-attr]

    def test_registry_rejects_unknown(self):
        assert formats.asset_format("a.txt") is None
        assert formats.asset_format("a") is None
        assert not formats.is_supported("a.zip")
        assert formats.is_convertible("a.docx")
        assert not formats.is_convertible("a.pdf")

    def test_convertible_formats_stay_markdown(self):
        doc = reader.convert_file(reader.UploadedItem("a.md", b"# T\n\nbody\n"))
        assert doc.asset is False
        assert doc.content_type == "markdown"

    def test_asset_dispatch(self):
        doc = reader.convert_file(reader.UploadedItem("dir/报告.pdf", PDF_BYTES))
        assert doc.asset is True
        assert doc.body == ""
        assert doc.title == "报告"
        assert doc.content_type == "pdf"
        assert doc.mime == "application/pdf"

    def test_asset_oversize_rejected(self, monkeypatch):
        monkeypatch.setattr(formats, "MAX_ASSET_BYTES", 2)
        monkeypatch.setattr(reader, "MAX_ASSET_BYTES", 2)
        with pytest.raises(UnsupportedImport):
            reader.convert_file(reader.UploadedItem("a.pdf", PDF_BYTES))

    def test_empty_asset_rejected(self):
        with pytest.raises(UnsupportedImport):
            reader.convert_file(reader.UploadedItem("a.png", b""))


class TestDocxMode:
    """Word 处理模式（ADR 0087）：默认转换，archive 原样存档."""

    def test_convert_is_default(self):
        doc = reader.convert_file(reader.UploadedItem("a.docx", DOCX_REAL_BYTES))
        assert doc.asset is False
        assert doc.content_type == "markdown"
        assert doc.title == "项目说明"
        assert "正文段落" in doc.body

    def test_archive_stores_original(self):
        doc = reader.convert_file(reader.UploadedItem("a.docx", DOCX_REAL_BYTES), docx_mode="archive")
        assert doc.asset is True
        assert doc.body == ""
        assert doc.content_type == "word"
        assert doc.mime.endswith("wordprocessingml.document")
        assert doc.title == "a"

    def test_unknown_mode_rejected(self):
        with pytest.raises(UnsupportedImport):
            reader.convert_file(reader.UploadedItem("a.docx", DOCX_REAL_BYTES), docx_mode="explode")


class TestOfficePreviewRender:
    """原件预览渲染（ADR 0087 C1/C2/C3/C4）."""

    def test_spreadsheet_html_has_sheets_rows_and_escaped_text(self):
        html = office_preview.build_spreadsheet_html(XLSX_REAL_BYTES)
        assert '<table class="sheet">' in html
        assert "销售明细" in html
        assert "备注空表" in html
        assert "<td>月份</td>" in html
        assert "1200.5" in html
        assert "2026-01-31" in html
        # 来源文本一律转义：单元格里的脚本不能出现在标签里
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html

    def test_spreadsheet_shows_row_and_column_numbers(self):
        """行列号（需求 0090）：列 A/B/C…，行号取原件真实行号（空行跳过导致不连续）."""
        html = office_preview.build_spreadsheet_html(XLSX_REAL_BYTES)
        # 列号：首个工作表 4 列 → A..D，且含左上角占位单元格
        for letter in ("A", "B", "C", "D"):
            assert f'<th scope="col">{letter}</th>' in html
        assert 'class="cn-sheet-corner"' in html
        # 行号：第 1 行表头、第 2 行数据、第 3 行为空被跳过、第 4 行数据
        assert 'class="cn-sheet-rownum" scope="row">1</th>' in html
        assert 'class="cn-sheet-rownum" scope="row">2</th>' in html
        assert 'class="cn-sheet-rownum" scope="row">3</th>' not in html
        assert 'class="cn-sheet-rownum" scope="row">4</th>' in html
        # 表头吸附在顶部、行号列吸附在左侧（横向滚动也不丢行号）
        assert "thead th { position: sticky; top: 0;" in html
        assert "tbody th.cn-sheet-rownum { position: sticky; left: 0;" in html

    def test_column_letters(self):
        assert [office_preview._column_letters(i) for i in (1, 26, 27, 52, 53)] == [
            "A",
            "Z",
            "AA",
            "AZ",
            "BA",
        ]

    def test_spreadsheet_page_fills_iframe_height(self):
        """布局（需求 0091）：整页铺满 iframe 高度，滚动只发生在面板内，底部不留大空白."""
        html = office_preview.build_spreadsheet_html(XLSX_REAL_BYTES)
        assert '<body class="cn-preview-sheet-page">' in html
        assert "html, body { height: 100%; }" in html
        assert "body.cn-preview-sheet-page { display: flex; flex-direction: column;" in html
        # 标签条固定、面板撑满剩余高度并各自滚动
        assert ".cn-sheet-tabs { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }" in html
        assert ".cn-sheet-panels { display: flex; flex-direction: column; flex: 1 1 auto; min-height: 0; }" in html
        assert ".cn-sheet-panel { flex: 1 1 auto; min-height: 0; overflow: auto; }" in html
        # 旧的 70vh 高度上限会留下底部空白，已移除
        assert "max-height: 70vh" not in html

    def test_spreadsheet_sheets_are_paginated(self):
        """多工作表按标签页分页（需求 0089）：一次只显示一个表，纯 CSS 切换."""
        html = office_preview.build_spreadsheet_html(XLSX_REAL_BYTES)
        # 每个工作表一枚 radio + 一个面板；只有第一个默认选中
        assert html.count('class="cn-sheet-radio"') == 2
        assert 'id="cn-sheet-0" checked' in html
        assert 'id="cn-sheet-1" checked' not in html
        assert 'role="tablist"' in html
        assert html.count(":checked ~ .cn-sheet-panels .cn-sheet-panel-") == 2
        assert "#cn-sheet-1:checked ~ .cn-sheet-panels .cn-sheet-panel-1 { display: block; }" in html
        assert ".cn-sheet-panel { display: none; }" in html
        assert "#cn-sheet-1:checked ~ .cn-sheet-tabbar .cn-sheet-tab-1" in html

    def test_spreadsheet_panel_visibility_only_by_checked(self):
        """回归（Excel 切页后前一页仍显示）：面板可见性只能由 :checked 决定.

        曾用 `.cn-sheet-panel.is-active { display: block }` 给首屏兜底，导致切到第二页时
        第一个面板仍然常驻显示（两页叠在一起）。这里锁死：不存在任何常驻显示规则。
        """
        html = office_preview.build_spreadsheet_html(XLSX_REAL_BYTES)
        assert "is-active" not in html
        assert ".cn-sheet-panel.is-active" not in html
        # 允许面板显示的三条规则：两条 :checked（多表切换）+ 一条 is-single（单表铺满高度）
        panel_rules = [rule for rule in html.split("}") if "cn-sheet-panel" in rule and "display: block" in rule]
        assert len(panel_rules) == 3
        assert all(":checked" in rule or "is-single" in rule for rule in panel_rules)
        # 多表结构里绝不能出现 is-single 容器（否则面板会常驻显示）
        assert 'class="cn-sheet-panels is-single"' not in html

    def test_spreadsheet_single_sheet_has_no_tabbar(self):
        """单工作表不渲染标签条（避免无意义的分页 chrome）."""
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "唯一"
        sheet.append(["列", "值"])
        sheet.append(["a", 1])
        buffer = io.BytesIO()
        workbook.save(buffer)

        html = office_preview.build_spreadsheet_html(buffer.getvalue())
        assert '<table class="sheet">' in html
        # 样式表里始终有分页类定义，这里断言的是「不渲染分页结构」，但仍有铺满高度的面板
        assert '<div class="cn-sheet-tabs">' not in html
        assert 'class="cn-sheet-radio"' not in html
        assert 'role="tablist"' not in html
        assert '<div class="cn-sheet-panels is-single">' in html

    def test_spreadsheet_empty_sheet(self):
        # 全空工作表在分页面板内给空态提示，不产出空 <table>
        html = office_preview.build_spreadsheet_html(XLSX_REAL_BYTES)
        assert "（空白工作表）" in html
        assert '<table class="sheet"></table>' not in html
        assert 'cn-sheet-panel-1" data-sheet="1"><p class="cn-preview-empty">（空白工作表）</p>' in html

    def test_spreadsheet_truncated_note(self, monkeypatch):
        monkeypatch.setattr(office_preview, "MAX_TOTAL_CELLS", 2)
        html = office_preview.build_spreadsheet_html(XLSX_REAL_BYTES)
        assert "已截断" in html

    def test_spreadsheet_broken_bytes(self):
        with pytest.raises(office_preview.UnsupportedPreview):
            office_preview.build_spreadsheet_html(b"not-a-zip")

    def test_document_html_structure(self):
        html = office_preview.build_document_html(DOCX_REAL_BYTES)
        assert "<h1>项目说明</h1>" in html
        assert "<p>正文段落</p>" in html
        assert "<ul><li>第一条</li><li>第二条</li></ul>" in html
        assert '<table class="docx">' in html and "<th>字段</th>" in html
        assert "data:image/png;base64," in html

    def test_document_without_image_has_no_data_uri(self):
        html = office_preview.build_document_html(_docx_bytes(with_image=False))
        assert "data:image/png;base64," not in html

    def test_document_empty(self):
        from docx import Document as DocxDocument

        buffer = io.BytesIO()
        DocxDocument().save(buffer)
        html = office_preview.build_document_html(buffer.getvalue())
        assert "没有可见正文" in html

    def test_document_broken_bytes(self):
        with pytest.raises(office_preview.UnsupportedPreview):
            office_preview.build_document_html(b"not-a-zip")

    def test_legacy_binary_formats_rejected(self):
        for mime in ("application/vnd.ms-excel", "application/msword"):
            with pytest.raises(office_preview.UnsupportedPreview):
                office_preview.build_office_preview("xlsx", mime, XLSX_REAL_BYTES)

    def test_unknown_content_type_rejected(self):
        with pytest.raises(office_preview.UnsupportedPreview):
            office_preview.build_office_preview("pdf", "application/pdf", PDF_BYTES)


# ── 接口层 ──


class TestAnalyzeAssets:
    def test_preview_marks_asset_and_writes_nothing(self, client, ws, auth):
        r = client.post(
            ANALYZE.format(ws=ws.id),
            files=_files(
                ("报告.pdf", PDF_BYTES, "application/pdf"),
                ("封面.png", PNG_BYTES, "image/png"),
            ),
            data={"paths": ["报告.pdf", "封面.png"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["assets"] == 2
        assert data["total_documents"] == 2
        items = {item["title"]: item for item in data["items"]}
        assert items["报告"]["is_asset"] is True
        assert items["报告"]["format"] == "pdf"
        assert items["封面"]["format"] == "image"
        assert _tree(client, ws.id, auth) == []


class TestImportAssets:
    def test_import_docx_archive_and_read_back(self, client, ws, auth):
        stats = _import_one(
            client,
            ws.id,
            auth,
            "说明书.docx",
            DOCX_REAL_BYTES,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            docx_mode="archive",
        )
        assert stats["assets"] == 1
        doc = _doc(client, ws.id, auth)
        assert doc["content_type"] == "word"
        assert doc["asset_mime"].endswith("wordprocessingml.document")
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 200
        assert r.content == DOCX_REAL_BYTES

    def test_import_docx_convert_keeps_markdown(self, client, ws, auth):
        _import_one(
            client,
            ws.id,
            auth,
            "说明书.docx",
            DOCX_REAL_BYTES,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        doc = _doc(client, ws.id, auth)
        assert doc["content_type"] == "markdown"

    def test_invalid_docx_mode_rejected(self, client, ws, auth):
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("说明书.docx", DOCX_REAL_BYTES, "application/octet-stream")),
            data={"paths": "说明书.docx", "docx_mode": "explode"},
            headers=auth,
        )
        assert r.status_code == 400
        r = client.post(
            ANALYZE.format(ws=ws.id),
            files=_files(("说明书.docx", DOCX_REAL_BYTES, "application/octet-stream")),
            data={"paths": "说明书.docx", "docx_mode": "explode"},
            headers=auth,
        )
        assert r.status_code == 400

    def test_import_pdf_and_read_back(self, client, ws, auth):
        stats = _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        assert stats["created"] == 1
        assert stats["assets"] == 1
        doc = _doc(client, ws.id, auth)
        assert doc["content_type"] == "pdf"
        assert doc["asset_mime"] == "application/pdf"
        assert doc["content_size"] == len(PDF_BYTES)

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 200, r.text
        assert r.content == PDF_BYTES
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.headers["content-disposition"].startswith("inline")

    def test_import_image_and_office(self, client, ws, auth):
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(
                ("封面.png", PNG_BYTES, "image/png"),
                ("数据.xlsx", XLSX_BYTES, "application/vnd.ms-excel"),
                ("胶片.pptx", PPTX_BYTES, "application/vnd.ms-powerpoint"),
            ),
            data={"paths": ["封面.png", "数据.xlsx", "胶片.pptx"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        stats = r.json()
        assert stats["created"] == 3
        assert stats["assets"] == 3
        assert stats["attachments"] == 0
        types = {node["title"]: node["content_type"] for node in _flat(_tree(client, ws.id, auth))}
        assert types == {"封面": "image", "数据": "xlsx", "胶片": "pptx"}

    def test_binds_file_owner_to_document(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        owners = db.execute(select(FileOwner).where(FileOwner.workspace_id == ws.id)).scalars().all()
        assert len(owners) == 1
        assert owners[0].document_id == doc["id"]

    def test_folder_mode_keeps_asset_in_folder(self, client, ws, auth):
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("资料/报告.pdf", PDF_BYTES, "application/pdf")),
            data={"paths": ["资料/报告.pdf"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        nodes = _flat(_tree(client, ws.id, auth))
        folder = next(node for node in nodes if node["is_folder"])
        doc = next(node for node in nodes if not node["is_folder"])
        assert doc["parent_id"] == folder["id"]

    def test_overwrite_replaces_asset_and_drops_old_file(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        old_keys = [path.name for path in (Path(settings.UPLOAD_DIR) / str(ws.id)).iterdir()]
        assert len(old_keys) == 1

        new_bytes = PDF_BYTES + b"REV2\n"
        stats = _import_one(client, ws.id, auth, "报告.pdf", new_bytes, "application/pdf", conflict="overwrite")
        assert stats["updated"] == 1
        assert stats["created"] == 0

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.content == new_bytes
        remaining = [path.name for path in (Path(settings.UPLOAD_DIR) / str(ws.id)).iterdir()]
        assert len(remaining) == 1
        assert remaining != old_keys

    def test_skip_keeps_first_asset(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        stats = _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES + b"X", "application/pdf", conflict="skip")
        assert stats["skipped"] == 1
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.content == PDF_BYTES

    def test_asset_does_not_replace_markdown_document(self, client, ws, auth):
        """同名 Markdown 文档不被只读原件覆盖（改名保留两份）."""
        client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("报告.md", b"# x\n\nbody\n", "text/markdown")),
            data={"paths": "报告.md"},
            headers=auth,
        )
        stats = _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf", conflict="overwrite")
        assert stats["created"] == 1
        assert stats["updated"] == 0
        kinds = {node["title"]: node["content_type"] for node in _flat(_tree(client, ws.id, auth))}
        assert kinds == {"x": "markdown", "报告": "pdf"}

    def test_oversize_asset_only_skips_itself(self, client, ws, auth, monkeypatch):
        monkeypatch.setattr(reader, "MAX_ASSET_BYTES", 4)
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(
                ("ok.md", b"# ok\n\nbody\n", "text/markdown"),
                ("big.pdf", PDF_BYTES, "application/pdf"),
            ),
            data={"paths": ["ok.md", "big.pdf"]},
            headers=auth,
        )
        assert r.status_code == 200, r.text
        stats = r.json()
        assert stats["created"] == 1
        assert stats["skipped"] == 1
        assert stats["skipped_files"][0]["path"] == "big.pdf"

    def test_viewer_cannot_import_asset(self, client, db, ws):
        viewer = _make_user(db, "asset_viewer")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("报告.pdf", PDF_BYTES, "application/pdf")),
            data={"paths": "报告.pdf"},
            headers=_login(client, viewer.username),
        )
        assert r.status_code == 403

    def test_non_member_cannot_import_asset(self, client, db, ws):
        outsider = _make_user(db, "asset_outsider")
        r = client.post(
            IMPORT.format(ws=ws.id),
            files=_files(("报告.pdf", PDF_BYTES, "application/pdf")),
            data={"paths": "报告.pdf"},
            headers=_login(client, outsider.username),
        )
        assert r.status_code == 403


class TestAssetEndpoint:
    def test_markdown_document_has_no_asset(self, client, ws, auth):
        client.post(DOCS.format(ws=ws.id), json={"title": "普通文档", "content": "正文"}, headers=auth)
        doc = _doc(client, ws.id, auth)
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 404

    def test_download_disposition(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset?download=true", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-disposition"].startswith("attachment")

    def test_svg_gets_sandbox_header(self, client, ws, auth):
        _import_one(client, ws.id, auth, "图标.svg", b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml")
        doc = _doc(client, ws.id, auth)
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 200
        assert r.headers["content-security-policy"] == "sandbox"
        assert r.headers["x-content-type-options"] == "nosniff"

    def test_unpublished_asset_hidden_from_other_member(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        member = _make_user(db, "asset_member")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=member.id, role=WorkspaceRole.EDITOR))
        db.commit()
        member_auth = _login(client, member.username)
        # 草稿态文档对非创建者不可见 → 原件同样 404
        assert client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=member_auth).status_code == 404

        published = client.patch(DOCS.format(ws=ws.id) + f"/{doc['id']}", json={"status": "published"}, headers=auth)
        assert published.status_code == 200, published.text
        assert client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=member_auth).status_code == 200

    def test_missing_file_returns_404(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        for path in (Path(settings.UPLOAD_DIR) / str(ws.id)).iterdir():
            path.unlink()
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset", headers=auth)
        assert r.status_code == 404


MHTML_PREVIEW_BOUNDARY = "----MultipartBoundary--api62----"


def _make_mhtml(html: str, image_location: str | None = None) -> bytes:
    """构造最小 MHTML：根 HTML 走 QP，可选打包一张 PNG."""
    lines = [
        "From: <Saved by Blink>",
        "MIME-Version: 1.0",
        f'Content-Type: multipart/related; type="text/html"; boundary="{MHTML_PREVIEW_BOUNDARY}"',
        "",
        f"--{MHTML_PREVIEW_BOUNDARY}",
        "Content-Type: text/html; charset=UTF-8",
        "Content-Transfer-Encoding: quoted-printable",
        "Content-Location: https://example.com/page",
        "",
        quopri.encodestring(html.encode("utf-8")).decode("ascii"),
        "",
    ]
    if image_location:
        lines += [
            f"--{MHTML_PREVIEW_BOUNDARY}",
            "Content-Type: image/png",
            "Content-Transfer-Encoding: base64",
            f"Content-Location: {image_location}",
            "",
            base64.encodebytes(PNG_BYTES).decode("ascii"),
            "",
        ]
    lines.append(f"--{MHTML_PREVIEW_BOUNDARY}--")
    return "\n".join(lines).encode("ascii")


class TestMhtmlPreviewEndpoint:
    """MHTML 在线预览端点（需求 0064 C1/C4）：自包含 HTML + 沙箱响应头."""

    def _import_mhtml(self, client, ws_id: int, auth) -> dict:
        html = (
            "<html><head><title>网页存档</title><style>p{color:blue}</style></head>"
            '<body><p>正文</p><img src="https://example.com/a.png" alt="图"></body></html>'
        )
        _import_one(
            client,
            ws_id,
            auth,
            "页面.mhtml",
            _make_mhtml(html, "https://example.com/a.png"),
            "message/rfc822",
        )
        return _doc(client, ws_id, auth)

    def test_preview_returns_selfcontained_html(self, client, ws, auth):
        doc = self._import_mhtml(client, ws.id, auth)
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=auth)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/html")
        assert r.headers["content-security-policy"] == "sandbox"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-disposition"].startswith("inline")
        body = r.text
        assert "<style>p{color:blue}</style>" in body
        assert "data:image/png;base64," in body
        assert "https://example.com/a.png" not in body

    def test_preview_rejects_non_mhtml(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=auth)
        assert r.status_code == 400

    def test_preview_broken_file_returns_400(self, client, ws, auth):
        doc = self._import_mhtml(client, ws.id, auth)
        for path in (Path(settings.UPLOAD_DIR) / str(ws.id)).iterdir():
            path.write_bytes(b"junk")
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=auth)
        assert r.status_code == 400

    def test_preview_respects_visibility(self, client, db, ws, auth):
        doc = self._import_mhtml(client, ws.id, auth)
        member = _make_user(db, "mhtml_member")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=member.id, role=WorkspaceRole.EDITOR))
        db.commit()
        member_auth = _login(client, member.username)
        # 草稿态对非创建者不可见 → 预览同样 404
        assert client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=member_auth).status_code == 404
        published = client.patch(DOCS.format(ws=ws.id) + f"/{doc['id']}", json={"status": "published"}, headers=auth)
        assert published.status_code == 200, published.text
        assert client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=member_auth).status_code == 200


class TestOfficePreviewEndpoint:
    """Excel / Word 预览端点（ADR 0087）：自包含 HTML + 沙箱响应头."""

    def _import(self, client, ws_id: int, auth, name: str, data: bytes, mime: str, **form) -> dict:
        _import_one(client, ws_id, auth, name, data, mime, **form)
        return _doc(client, ws_id, auth)

    def test_xlsx_preview_renders_table(self, client, ws, auth):
        doc = self._import(
            client,
            ws.id,
            auth,
            "明细.xlsx",
            XLSX_REAL_BYTES,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=auth)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/html")
        assert r.headers["content-security-policy"] == "sandbox"
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["content-disposition"].startswith("inline")
        assert '<table class="sheet">' in r.text
        assert "销售明细" in r.text

    def test_docx_preview_renders_document(self, client, ws, auth):
        doc = self._import(
            client,
            ws.id,
            auth,
            "说明书.docx",
            DOCX_REAL_BYTES,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            docx_mode="archive",
        )
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=auth)
        assert r.status_code == 200, r.text
        assert "<h1>项目说明</h1>" in r.text
        assert "data:image/png;base64," in r.text

    def test_legacy_xls_preview_rejected(self, client, ws, auth):
        # 旧版 .xls 属 xlsx 渲染族但 MIME 为二进制 Excel：保持下载卡（400）
        doc = self._import(client, ws.id, auth, "老表.xls", XLSX_BYTES, "application/vnd.ms-excel")
        assert doc["content_type"] == "xlsx"
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=auth)
        assert r.status_code == 400

    def test_broken_xlsx_preview_returns_400(self, client, ws, auth):
        doc = self._import(
            client,
            ws.id,
            auth,
            "坏表.xlsx",
            XLSX_BYTES,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=auth)
        assert r.status_code == 400

    def test_preview_missing_original_returns_404(self, client, ws, auth):
        doc = self._import(
            client,
            ws.id,
            auth,
            "明细.xlsx",
            XLSX_REAL_BYTES,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        for path in (Path(settings.UPLOAD_DIR) / str(ws.id)).iterdir():
            path.unlink()
        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=auth)
        assert r.status_code == 404

    def test_preview_respects_visibility(self, client, db, ws, auth):
        doc = self._import(
            client,
            ws.id,
            auth,
            "明细.xlsx",
            XLSX_REAL_BYTES,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        member = _make_user(db, "office_preview_member")
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=member.id, role=WorkspaceRole.EDITOR))
        db.commit()
        member_auth = _login(client, member.username)
        assert client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=member_auth).status_code == 404
        published = client.patch(DOCS.format(ws=ws.id) + f"/{doc['id']}", json={"status": "published"}, headers=auth)
        assert published.status_code == 200, published.text
        assert client.get(f"{DOCS.format(ws=ws.id)}/{doc['id']}/asset/preview", headers=member_auth).status_code == 200


class TestExportAssets:
    """文档树导出（需求 0088）：原件族按原件字节与扩展名导出，不转空 Markdown."""

    DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def _seed(self, client, ws, auth) -> None:
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        _import_one(client, ws.id, auth, "明细.xlsx", XLSX_REAL_BYTES, self.XLSX_MIME)
        _import_one(client, ws.id, auth, "说明书.docx", DOCX_REAL_BYTES, self.DOCX_MIME, docx_mode="archive")
        assert client.post(
            DOCS.format(ws=ws.id),
            json={"title": "正文", "content": "# 标题\n\n正文", "status": "published"},
            headers=auth,
        ).status_code in (200, 201)

    def _export(self, client, ws, auth, **params) -> tuple[bytes, str]:
        r = client.get(DOCS.format(ws=ws.id) + "/export/vault", params=params, headers=auth)
        assert r.status_code == 200, r.text
        return r.content, r.headers["content-disposition"]

    def test_archive_style_exports_originals(self, client, ws, auth):
        self._seed(client, ws, auth)
        content, disposition = self._export(client, ws, auth)
        assert re.search(r"documents-\d{8}-\d{4}\.zip", disposition)

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            # 原件族：原扩展名 + 原始字节
            assert "原件库/报告.pdf" in names
            assert archive.read("原件库/报告.pdf") == PDF_BYTES
            assert archive.read("原件库/明细.xlsx") == XLSX_REAL_BYTES
            assert archive.read("原件库/说明书.docx") == DOCX_REAL_BYTES
            # 不再出现空 Markdown 占位
            assert not {"原件库/报告.md", "原件库/明细.md", "原件库/说明书.md"} & names
            # Markdown 正文按正文导出，压缩文档不带 front-matter / .obsidian
            assert not archive.read("原件库/正文.md").decode("utf-8").startswith("---")
            assert not any(name.startswith("原件库/.obsidian/") for name in names)

    def test_obsidian_style_keeps_originals(self, client, ws, auth):
        self._seed(client, ws, auth)
        content, disposition = self._export(client, ws, auth, style="obsidian")
        assert re.search(r"obsidian-\d{8}-\d{4}\.zip", disposition)

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
            assert archive.read("原件库/报告.pdf") == PDF_BYTES
            assert "原件库/说明书.docx" in names
            assert "原件库/.obsidian/app.json" in names
            assert archive.read("原件库/正文.md").decode("utf-8").startswith("---")

    def test_asset_title_collides_with_markdown(self, client, ws, auth):
        """同名原件与 Markdown 并存：扩展名参与去重，两者都保留."""
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        assert client.post(
            DOCS.format(ws=ws.id),
            json={"title": "报告", "content": "正文", "status": "published"},
            headers=auth,
        ).status_code in (200, 201)

        content, _ = self._export(client, ws, auth)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            names = set(archive.namelist())
        assert "原件库/报告.pdf" in names
        assert "原件库/报告.md" in names


class TestAssetReadOnly:
    def test_content_draft_submit_rejected(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        base = DOCS.format(ws=ws.id) + f"/{doc['id']}"

        r = client.put(f"{base}/content", json={"content": "# 改写"}, headers=auth)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "doc_read_only"

        r = client.put(f"{base}/draft", json={"content": "# 草稿"}, headers=auth)
        assert r.status_code == 409

        r = client.post(f"{base}/submit", json={"content": "# 提交"}, headers=auth)
        assert r.status_code == 409

    def test_rollback_rejected(self, client, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        r = client.post(f"{DOCS.format(ws=ws.id)}/{doc['id']}/rollback", json={"target_version": 1}, headers=auth)
        assert r.status_code == 409


class TestAssetPurge:
    def test_purge_removes_original_and_owner(self, client, db, ws, auth):
        _import_one(client, ws.id, auth, "报告.pdf", PDF_BYTES, "application/pdf")
        doc = _doc(client, ws.id, auth)
        directory = Path(settings.UPLOAD_DIR) / str(ws.id)
        assert len(list(directory.iterdir())) == 1

        base = DOCS.format(ws=ws.id) + f"/{doc['id']}"
        assert client.delete(base, headers=auth).status_code == 200
        purged = client.delete(f"{base}/purge", headers=auth)
        assert purged.status_code == 200, purged.text
        assert list(directory.iterdir()) == []
        owners = db.execute(select(FileOwner).where(FileOwner.workspace_id == ws.id)).scalars().all()
        assert owners == []


class TestAssetServiceGuards:
    """服务层分支（接口层不易触达的防御口径）."""

    def test_replace_requires_asset_document(self, db, ws, owner):
        from cndb.core.errors import ConflictError
        from cndb.plugins.documents.services import content as content_service

        markdown_doc = content_service.create_document(db, ws.id, owner, title="普通文档", content="正文")
        with pytest.raises(ConflictError):
            content_service.replace_document_asset(
                db,
                ws.id,
                markdown_doc.id,
                owner,
                asset_file_key="x.pdf",
                asset_mime="application/pdf",
                content_size=10,
            )

    def test_replace_rejects_folder(self, db, ws, owner):
        from cndb.core.errors import ConflictError
        from cndb.plugins.documents.services import content as content_service

        folder = content_service.create_document(db, ws.id, owner, title="目录", is_folder=True)
        with pytest.raises(ConflictError):
            content_service.replace_document_asset(
                db,
                ws.id,
                folder.id,
                owner,
                asset_file_key="x.pdf",
                asset_mime="application/pdf",
                content_size=10,
            )

    def test_remove_workspace_file_tolerates_bad_key(self, ws):
        from cndb.plugins.files.services import remove_workspace_file

        assert remove_workspace_file(ws.id, "../escape.pdf") is False
        assert remove_workspace_file(ws.id, "not-exists.pdf") is False
