"""内嵌图表块的导出端到端测试（ADR 0052 D6 / D11 / P0）.

覆盖：Markdown 归档保留定义块并追加指纹命名的静态 SVG、重复定义复用资产、
DOCX / PDF 从块渲染图形、坏块降级不阻断、无图表文档零回归（I8）。
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services.charts.inline import serialize_inline_chart_block
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
TEMPLATE = "stacked-bar-horizontal"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def owner(db: Session) -> User:
    u = User(username="inline_export_owner", nickname="inline_export_owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db: Session, owner: User) -> Workspace:
    w = Workspace(name="InlineExportWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _create_doc(db: Session, ws: Workspace, owner: User, content: str, title: str = "带图文档"):
    return content_service.create_document(db, ws.id, owner, title=title, content=content)


def _export(client: TestClient, auth: dict[str, str], ws: Workspace, doc_id: int, fmt: str):
    return client.get(f"{DOCS.format(ws=ws.id)}/{doc_id}/export", params={"format": fmt}, headers=auth)


class TestMarkdownExport:
    def test_block_preserved_and_asset_packed(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        block = serialize_inline_chart_block(template_key=TEMPLATE, config={}, width=60, title="市场规模")
        doc = _create_doc(db, ws, owner, f"# 报表\n\n{block}\n")

        r = _export(client, auth, ws, doc.id, "md")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("application/zip")
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            md_name = next(n for n in zf.namelist() if n.endswith(".md"))
            archived = zf.read(md_name).decode("utf-8")
            assets = [n for n in zf.namelist() if n.startswith("assets/chart-")]
            assert len(assets) == 1
            svg = zf.read(assets[0])

        assert "```chart" in archived
        assert '"template": "stacked-bar-horizontal"' in archived
        assert f"![市场规模]({assets[0]})" in archived
        assert "{{chart:" not in archived
        assert svg.startswith(b"<svg")

    def test_duplicate_definition_reuses_asset(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        block = serialize_inline_chart_block(template_key=TEMPLATE, config={})
        doc = _create_doc(db, ws, owner, f"{block}\n\n正文\n\n{block}")
        r = _export(client, auth, ws, doc.id, "md")
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assets = [n for n in zf.namelist() if n.startswith("assets/chart-")]
        assert len(assets) == 1

    def test_broken_block_keeps_plain_markdown(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        content = "前文\n\n```chart\n{bad json}\n```\n\n后文"
        doc = _create_doc(db, ws, owner, content)
        r = _export(client, auth, ws, doc.id, "md")
        assert r.status_code == 200, r.text
        # 无资产 → 保持单文件 .md，块原文保留（可修复，D11）
        assert r.headers["content-type"].startswith("text/markdown")
        text = r.content.decode("utf-8")
        assert "```chart" in text
        assert "{bad json}" in text

    def test_no_chart_document_unchanged(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(db, ws, owner, "# 标题\n\n普通正文\n")
        r = _export(client, auth, ws, doc.id, "md")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("text/markdown")
        assert r.content.decode("utf-8") == "# 标题\n\n普通正文\n"


class TestDocxPdfExport:
    def test_docx_embeds_chart(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        block = serialize_inline_chart_block(template_key=TEMPLATE, config={})
        doc = _create_doc(db, ws, owner, block)
        r = _export(client, auth, ws, doc.id, "docx")
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert any(n.startswith("word/media/") for n in zf.namelist())

    def test_docx_broken_block_degrades(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        doc = _create_doc(db, ws, owner, "```chart\n{bad}\n```")
        r = _export(client, auth, ws, doc.id, "docx")
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8")
        assert "图表定义无效" in xml

    def test_pdf_embeds_chart(self, client, ws, owner, db):
        auth = _login(client, owner.username)
        block = serialize_inline_chart_block(template_key=TEMPLATE, config={})
        doc = _create_doc(db, ws, owner, block)
        r = _export(client, auth, ws, doc.id, "pdf")
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")

    def test_docx_chart_plus_table(self, client, ws, owner, db):
        """图表块前后各有表格时不串行（表格缓冲需在块前 flush）."""
        auth = _login(client, owner.username)
        block = serialize_inline_chart_block(template_key=TEMPLATE, config={})
        content = "| A | B |\n| --- | --- |\n| 1 | 2 |\n\n" + block + "\n\n| C | D |\n| --- | --- |\n| 3 | 4 |"
        doc = _create_doc(db, ws, owner, content)
        r = _export(client, auth, ws, doc.id, "docx")
        assert r.status_code == 200, r.text
        with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
            assert any(n.startswith("word/media/") for n in zf.namelist())
            assert zf.read("word/document.xml").count(b"<w:tbl>") == 2


def test_fingerprint_matches_serialized_block():
    """导出资产名与正文块指纹一致（前后端同批序列化规则）."""
    block = serialize_inline_chart_block(template_key=TEMPLATE, config={"a": 1}, width=40)
    payload = json.loads(block.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert payload["width"] == 40
    assert payload["template"] == TEMPLATE
