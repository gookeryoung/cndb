"""文档导出模板（ADR 0152）测试.

覆盖：
- 内置 6 套预设全部通过校验；默认锚点为 ``research``（研究报告）
- 配置校验边界（字号 / 行距 / 缩进 / 颜色 / 枚举 / 未知字段）与引用规范
- 解析链：显式 ref → 工作区默认 → 内置 research；跨工作区 404（I1）
- API：成员可读、editor 才可写、内置只读、重名 400、默认唯一
- 预览端点返回真实 docx / pdf 字节
- 导出端点 ``template`` 参数生效（docx 字体 / 标题编号）且不带时行为不变
- 迁移 upgrade 幂等 + downgrade 可还原
- 备份 v17 往返与旧包（无 templates 键）兼容
"""

from __future__ import annotations

import importlib
import io
import zipfile
from typing import Any

import pytest
from docx import Document
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import ExportTemplate
from cndb.plugins.documents.services.export import templates as tpl
from cndb.plugins.documents.services.export.templates import (
    BUILTIN_TEMPLATES,
    DEFAULT_TEMPLATE_REF,
    config_to_dict,
    heading_prefix,
    normalize_ref,
    resolve_export_template,
    validate_config,
)
from cndb.plugins.documents.services.export.theme import DEFAULT_THEME
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

DOCS = "/api/v1/workspaces/{ws}/documents"
TEMPLATES = "/api/v1/workspaces/{ws}/documents/templates"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    user = User(username=username, nickname=username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _add_member(db: Session, ws: Workspace, username: str, role: WorkspaceRole) -> User:
    user = _make_user(db, username)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role))
    db.commit()
    return user


@pytest.fixture
def owner(db) -> User:
    return _make_user(db, "tpl_owner")


