"""数据表引用导出渲染测试（ADR 0045）.

覆盖：占位符解析（与前端同构）、Markdown 改写为静态 GFM 表格、
按视图过滤 / 排序取数、字段与角色隐藏、截断上限、记忆化、
坏引用降级，以及经导出接口的 md / docx / pdf 端到端验证。
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, select
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services.export import render_export, table_refs
from cndb.plugins.documents.services.export.table_refs import (
    ResolvedTable,
    TableRefSpec,
    make_table_resolver,
    parse_table_ref_line,
    rewrite_markdown_table_refs,
)
from cndb.plugins.tables.models import DataField, DataTable, DataView, TablePermission
from cndb.plugins.tables.services.core import ddl as table_ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"

# 1x1 PNG（合法图片字节，供归档用例使用）
PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001a5f645400000000049454e44ae426082"
)


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


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "tbl_ref_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="TableRefWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def table(db, ws) -> DataTable:
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, owner_id=ws.created_by_id, name="客户表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    f_name = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    f_name.ensure_db_name()
    f_city = DataField(table_id=dt.id, name="城市", field_type="text", order=1)
    f_city.ensure_db_name()
    db.add_all([f_name, f_city])
    db.commit()
    db.refresh(dt)
    table_ddl.create_table(engine, dt)

    meta = MetaData()
    meta.reflect(bind=engine, only=[dt.db_table_name])
    sa_table = meta.tables[dt.db_table_name]
    with engine.begin() as conn:
        conn.execute(
            sa_table.insert(),
            [
                {f_name.db_column_name: "张三", f_city.db_column_name: "北京"},
                {f_name.db_column_name: "李四", f_city.db_column_name: "上海"},
                {f_name.db_column_name: "王五", f_city.db_column_name: "北京"},
            ],
        )
    return dt


@pytest.fixture
def view(db, table, owner) -> DataView:
    dv = DataView(
        table_id=table.id,
        owner_id=owner.id,
        name="北京客户",
        view_type="grid",
        filters=[{"field_name": "城市", "op": "eq", "value": "北京"}],
        sortings=[{"field_name": "姓名", "direction": "desc"}],
    )
    db.add(dv)
    db.commit()
    db.refresh(dv)
    return dv


class TestParse:
    def test_plain_table(self):
        assert parse_table_ref_line("{{table:1}}") == TableRefSpec(table_id=1, view_id=None)

    def test_with_view_and_limit_any_order(self):
        assert parse_table_ref_line("{{table:1|view=2|limit=5}}").view_id == 2  # type: ignore[union-attr]
        assert parse_table_ref_line("{{table:1|limit=5|view=2}}").view_id == 2  # type: ignore[union-attr]

    def test_trimmed_and_unknown_params(self):
        spec = parse_table_ref_line("  {{table:7|foo=bar}}  ")
        assert spec == TableRefSpec(table_id=7, view_id=None)

    def test_invalid_view_falls_back_to_whole_table(self):
        assert parse_table_ref_line("{{table:1|view=abc}}") == TableRefSpec(table_id=1, view_id=None)
        assert parse_table_ref_line("{{table:1|view=0}}") == TableRefSpec(table_id=1, view_id=None)

    def test_inline_and_invalid_are_ignored(self):
        assert parse_table_ref_line("前面 {{table:1}} 后面") is None
        assert parse_table_ref_line("{{table:x}}") is None
        assert parse_table_ref_line("") is None

    def test_width_default_is_75(self):
        assert parse_table_ref_line("{{table:1}}").width == 75  # type: ignore[union-attr]
        assert parse_table_ref_line("{{table:1|view=2}}").width == 75  # type: ignore[union-attr]

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("25", 25),
            ("50", 50),
            ("100", 100),
            ("", 75),
            ("abc", 75),
            ("50.5", 75),
            ("24", 75),
            ("101", 75),
        ],
    )
    def test_width_range_and_fallback(self, raw: str, expected: int):
        spec = parse_table_ref_line(f"{{{{table:1|view=2|width={raw}}}}}")
        assert spec is not None
        assert spec.width == expected
        assert spec.view_id == 2


class TestRewriteMarkdown:
    def test_renders_caption_and_gfm_table(self):
        resolved = ResolvedTable(
            table_name="客户表",
            view_name="北京客户",
            header=["姓名", "城市"],
            rows=[["张三", "北京"], ["王五", "北京"]],
            total=2,
        )
        md = rewrite_markdown_table_refs("前文\n\n{{table:1|view=2}}\n\n后文", lambda _s: resolved)
        assert "前文" in md and "后文" in md
        assert "*客户表 · 北京客户 · 共 2 行*" in md
        assert "| 姓名 | 城市 |" in md
        assert "| --- | --- |" in md
        assert "| 张三 | 北京 |" in md
        assert "{{table:" not in md

    def test_cells_escape_pipe_and_newline(self):
        resolved = ResolvedTable(
            table_name="T",
            header=["列"],
            rows=[["a|b", "第一行\n第二行"]],
            total=1,
        )
        md = rewrite_markdown_table_refs("{{table:1}}", lambda _s: resolved)
        assert r"a\|b" in md
        assert "第一行<br>第二行" in md

    def test_error_degrades_to_placeholder(self):
        md = rewrite_markdown_table_refs("{{table:9}}", lambda _s: ResolvedTable(error="[数据表引用无效：表 #9]"))
        assert md == "[数据表引用无效：表 #9]"
        assert "{{table:" not in md

    def test_inline_reference_not_rewritten(self):
        md = "前面 {{table:1}} 后面"
        assert rewrite_markdown_table_refs(md, lambda _s: ResolvedTable()) == md


class TestExportResolver:
    def test_view_filters_and_sorts_rows(self, db, ws, owner, table, view):
        resolved = make_table_resolver(db, ws.id, owner)(TableRefSpec(table.id, view.id))
        assert resolved.error is None
        assert resolved.table_name == "客户表"
        assert resolved.view_name == "北京客户"
        assert resolved.header == ["姓名", "城市"]
        assert resolved.rows == [["王五", "北京"], ["张三", "北京"]]
        assert resolved.total == 2
        assert resolved.truncated is False
        assert resolved.caption == "客户表 · 北京客户 · 共 2 行"

    def test_whole_table_without_view(self, db, ws, owner, table):
        resolved = make_table_resolver(db, ws.id, owner)(TableRefSpec(table.id))
        assert resolved.error is None
        assert resolved.view_name is None
        assert resolved.total == 3
        assert resolved.caption == "客户表 · 共 3 行"

    def test_hidden_field_excluded_from_header(self, db, ws, owner, table):
        f_hidden = DataField(table_id=table.id, name="备注", field_type="text", order=2, hidden=True)
        f_hidden.ensure_db_name()
        db.add(f_hidden)
        db.commit()

        resolved = make_table_resolver(db, ws.id, owner)(TableRefSpec(table.id))
        assert resolved.header == ["姓名", "城市"]

    def test_role_hidden_field_excluded_from_header(self, db, ws, owner, table):
        db.add(TablePermission(table_id=table.id, hidden_fields={"owner": ["城市"]}))
        db.commit()

        resolved = make_table_resolver(db, ws.id, owner)(TableRefSpec(table.id))
        assert resolved.header == ["姓名"]
        assert all(len(row) == 1 for row in resolved.rows or [])

    def test_truncation_marks_caption(self, db, ws, owner, table, monkeypatch):
        monkeypatch.setattr(table_refs, "MAX_EXPORT_TABLE_ROWS", 2)
        resolved = make_table_resolver(db, ws.id, owner)(TableRefSpec(table.id))
        assert resolved.truncated is True
        assert len(resolved.rows or []) == 2
        assert resolved.total == 3
        assert "（仅导出前 2 行）" in resolved.caption

    def test_missing_table_degrades(self, db, ws, owner):
        resolved = make_table_resolver(db, ws.id, owner)(TableRefSpec(999999))
        assert resolved.error is not None
        assert "表 #999999" in resolved.error

    def test_cross_workspace_table_degrades(self, db, ws, owner, table):
        other = Workspace(name="OtherWS", created_by_id=owner.id)
        db.add(other)
        db.commit()

        resolved = make_table_resolver(db, other.id, owner)(TableRefSpec(table.id))
        assert resolved.error is not None

    def test_invisible_view_degrades(self, db, ws, owner, table):
        resolved = make_table_resolver(db, ws.id, owner)(TableRefSpec(table.id, 999999))
        assert resolved.error is not None
        assert "视图 #999999" in resolved.error

    def test_repeated_reference_queries_once(self, db, ws, owner, table, monkeypatch):
        calls: list[int] = []
        original = table_refs.get_table_or_404

        def _counting(*args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(table_refs, "get_table_or_404", _counting)
        resolver = make_table_resolver(db, ws.id, owner)
        spec = TableRefSpec(table.id)
        resolver(spec)
        resolver(spec)
        assert len(calls) == 1


class TestLinkFieldDisplay:
    def test_link_field_shows_display_summary(self, db, db_engine, ws, owner, table):
        """link 字段导出为显示值摘要（逗号连接），而非原始 JSON."""
        from cndb.plugins.tables.services.core import links as links_service

        # 目标表 + 两行
        target = DataTable(workspace_id=ws.id, owner_id=owner.id, name="客户主表")
        target.ensure_db_name()
        db.add(target)
        db.flush()
        f_t = DataField(table_id=target.id, name="客户名", field_type="text", order=0)
        f_t.ensure_db_name()
        db.add(f_t)
        db.commit()
        db.refresh(target)
        table_ddl.create_table(db_engine, target)
        meta = MetaData()
        meta.reflect(bind=db_engine, only=[target.db_table_name])
        sa_target = meta.tables[target.db_table_name]
        with db_engine.begin() as conn:
            conn.execute(sa_target.insert(), [{f_t.db_column_name: "KT甲"}, {f_t.db_column_name: "KT乙"}])
        target_ids = [r[0] for r in db_engine.connect().execute(select(sa_target.c.id))]

        # 源表加 link 字段（含物理关联表）
        f_link = DataField(
            table_id=table.id,
            name="关联客户",
            field_type="link",
            order=2,
            config={"target_table_id": target.id, "multiple": True},
        )
        f_link.ensure_db_name()
        db.add(f_link)
        db.commit()
        db.refresh(f_link)
        table_ddl.add_column(db_engine, table, f_link)
        table_ddl.create_link_table(db_engine, f_link)

        # 已有首行（张三，id=1）挂两条 link
        links_service.set_links(db_engine, f_link, row_id=1, target_ids=target_ids, db=db)

        resolved = make_table_resolver(db, ws.id, owner)(TableRefSpec(table.id))
        assert resolved.error is None
        idx = resolved.header.index("关联客户")
        assert any("KT甲, KT乙" in (row[idx] or "") for row in resolved.rows or [])
        assert all("[{" not in cell for row in resolved.rows or [] for cell in row)


class TestExportEndpoint:
    def _create_doc(self, db, ws, owner, content: str, title: str = "带表文档"):
        return content_service.create_document(db, ws.id, owner, title=title, content=content)

    def test_markdown_export_renders_table(self, client, ws, owner, table, db):
        auth = _login(client, owner.username)
        doc = self._create_doc(db, ws, owner, f"# 报表\n\n{{{{table:{table.id}}}}}\n")

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc.id}/export", params={"format": "md"}, headers=auth)
        assert r.status_code == 200, r.text
        text = r.content.decode("utf-8")
        assert "{{table:" not in text
        assert "| 姓名 | 城市 |" in text
        assert "张三" in text
        assert "共 3 行" in text

    def test_docx_export_contains_table_nodes(self, client, ws, owner, table, view, db):
        auth = _login(client, owner.username)
        doc = self._create_doc(db, ws, owner, f"{{{{table:{table.id}|view={view.id}}}}}")

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc.id}/export", params={"format": "docx"}, headers=auth)
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        assert "<w:tbl>" in xml
        assert "王五" in xml
        assert "{{table:" not in xml

    def test_docx_export_table_width_percent(self, client, ws, owner, table, db):
        """DOCX 表宽按正文宽度百分比写入 ``w:tblW``（ADR 0051 D5）."""
        auth = _login(client, owner.username)

        def _tbl_width(percent: int) -> str:
            doc = self._create_doc(
                db,
                ws,
                owner,
                f"{{{{table:{table.id}|width={percent}}}}}",
                title=f"表宽{percent}",
            )
            r = client.get(f"{DOCS.format(ws=ws.id)}/{doc.id}/export", params={"format": "docx"}, headers=auth)
            assert r.status_code == 200, r.text
            with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
                xml = zf.read("word/document.xml").decode("utf-8")
            m = re.search(r'<w:tblW w:type="pct" w:w="(\d+)"/>', xml)
            assert m is not None
            return m.group(1)

        assert _tbl_width(75) == "3750"
        assert _tbl_width(50) == "2500"

    def test_pdf_export_renders(self, client, ws, owner, table, db):
        auth = _login(client, owner.username)
        doc = self._create_doc(db, ws, owner, f"{{{{table:{table.id}}}}}")

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc.id}/export", params={"format": "pdf"}, headers=auth)
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")

    def test_broken_reference_does_not_break_export(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = self._create_doc(db, ws, owner, "前文\n\n{{table:999999}}\n\n后文")

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc.id}/export", params={"format": "md"}, headers=auth)
        assert r.status_code == 200, r.text
        text = r.content.decode("utf-8")
        assert "前文" in text and "后文" in text
        assert "数据表引用无效" in text
        assert "{{table:" not in text

    def test_markdown_archive_rewrites_before_packaging(self, client, ws, owner, table, db):
        auth = _login(client, owner.username)
        up = client.post(
            f"/api/v1/workspaces/{ws.id}/files",
            files={"file": ("图表.png", PNG_1PX, "image/png")},
            headers=auth,
        )
        assert up.status_code == 201, up.text
        file_key = up.json()["file_key"]
        doc = self._create_doc(db, ws, owner, f"![图表](file:{file_key})\n\n{{{{table:{table.id}}}}}")

        r = client.get(f"{DOCS.format(ws=ws.id)}/{doc.id}/export", params={"format": "md"}, headers=auth)
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            md_name = next(n for n in zf.namelist() if n.endswith(".md"))
            archived = zf.read(md_name).decode("utf-8")
        assert "{{table:" not in archived
        assert "| 姓名 | 城市 |" in archived


class TestRenderExportDirect:
    def test_markdown_exporter_accepts_resolver(self):
        resolver = lambda _s: ResolvedTable(  # noqa: E731
            table_name="T", header=["列"], rows=[["值"]], total=1
        )
        data = render_export("{{table:1}}", "md", "标题", tables=resolver)
        assert b"{{table:" not in data
        assert "| 列 |" in data.decode("utf-8")