@pytest.fixture
def ws(db, owner) -> Workspace:
    workspace = Workspace(name="模板工作区", created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


@pytest.fixture
def viewer(db, ws) -> User:
    return _add_member(db, ws, "tpl_viewer", WorkspaceRole.VIEWER)


@pytest.fixture
def editor(db, ws) -> User:
    return _add_member(db, ws, "tpl_editor", WorkspaceRole.EDITOR)


@pytest.fixture
def owner_headers(client, owner) -> dict[str, str]:
    return _login(client, owner.username)


@pytest.fixture
def editor_headers(client, editor) -> dict[str, str]:
    return _login(client, editor.username)


@pytest.fixture
def viewer_headers(client, viewer) -> dict[str, str]:
    return _login(client, viewer.username)


def _create_doc(client: TestClient, ws: Workspace, headers: dict[str, str], content: str) -> int:
    r = client.post(
        f"{DOCS.format(ws=ws.id)}",
        json={"title": "模板导出文档", "content": content, "status": "published"},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _export(client: TestClient, ws: Workspace, doc_id: int, headers: dict[str, str], **params: Any) -> Any:
    return client.get(f"{DOCS.format(ws=ws.id)}/{doc_id}/export", params=params, headers=headers)


class TestBuiltinPresets:
    def test_all_builtin_presets_validate(self):
        assert len(BUILTIN_TEMPLATES) == 6
        assert set(BUILTIN_TEMPLATES) == {"research", "techreport", "trend", "thesis", "official", "press"}
        for key, builtin in BUILTIN_TEMPLATES.items():
            config = validate_config(config_to_dict(builtin.config))
            assert config.body.size > 0
            assert len(config.headings) == 6
            assert builtin.ref == f"builtin:{key}"

    def test_default_preset_is_research(self):
        """默认锚点为「研究报告」：企业报告规范的通用基线（标准 / 周报已移除）."""
        assert DEFAULT_TEMPLATE_REF == "builtin:research"
        config = BUILTIN_TEMPLATES["research"].config
        assert config.body.east_asia_font == "宋体"
        assert config.body.size == 12.0
        # 历史 DEFAULT_THEME 仍保留给 PDF 兼容路径，但不再是导出默认
        assert DEFAULT_THEME.body_size == 10.5

    def test_official_preset_matches_gb9704(self):
        """公文预设对齐 GB/T 9704-2012：边距 37/35/28/26mm、正文三号仿宋、标题 2 号小标宋、4 号页码."""
        config = BUILTIN_TEMPLATES["official"].config
        assert (config.page.margin_top, config.page.margin_bottom) == (3.7, 3.5)
        assert (config.page.margin_left, config.page.margin_right) == (2.8, 2.6)
        assert config.body.east_asia_font == "仿宋"
        assert config.body.size == 16.0  # 三号
        assert config.body.line_spacing_rule == "fixed"
        assert config.body.line_spacing_pt == 28.0
        assert config.heading(1).east_asia_font == "方正小标宋简体"
        assert config.heading(1).size == 22.0  # 二号
        assert config.heading(1).align == "center"
        assert config.heading(2).east_asia_font == "黑体"
        assert config.heading(3).east_asia_font == "楷体"
        assert config.numbering.heading == "cn_ordinal"
        # 公文页码是 4 号数字，不写「第 X 页 共 Y 页」
        assert config.header_footer.page_number == "plain"
        assert config.header_footer.font_size == 14.0

    def test_thesis_preset_matches_thesis_norms(self):
        """论文预设：左侧装订边 3cm、正文小四宋体 1.5 倍行距、一级标题三号黑体居中、第一章编号."""
        config = BUILTIN_TEMPLATES["thesis"].config
        assert config.page.margin_left == 3.0
        assert config.body.east_asia_font == "宋体"
        assert config.body.size == 12.0
        assert config.body.line_spacing == 1.5
        assert config.body.first_line_indent_chars == 2.0
        assert config.heading(1).east_asia_font == "黑体"
        assert config.heading(1).size == 16.0
        assert config.heading(1).align == "center"
        assert config.numbering.heading == "chapter_chinese"
        assert config.table.style == "three_line"

    def test_report_presets_use_standard_sizes(self):
        """报告类预设统一小四 12pt / 1.5 倍行距（避免 11pt 这类非标准号数）."""
        for key in ("research", "techreport", "trend", "press"):
            body = BUILTIN_TEMPLATES[key].config.body
            assert body.size == 12.0, key
            assert body.east_asia_font == "宋体", key
            if key != "press":
                assert body.line_spacing == 1.5, key

    def test_builtin_presets_are_not_rows(self, db, ws):
        assert db.query(ExportTemplate).count() == 0


class TestValidate:
    @pytest.mark.parametrize(
        "patch",
        [
            {"body": {"size": 7.0}},
            {"body": {"size": 73.0}},
            {"body": {"line_spacing": 0.9}},
            {"body": {"line_spacing": 3.1}},
            {"body": {"first_line_indent_chars": 9}},
            {"body": {"color": "red"}},
            {"body": {"color": "#123"}},
            {"body": {"unknown_field": 1}},
            {"table": {"style": "double"}},
            {"page": {"paper": "B5"}},
        ],
    )
    def test_invalid_config_rejected(self, patch):
        with pytest.raises(ValueError):
            validate_config(patch)

    def test_valid_partial_config_fills_defaults(self):
        config = validate_config({"body": {"size": 12.0, "east_asia_font": "宋体"}})
        assert config.body.size == 12.0
        assert config.body.east_asia_font == "宋体"
        assert len(config.headings) == 6

    def test_normalize_ref(self):
        assert normalize_ref("builtin:thesis") == "builtin:thesis"
        assert normalize_ref("  " + "12" + "  ") == "12"
        assert normalize_ref(None) is None
        assert normalize_ref("") is None
        with pytest.raises(ValueError):
            normalize_ref("thesis")
        with pytest.raises(ValueError):
            normalize_ref("-3")

    def test_heading_prefix_schemes(self):
        assert heading_prefix("none", 1, [1, 0, 0, 0, 0, 0]) == ""
        assert heading_prefix("arabic_multilevel", 2, [1, 2, 0, 0, 0, 0]) == "1.2"
        assert heading_prefix("chapter_chinese", 1, [3, 0, 0, 0, 0, 0]) == "第三章"
        assert heading_prefix("cn_ordinal", 1, [2, 0, 0, 0, 0, 0]) == "二、"
        assert heading_prefix("cn_ordinal", 2, [2, 5, 0, 0, 0, 0]) == "（五）"
        # 公文层次序数（GB/T 9704）：三级「1.」 四级「（1）」
        assert heading_prefix("cn_ordinal", 3, [2, 5, 3, 0, 0, 0]) == "3."
        assert heading_prefix("cn_ordinal", 4, [2, 5, 3, 4, 0, 0]) == "（4）"


class TestResolve:
    def test_explicit_builtin(self, db, ws):
        resolved = resolve_export_template(db, ws.id, "builtin:thesis")
        assert resolved.source == "builtin"
        assert resolved.name == "论文"

    def test_explicit_custom(self, db, ws):
        row = ExportTemplate(
            workspace_id=ws.id, name="自定义", config=config_to_dict(BUILTIN_TEMPLATES["trend"].config)
        )
        db.add(row)
        db.commit()
        resolved = resolve_export_template(db, ws.id, str(row.id))
        assert resolved.source == "custom"
        assert resolved.name == "自定义"

    def test_default_chain(self, db, ws):
        row = ExportTemplate(
            workspace_id=ws.id, name="默认", config=config_to_dict(BUILTIN_TEMPLATES["press"].config), is_default=True
        )
        db.add(row)
        db.commit()
        assert resolve_export_template(db, ws.id, None).name == "默认"
        # 显式 ref 优先于默认
        assert resolve_export_template(db, ws.id, "builtin:official").name == "公文"

    def test_fallback_to_default_preset(self, db, ws):
        assert resolve_export_template(db, ws.id, None).ref == DEFAULT_TEMPLATE_REF

    def test_unknown_refs(self, db, ws):
        from cndb.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            resolve_export_template(db, ws.id, "builtin:nope")
        with pytest.raises(NotFoundError):
            resolve_export_template(db, ws.id, "9999")
        with pytest.raises(ValueError):
            resolve_export_template(db, ws.id, "thesis")

    def test_cross_workspace_is_404(self, db, ws, owner):
        other = Workspace(name="另一个", created_by_id=owner.id)
        db.add(other)
        db.commit()
        row = ExportTemplate(
            workspace_id=other.id, name="别人的", config=config_to_dict(BUILTIN_TEMPLATES["press"].config)
        )
        db.add(row)
        db.commit()
        from cndb.core.errors import NotFoundError

        with pytest.raises(NotFoundError):
            resolve_export_template(db, ws.id, str(row.id))


class TestApi:
    def test_list_returns_builtins_and_default(self, client, ws, owner_headers):
        r = client.get(TEMPLATES.format(ws=ws.id), headers=owner_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert len(body["items"]) == 6
        assert body["total"] == 6  # ADR 0177 C4：与内容模板统一的 {items, total} 载荷
        assert body["default_ref"] == DEFAULT_TEMPLATE_REF
        assert all(item["source"] == "builtin" for item in body["items"])

    def test_patch_alias_matches_put(self, client, ws, owner_headers):
        """ADR 0177 D6：导出模板同样接受 PATCH，与 PUT 等价."""
        created = client.post(
            TEMPLATES.format(ws=ws.id), json={"name": "动词等价", "preset_key": "press"}, headers=owner_headers
        ).json()
        r = client.patch(
            f"{TEMPLATES.format(ws=ws.id)}/{created['ref']}",
            json={"name": "动词等价 PATCH"},
            headers=owner_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "动词等价 PATCH"

    def test_viewer_can_read(self, client, ws, viewer_headers):
        r = client.get(TEMPLATES.format(ws=ws.id), headers=viewer_headers)
        assert r.status_code == 200

    def test_create_and_default_unique(self, client, db, ws, owner_headers):
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "报告 A", "preset_key": "research"},
            headers=owner_headers,
        )
        assert r.status_code == 201, r.text
        first = r.json()
        assert first["source"] == "custom"
        r2 = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "报告 B", "preset_key": "trend"},
            headers=owner_headers,
        )
        second = r2.json()
        # 设 A 默认，再设 B 默认 → 只剩 B
        assert (
            client.put(
                f"{TEMPLATES.format(ws=ws.id)}/{first['ref']}", json={"is_default": True}, headers=owner_headers
            ).status_code
            == 200
        )
        assert (
            client.put(
                f"{TEMPLATES.format(ws=ws.id)}/{second['ref']}", json={"is_default": True}, headers=owner_headers
            ).status_code
            == 200
        )
        listed = client.get(TEMPLATES.format(ws=ws.id), headers=owner_headers).json()
        defaults = [item for item in listed["items"] if item["is_default"]]
        assert len(defaults) == 1
        assert defaults[0]["ref"] == second["ref"]
        assert listed["default_ref"] == second["ref"]

    def test_duplicate_name_is_400(self, client, ws, owner_headers):
        client.post(TEMPLATES.format(ws=ws.id), json={"name": "同名", "preset_key": "press"}, headers=owner_headers)
        r = client.post(TEMPLATES.format(ws=ws.id), json={"name": "同名", "preset_key": "press"}, headers=owner_headers)
        assert r.status_code == 400

    def test_viewer_cannot_write(self, client, ws, viewer_headers):
        r = client.post(
            TEMPLATES.format(ws=ws.id), json={"name": "只读", "preset_key": "press"}, headers=viewer_headers
        )
        assert r.status_code == 403

    def test_editor_can_write(self, client, ws, editor_headers):
        r = client.post(
            TEMPLATES.format(ws=ws.id), json={"name": "编辑者建", "preset_key": "press"}, headers=editor_headers
        )
        assert r.status_code == 201

    def test_builtin_read_only(self, client, ws, owner_headers):
        r = client.put(
            f"{TEMPLATES.format(ws=ws.id)}" + "/builtin:thesis", json={"name": "改名"}, headers=owner_headers
        )
        assert r.status_code in (400, 405, 422)
        assert client.delete(TEMPLATES.format(ws=ws.id) + "/builtin:thesis", headers=owner_headers).status_code in (
            400,
            405,
            422,
        )

    def test_get_builtin_detail(self, client, ws, owner_headers):
        r = client.get(TEMPLATES.format(ws=ws.id) + "/builtin:official", headers=owner_headers)
        assert r.status_code == 200
        assert r.json()["name"] == "公文"

    def test_update_and_delete(self, client, ws, owner_headers):
        created = client.post(
            TEMPLATES.format(ws=ws.id), json={"name": "待删", "preset_key": "press"}, headers=owner_headers
        ).json()
        updated = client.put(
            f"{TEMPLATES.format(ws=ws.id)}/{created['ref']}",
            json={"name": "已改名", "description": "说明"},
            headers=owner_headers,
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "已改名"
        deleted = client.delete(f"{TEMPLATES.format(ws=ws.id)}/{created['ref']}", headers=owner_headers)
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
        listed = client.get(TEMPLATES.format(ws=ws.id), headers=owner_headers).json()
        assert all(item["name"] != "已改名" for item in listed["items"])

    def test_delete_default_falls_back(self, client, ws, owner_headers):
        created = client.post(
            TEMPLATES.format(ws=ws.id), json={"name": "删默认", "preset_key": "press"}, headers=owner_headers
        ).json()
        client.put(f"{TEMPLATES.format(ws=ws.id)}/{created['ref']}", json={"is_default": True}, headers=owner_headers)
        deleted = client.delete(f"{TEMPLATES.format(ws=ws.id)}/{created['ref']}", headers=owner_headers).json()
        assert deleted["default_ref"] == DEFAULT_TEMPLATE_REF

    def test_cross_workspace_404(self, client, db, ws, owner, owner_headers):
        other = Workspace(name="外工作区", created_by_id=owner.id)
        db.add(other)
        db.commit()
        row = ExportTemplate(
            workspace_id=other.id, name="外部", config=config_to_dict(BUILTIN_TEMPLATES["press"].config)
        )
        db.add(row)
        db.commit()
        assert client.get(TEMPLATES.format(ws=ws.id) + f"/{row.id}", headers=owner_headers).status_code == 404
        assert (
            client.put(f"{TEMPLATES.format(ws=ws.id)}/{row.id}", json={"name": "x"}, headers=owner_headers).status_code
            == 404
        )

    def test_preview_docx_and_pdf(self, client, ws, owner_headers):
        docx = client.post(
            TEMPLATES.format(ws=ws.id) + "/preview",
            json={"preset_key": None, "ref": "builtin:thesis"},
            params={"format": "docx"},
            headers=owner_headers,
        )
        assert docx.status_code == 200, docx.text
        assert docx.content[:2] == b"PK"
        pdf = client.post(
            TEMPLATES.format(ws=ws.id) + "/preview",
            json={"ref": "builtin:official"},
            params={"format": "pdf"},
            headers=owner_headers,
        )
        assert pdf.status_code == 200
        assert pdf.content[:4] == b"%PDF"
        bad = client.post(
            TEMPLATES.format(ws=ws.id) + "/preview",
            json={"ref": "builtin:official"},
            params={"format": "md"},
            headers=owner_headers,
        )
        assert bad.status_code == 400

    def test_preview_invalid_config_is_400(self, client, ws, owner_headers):
        r = client.post(
            TEMPLATES.format(ws=ws.id) + "/preview",
            json={"config": {"body": {"size": 999}}},
            params={"format": "docx"},
            headers=owner_headers,
        )
        assert r.status_code == 400


class TestExportWithTemplate:
    def test_docx_uses_template_fonts(self, client, ws, owner_headers):
        doc_id = _create_doc(client, ws, owner_headers, "# 一\n\n正文\n")
        r = _export(client, ws, doc_id, owner_headers, format="docx", template="builtin:thesis")
        assert r.status_code == 200, r.text
        document = Document(io.BytesIO(r.content))
        body_run = next(
            run for paragraph in document.paragraphs if paragraph.text.startswith("正文") for run in paragraph.runs
        )
        assert body_run.font.name == "Times New Roman"
        assert body_run.font.size.pt == 12.0
        heading = next(p for p in document.paragraphs if p.text.strip().startswith("第一章"))
        assert heading.runs[0].font.size.pt == 16.0

    def test_export_without_template_uses_default_preset(self, client, ws, owner_headers):
        doc_id = _create_doc(client, ws, owner_headers, "# 一" + chr(10) + chr(10) + "正文" + chr(10))
        r = _export(client, ws, doc_id, owner_headers, format="docx")
        assert r.status_code == 200
        document = Document(io.BytesIO(r.content))
        heading = next(p for p in document.paragraphs if "一" in p.text)
        # 默认 = 研究报告：H1 黑体 16pt，且带多级编号（前缀「1 」）
        assert heading.runs[0].font.size.pt == 16.0
        assert heading.text.strip().startswith("1")

    def test_export_pdf_with_template(self, client, ws, owner_headers):
        doc_id = _create_doc(client, ws, owner_headers, "# 一\n\n正文\n")
        r = _export(client, ws, doc_id, owner_headers, format="pdf", template="builtin:official")
        assert r.status_code == 200
        assert r.content[:4] == b"%PDF"

    def test_markdown_ignores_template(self, client, ws, owner_headers):
        doc_id = _create_doc(client, ws, owner_headers, "# 一\n\n正文\n")
        r = _export(client, ws, doc_id, owner_headers, format="md", template="builtin:thesis")
        assert r.status_code == 200
        assert "正文" in r.content.decode("utf-8")

    def test_unknown_template_is_404(self, client, ws, owner_headers):
        doc_id = _create_doc(client, ws, owner_headers, "正文\n")
        assert _export(client, ws, doc_id, owner_headers, format="docx", template="builtin:nope").status_code == 404
        assert _export(client, ws, doc_id, owner_headers, format="docx", template="abc").status_code == 400


class TestDocxTemplateFeatures:
    def _docx(self, markdown: str, preset: str) -> Any:
        from cndb.plugins.documents.services.export.docx import _render_docx

        builtin = BUILTIN_TEMPLATES[preset]
        resolved = tpl.ResolvedTemplate(ref=builtin.ref, name=builtin.name, source="builtin", config=builtin.config)
        return Document(io.BytesIO(_render_docx(markdown, template=resolved)))

    def test_three_line_table_and_captions(self):
        markdown = "表：示例数据\n\n| 名称 | 数量 |\n| --- | ---: |\n| A | 1 |\n"
        document = self._docx(markdown, "thesis")
        xml = document.tables[0]._tbl.xml
        assert 'w:val="nil"' in xml  # 竖线关闭（三线表）
        texts = [p.text for p in document.paragraphs if p.text.strip()]
        assert any(text.startswith("表 1-1") for text in texts)
        assert not any(text.startswith("表：") for text in texts)

    def test_heading_numbering_and_page_footer(self):
        document = self._docx("# 一\n\n## 二\n", "official")
        texts = [p.text for p in document.paragraphs if p.text.strip()]
        assert texts[0].startswith("一、")
        assert texts[1].startswith("（一）")
        footer_xml = document.sections[0].footer.paragraphs[0]._p.xml
        # 公文页脚只有 4 号数字页码（GB/T 9704），不写「第 X 页 共 Y 页」
        assert "PAGE" in footer_xml
        assert "NUMPAGES" not in footer_xml

    def test_figure_caption_from_alt(self):
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (40, 20), (10, 20, 30)).save(buffer, format="PNG")
        data = buffer.getvalue()
        from cndb.plugins.documents.services.export.docx import _render_docx

        builtin = BUILTIN_TEMPLATES["research"]
        resolved = tpl.ResolvedTemplate(ref=builtin.ref, name=builtin.name, source="builtin", config=builtin.config)
        document = Document(
            io.BytesIO(_render_docx("![架构示意](file:x.png)", images=lambda _key: (data, "x.png"), template=resolved))
        )
        texts = [p.text for p in document.paragraphs if p.text.strip()]
        assert any(text.startswith("图 1") and "架构示意" in text for text in texts)


class TestMigration:
    def test_upgrade_and_downgrade(self, tmp_path):
        from alembic import command
        from sqlalchemy import create_engine

        from cndb.core.migrations import _build_config

        url = f"sqlite:///{(tmp_path / 'tpl.db').as_posix()}"
        cfg = _build_config(url)
        importlib.import_module("cndb.alembic.versions.b7c8d9e0f1a2_add_export_templates")
        command.upgrade(cfg, "b7c8d9e0f1a2")
        engine = create_engine(url)
        assert "documents_exporttemplate" in set(__import__("sqlalchemy").inspect(engine).get_table_names())
        # 幂等：重复 upgrade 到同一版本为空操作
        command.upgrade(cfg, "b7c8d9e0f1a2")
        assert "documents_exporttemplate" in set(__import__("sqlalchemy").inspect(engine).get_table_names())
        command.downgrade(cfg, "ea1b2c3d4e5f")
        assert "documents_exporttemplate" not in set(__import__("sqlalchemy").inspect(engine).get_table_names())


class TestBackupRoundtrip:
    def test_export_and_import(self, client, db, ws, owner, owner_headers, tmp_path):

        from cndb.plugins.workspaces.services.workspace_backup import build_workspace_backup_v17

        client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "往返模板", "preset_key": "research"},
            headers=owner_headers,
        )
        backup, files = build_workspace_backup_v17(db, ws.id, owner, rows_dir=tmp_path)
        assert backup["version"] == "17"
        assert len(backup["templates"]) == 1
        assert backup["templates"][0]["name"] == "往返模板"
        assert files is not None

        # 反向：导入到新工作区
        target = Workspace(name="恢复目标", created_by_id=owner.id)
        db.add(target)
        db.flush()
        db.add(WorkspaceMember(workspace_id=target.id, user_id=owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        from cndb.plugins.workspaces.services.backup_io import _import_export_templates

        imported, errors = _import_export_templates(target.id, backup, owner, db)
        assert imported == 1
        assert errors == []
        restored = db.query(ExportTemplate).filter(ExportTemplate.workspace_id == target.id).one()
        assert restored.name == "往返模板"
        assert restored.config["body"]["size"] == 12.0

    def test_old_backup_without_templates(self, db, ws, owner):
        from cndb.plugins.workspaces.services.backup_io import _import_export_templates

        imported, errors = _import_export_templates(ws.id, {"version": "16"}, owner, db)
        assert imported == 0
        assert errors == []

    def test_invalid_template_skipped(self, db, ws, owner):
        from cndb.plugins.workspaces.services.backup_io import _import_export_templates

        payload = {
            "templates": [
                {"name": "坏配置", "config": {"body": {"size": 999}}},
                {"name": "好配置", "config": config_to_dict(BUILTIN_TEMPLATES["press"].config), "is_default": True},
                {"name": "好配置", "config": config_to_dict(BUILTIN_TEMPLATES["press"].config)},
            ]
        }
        imported, errors = _import_export_templates(ws.id, payload, owner, db)
        assert imported == 1
        assert len(errors) == 2

    def test_manifest_counts_templates(self, db, ws, owner):
        from cndb.plugins.workspaces.services.workspace_backup import build_manifest

        manifest = build_manifest({"version": "17", "templates": [{"name": "a"}], "documents": []}, 0)
        assert manifest["stats"]["templates"] == 1


def test_export_template_row_repr(db, ws):
    row = ExportTemplate(workspace_id=ws.id, name="repr", config={})
    assert "repr" in repr(row)


def test_preview_render_sample_direct():
    assert tpl.render_sample("docx", BUILTIN_TEMPLATES["press"].config)[:2] == b"PK"
    assert tpl.render_sample("pdf", BUILTIN_TEMPLATES["press"].config)[:4] == b"%PDF"
    # 示例正文含标题 / 列表 / 表格 / 代码块，保证预览覆盖主要块型
    sample = tpl.sample_markdown()
    assert "# " in sample and "| " in sample and "```" in sample


def test_docx_archive_contains_styles():
    from cndb.plugins.documents.services.export.docx import _render_docx

    data = _render_docx(
        "# 标题\n\n正文\n",
        template=tpl.ResolvedTemplate(
            ref="builtin:thesis", name="论文", source="builtin", config=BUILTIN_TEMPLATES["thesis"].config
        ),
    )
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        styles = zf.read("word/styles.xml").decode("utf-8")
    assert "宋体" in styles or "Times New Roman" in styles


class TestBrokenTemplateFallback:
    """库里的模板配置损坏时导出必须仍能出文件（回落内置默认，不阻断主流程）."""

    def test_resolve_falls_back_to_default(self, db, ws):
        row = ExportTemplate(workspace_id=ws.id, name="坏配置", config={"body": {"size": 999}})
        db.add(row)
        db.commit()
        resolved = resolve_export_template(db, ws.id, str(row.id))
        assert resolved.ref == DEFAULT_TEMPLATE_REF
        assert resolved.config.body.size == 12.0

    def test_export_still_works_with_broken_default(self, client, db, ws, owner_headers):
        row = ExportTemplate(workspace_id=ws.id, name="坏默认", config={"body": {"size": 999}}, is_default=True)
        db.add(row)
        db.commit()
        doc_id = _create_doc(client, ws, owner_headers, "# 一" + chr(10) + chr(10) + "正文" + chr(10))
        # 未显式指定模板 → 默认模板配置非法 → 回落内置 research，仍然 200
        r = _export(client, ws, doc_id, owner_headers, format="docx")
        assert r.status_code == 200, r.text
        assert r.content[:2] == b"PK"
        # 显式指定该模板同样回落而非报错
        r2 = _export(client, ws, doc_id, owner_headers, format="docx", template=str(row.id))
        assert r2.status_code == 200, r2.text


class TestStoreBranches:
    def test_get_template_invalid_ref_is_400(self, client, ws, owner_headers):
        assert client.get(TEMPLATES.format(ws=ws.id) + "/thesis", headers=owner_headers).status_code == 400

    def test_get_template_unknown_builtin_is_404(self, client, ws, owner_headers):
        r = client.get(TEMPLATES.format(ws=ws.id) + "/builtin:nope", headers=owner_headers)
        assert r.status_code == 404

    def test_create_requires_name(self, client, ws, owner_headers):
        r = client.post(TEMPLATES.format(ws=ws.id), json={"name": "  "}, headers=owner_headers)
        assert r.status_code in (400, 422)

    def test_create_unknown_preset_is_400(self, client, ws, owner_headers):
        r = client.post(TEMPLATES.format(ws=ws.id), json={"name": "x", "preset_key": "nope"}, headers=owner_headers)
        assert r.status_code == 400

    def test_create_without_preset_uses_default(self, client, ws, owner_headers):
        created = client.post(TEMPLATES.format(ws=ws.id), json={"name": "空配置"}, headers=owner_headers).json()
        assert created["config"]["body"]["size"] == 12.0
        assert created["config"]["body"]["east_asia_font"] == "宋体"

    def test_create_with_explicit_config(self, client, ws, owner_headers):
        config = config_to_dict(BUILTIN_TEMPLATES["press"].config)
        config["body"]["size"] = 13.0
        created = client.post(
            TEMPLATES.format(ws=ws.id), json={"name": "自定义配置", "config": config}, headers=owner_headers
        )
        assert created.status_code == 201
        assert created.json()["config"]["body"]["size"] == 13.0

    def test_create_with_invalid_config_is_400(self, client, ws, owner_headers):
        r = client.post(
            TEMPLATES.format(ws=ws.id),
            json={"name": "坏", "config": {"body": {"size": 1}}},
            headers=owner_headers,
        )
        assert r.status_code == 400

    def test_update_rejects_empty_name_and_accepts_unset_default(self, client, ws, owner_headers):
        created = client.post(
            TEMPLATES.format(ws=ws.id), json={"name": "可改", "preset_key": "press"}, headers=owner_headers
        ).json()
        assert client.put(
            f"{TEMPLATES.format(ws=ws.id)}/{created['ref']}", json={"name": " "}, headers=owner_headers
        ).status_code in (400, 422)
        client.put(f"{TEMPLATES.format(ws=ws.id)}/{created['ref']}", json={"is_default": True}, headers=owner_headers)
        updated = client.put(
            f"{TEMPLATES.format(ws=ws.id)}/{created['ref']}",
            json={"is_default": False, "config": config_to_dict(BUILTIN_TEMPLATES["trend"].config)},
            headers=owner_headers,
        )
        assert updated.status_code == 200
        assert updated.json()["is_default"] is False
        assert updated.json()["config"]["numbering"]["heading"] == "arabic_multilevel"

    def test_workspace_missing_is_404(self, client, owner_headers):
        assert client.get(TEMPLATES.format(ws=999999), headers=owner_headers).status_code == 404

    def test_non_member_is_denied(self, client, db, ws, owner_headers):
        outsider = _make_user(db, "tpl_outsider")
        headers = _login(client, outsider.username)
        assert client.get(TEMPLATES.format(ws=ws.id), headers=headers).status_code == 403

    def test_helper_branches(self):
        """纯函数的边界分支（heading 回退 / 中文数字 / 计数器清零）."""
        assert tpl.builtin_template("nope") is None
        assert tpl.builtin_template("thesis") is not None
        empty = tpl.ExportTemplateConfig(headings=[])
        assert empty.heading(3).size == 18.0
        assert tpl._chinese_number(0) == "0"
        assert tpl._chinese_number(120) == "120"
        assert tpl._chinese_number(10) == "十"
        assert tpl._chinese_number(12) == "十二"
        assert tpl._chinese_number(20) == "二十"
        counters = [1, 2, 3, 0, 0, 0]
        tpl.advance_counters(counters, 2)
        assert counters == [1, 3, 0, 0, 0, 0]

    def test_partial_headings_normalized(self):
        one = validate_config({"headings": [{"size": 20.0}]})
        assert len(one.headings) == 6
        assert all(heading.size == 20.0 for heading in one.headings)


class TestPdfTemplateFeatures:
    def _pdf(self, markdown: str, preset: str, **kwargs: Any) -> bytes:
        from cndb.plugins.documents.services.export.pdf import _render_pdf

        builtin = BUILTIN_TEMPLATES[preset]
        resolved = tpl.ResolvedTemplate(ref=builtin.ref, name=builtin.name, source="builtin", config=builtin.config)
        return _render_pdf(markdown, title="模板 PDF", template=resolved, **kwargs)

    def test_full_document_with_captions_tables_and_code(self):
        from PIL import Image

        buffer = io.BytesIO()
        Image.new("RGB", (80, 40), (5, 10, 15)).save(buffer, format="PNG")
        data = buffer.getvalue()

        class _Ref:
            pass

        def resolver(_spec: Any) -> Any:
            return _Ref()

        def table_resolver(_spec: Any) -> Any:
            from cndb.plugins.documents.services.export.table_refs import ResolvedTable

            return ResolvedTable(table_name="T", header=["a", "b"], rows=[["1", "2"]], total=1)

        markdown = (
            "# 一\n\n## 二\n\n表：数据说明\n\n| 名称 | 数量 |\n| --- | ---: |\n| A | 1 |\n\n"
            "![架构示意](file:x.png)\n\n```py\nprint('中文')\n```\n\n{{table:1|width=60}}\n\n---\n\n"
            "> 引用\n\n1. 一\n   - 二\n"
        )
        out = self._pdf(markdown, "thesis", images=lambda _key: (data, "x.png"), tables=table_resolver)
        assert out.startswith(b"%PDF")

    def test_code_with_left_bar_and_missing_image(self):
        out = self._pdf("```\nx\n```\n\n![缺](file:none.png)\n", "official", images=lambda _key: None)
        assert out.startswith(b"%PDF")

    def test_page_number_page_of_total_canvas(self):
        """「第 X 页 共 Y 页」走延迟 canvas，多页文档也能落到页脚."""
        markdown = "\n\n".join(f"第 {index} 段正文" for index in range(120))
        out = self._pdf(markdown, "official")
        assert out.startswith(b"%PDF")
        assert len(__import__("re").findall(rb"/Type\s*/Page\b", out)) >= 2

    def test_a3_paper_and_chart_block(self):
        chart_markdown = (
            '```chart\n{"template":"bar","data":{"labels":["A"],"series":[{"name":"s","values":[1]}]}}\n```\n'
        )
        out = self._pdf(chart_markdown, "techreport")
        assert out.startswith(b"%PDF")
        broken = "```chart\n{不是合法JSON}\n```\n"
        assert self._pdf(broken, "techreport").startswith(b"%PDF")


class TestStoreDirect:
    """服务层直接调用：覆盖路由层不易触达的边界分支."""

    def test_direct_branches(self, db, ws, owner):
        from cndb.core.errors import BadRequestError, NotFoundError
        from cndb.plugins.documents.services import export_template_store as store

        with pytest.raises(NotFoundError):
            store.get_template(db, ws.id, " ")
        with pytest.raises(NotFoundError):
            store.get_template(db, ws.id, "builtin:nope")
        with pytest.raises(BadRequestError):
            store.create_template(db, ws.id, owner, name="  ")

        created = store.create_template(db, ws.id, owner, name="直达模板")
        assert created["source"] == "custom"
        updated = store.update_template(db, ws.id, int(created["ref"]), description="说明")
        assert updated["description"] == "说明"
        with pytest.raises(BadRequestError):
            store.update_template(db, ws.id, int(created["ref"]), name=" ")

        with pytest.raises(BadRequestError):
            store.render_preview(db, ws.id, fmt="md")
        assert store.default_ref(db, ws.id) == DEFAULT_TEMPLATE_REF

        preview = store.render_preview(db, ws.id, fmt="docx", config=config_to_dict(BUILTIN_TEMPLATES["press"].config))
        assert preview[:2] == b"PK"

        deleted = store.delete_template(db, ws.id, int(created["ref"]))
        assert deleted["was_default"] is False
