"""文档级排版模板绑定（ADR 0177 P3）测试.

覆盖：
- ``validate_export_template_ref``：内置 key / 本区 id 通过，未知 key / 跨区 / 非法格式拒绝；
- 解析链：显式 ref → 文档绑定 → 工作区默认 → 内置 research；绑定悬空静默回落；
- 文档 API：PATCH 设 / 清绑定、文件夹 400、建文档透传、副本复制绑定、导出走绑定；
- 内容模板：绑定字段随 CRUD、null 清除、副本继承、非法引用 400；
- 迁移：两列 upgrade / downgrade 往返；
- 备份：两处新字段导出，导入只保留 ``builtin:`` 引用。
"""

from __future__ import annotations

import io

from docx import Document
from sqlalchemy import inspect

DOCS = "/api/v1/workspaces/{wid}/documents"
TEMPLATES = "/api/v1/workspaces/{wid}/documents/templates"
CONTENT = "/api/v1/workspaces/{wid}/document-content-templates"


def _ws(client, auth, name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth)
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _template(client, wid: int, auth, name: str = "公文排版", preset: str = "official") -> str:
    r = client.post(TEMPLATES.format(wid=wid), json={"name": name, "preset_key": preset}, headers=auth)
    assert r.status_code == 201, r.text
    return str(r.json()["ref"])


def _doc(client, wid: int, auth, title: str = "排版绑定文档", content: str = "# 一\n\n正文\n") -> dict:
    r = client.post(
        DOCS.format(wid=wid),
        json={"title": title, "content": content, "status": "published"},
        headers=auth,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _export(client, wid: int, doc_id: int, auth):
    return client.get(f"{DOCS.format(wid=wid)}/{doc_id}/export", params={"format": "docx"}, headers=auth)


def _body_size(content: bytes) -> float:
    document = Document(io.BytesIO(content))
    run = next(run for paragraph in document.paragraphs if paragraph.text.startswith("正文") for run in paragraph.runs)
    return float(run.font.size.pt)


def _bind(client, wid: int, auth, doc_id: int, ref: str | None) -> dict:
    r = client.patch(DOCS.format(wid=wid) + f"/{doc_id}", json={"export_template_ref": ref}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


class TestValidateRef:
    def test_validate_accepts_builtin_and_local_id(self, client, db, auth_headers):
        from cndb.plugins.documents.services.export import (
            validate_export_template_ref as validate,
        )

        wid = _ws(client, auth_headers, "绑定校验")
        ref = _template(client, wid, auth_headers)

        assert validate(db, wid, None) is None
        assert validate(db, wid, "  ") is None
        assert validate(db, wid, "builtin:thesis") == "builtin:thesis"
        assert validate(db, wid, ref) == ref

    def test_validate_rejects_unknown_builtin_and_format(self, client, db, auth_headers):
        import pytest

        from cndb.plugins.documents.services.export import (
            validate_export_template_ref as validate,
        )

        wid = _ws(client, auth_headers, "绑定校验非法")
        with pytest.raises(ValueError):
            validate(db, wid, "builtin:nope")
        with pytest.raises(ValueError):
            validate(db, wid, "thesis")
        with pytest.raises(ValueError):
            validate(db, wid, "999999")

    def test_validate_rejects_cross_workspace_id(self, client, db, auth_headers):
        import pytest

        from cndb.plugins.documents.services.export import (
            validate_export_template_ref as validate,
        )

        wid = _ws(client, auth_headers, "绑定校验源")
        other = _ws(client, auth_headers, "绑定校验他区")
        ref = _template(client, other, auth_headers)
        with pytest.raises(ValueError):
            validate(db, wid, ref)


class TestResolveChain:
    def test_document_ref_wins_over_workspace_default(self, client, db, auth_headers):
        from cndb.plugins.documents.services.export import resolve_export_template

        wid = _ws(client, auth_headers, "绑定解析链")
        ref = _template(client, wid, auth_headers)
        client.post(TEMPLATES.format(wid=wid), json={"name": "默认模板", "preset_key": "thesis"}, headers=auth_headers)
        # 把默认设成论文，文档绑定公文
        default_row = client.get(TEMPLATES.format(wid=wid), headers=auth_headers).json()["items"]
        default_ref = next(item["ref"] for item in default_row if item["name"] == "默认模板")
        client.patch(TEMPLATES.format(wid=wid) + f"/{default_ref}", json={"is_default": True}, headers=auth_headers)

        resolved = resolve_export_template(db, wid, None, document_ref=ref)
        assert resolved.name == "公文排版"
        # 显式 ref 仍然最高优先
        assert resolve_export_template(db, wid, "builtin:thesis", document_ref=ref).name == "论文"

    def test_dangling_document_ref_falls_back(self, client, db, auth_headers):
        from cndb.plugins.documents.services.export import resolve_export_template

        wid = _ws(client, auth_headers, "绑定悬空")
        resolved = resolve_export_template(db, wid, None, document_ref="999999")
        assert resolved.ref == "builtin:research"
        resolved = resolve_export_template(db, wid, None, document_ref="builtin:nope")
        assert resolved.ref == "builtin:research"
        resolved = resolve_export_template(db, wid, None, document_ref="not-a-ref")
        assert resolved.ref == "builtin:research"


class TestDocumentBindingApi:
    def test_patch_sets_and_clears(self, client, auth_headers):
        wid = _ws(client, auth_headers, "文档绑定写")
        ref = _template(client, wid, auth_headers)
        doc = _doc(client, wid, auth_headers)

        updated = _bind(client, wid, auth_headers, doc["id"], ref)
        assert updated["export_template_ref"] == ref

        detail = client.get(DOCS.format(wid=wid) + f"/{doc['id']}", headers=auth_headers)
        assert detail.json()["export_template_ref"] == ref

        cleared = _bind(client, wid, auth_headers, doc["id"], None)
        assert cleared["export_template_ref"] is None

    def test_patch_without_field_keeps_binding(self, client, auth_headers):
        wid = _ws(client, auth_headers, "文档绑定省略")
        ref = _template(client, wid, auth_headers)
        doc = _doc(client, wid, auth_headers)
        _bind(client, wid, auth_headers, doc["id"], ref)

        r = client.patch(DOCS.format(wid=wid) + f"/{doc['id']}", json={"title": "改名"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["export_template_ref"] == ref

    def test_invalid_ref_is_400(self, client, auth_headers):
        wid = _ws(client, auth_headers, "文档绑定非法")
        doc = _doc(client, wid, auth_headers)
        r = client.patch(
            DOCS.format(wid=wid) + f"/{doc['id']}",
            json={"export_template_ref": "builtin:nope"},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text
        r = client.patch(
            DOCS.format(wid=wid) + f"/{doc['id']}",
            json={"export_template_ref": "thesis"},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text

    def test_folder_rejects_binding(self, client, auth_headers):
        wid = _ws(client, auth_headers, "文件夹绑定")
        r = client.post(
            DOCS.format(wid=wid),
            json={"title": "真文件夹", "is_folder": True},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        folder_id = r.json()["id"]
        r = client.patch(
            DOCS.format(wid=wid) + f"/{folder_id}",
            json={"export_template_ref": "builtin:thesis"},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text

    def test_create_document_accepts_binding(self, client, auth_headers):
        wid = _ws(client, auth_headers, "建文档绑定")
        ref = _template(client, wid, auth_headers)
        r = client.post(
            DOCS.format(wid=wid),
            json={"title": "带绑定", "content": "# 一", "export_template_ref": ref},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        assert r.json()["export_template_ref"] == ref

    def test_create_document_rejects_unknown_binding(self, client, auth_headers):
        wid = _ws(client, auth_headers, "建文档绑定非法")
        r = client.post(
            DOCS.format(wid=wid),
            json={"title": "坏绑定", "content": "", "export_template_ref": "builtin:nope"},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text

    def test_duplicate_copies_binding(self, client, auth_headers):
        wid = _ws(client, auth_headers, "副本绑定")
        ref = _template(client, wid, auth_headers)
        doc = _doc(client, wid, auth_headers)
        _bind(client, wid, auth_headers, doc["id"], ref)

        r = client.post(DOCS.format(wid=wid) + f"/{doc['id']}/duplicate", headers=auth_headers)
        assert r.status_code == 201, r.text
        assert r.json()["export_template_ref"] == ref

    def test_export_uses_document_binding(self, client, auth_headers):
        wid = _ws(client, auth_headers, "导出走绑定")
        ref = _template(client, wid, auth_headers)
        doc = _doc(client, wid, auth_headers)

        # 未绑定时走工作区默认（research，正文 12pt）
        assert _body_size(_export(client, wid, doc["id"], auth_headers).content) == 12.0

        _bind(client, wid, auth_headers, doc["id"], ref)
        assert _body_size(_export(client, wid, doc["id"], auth_headers).content) == 16.0

        # 显式 template 覆盖文档绑定
        r = client.get(
            f"{DOCS.format(wid=wid)}/{doc['id']}/export",
            params={"format": "docx", "template": "builtin:thesis"},
            headers=auth_headers,
        )
        assert _body_size(r.content) == 12.0

    def test_export_survives_deleted_binding_template(self, client, auth_headers):
        wid = _ws(client, auth_headers, "导出绑定已删")
        ref = _template(client, wid, auth_headers)
        doc = _doc(client, wid, auth_headers)
        _bind(client, wid, auth_headers, doc["id"], ref)
        assert client.delete(TEMPLATES.format(wid=wid) + f"/{ref}", headers=auth_headers).status_code == 200

        r = _export(client, wid, doc["id"], auth_headers)
        assert r.status_code == 200, r.text
        assert _body_size(r.content) == 12.0


class TestContentTemplateBinding:
    def test_binding_roundtrip_and_clear(self, client, auth_headers):
        wid = _ws(client, auth_headers, "内容模板绑定")
        ref = _template(client, wid, auth_headers)
        created = client.post(
            CONTENT.format(wid=wid),
            json={"name": "公文骨架", "content_markdown": "# 一", "export_template_ref": ref},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["export_template_ref"] == ref
        template_id = created.json()["id"]

        listed = client.get(CONTENT.format(wid=wid), headers=auth_headers).json()
        assert listed["items"][0]["export_template_ref"] == ref

        cleared = client.patch(
            CONTENT.format(wid=wid) + f"/{template_id}",
            json={"export_template_ref": None},
            headers=auth_headers,
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["export_template_ref"] is None

    def test_invalid_binding_is_400(self, client, auth_headers):
        wid = _ws(client, auth_headers, "内容模板绑定非法")
        r = client.post(
            CONTENT.format(wid=wid),
            json={"name": "坏绑定", "content_markdown": "", "export_template_ref": "builtin:nope"},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text

    def test_duplicate_copies_binding(self, client, auth_headers):
        wid = _ws(client, auth_headers, "内容模板副本绑定")
        ref = _template(client, wid, auth_headers)
        created = client.post(
            CONTENT.format(wid=wid),
            json={"name": "骨架", "content_markdown": "", "export_template_ref": ref},
            headers=auth_headers,
        ).json()
        dup = client.post(CONTENT.format(wid=wid) + f"/{created['id']}/duplicate", headers=auth_headers)
        assert dup.status_code == 201, dup.text
        assert dup.json()["export_template_ref"] == ref

    def test_create_document_from_template_carries_binding(self, client, auth_headers):
        wid = _ws(client, auth_headers, "从模板新建绑定")
        ref = _template(client, wid, auth_headers)
        template = client.post(
            CONTENT.format(wid=wid),
            json={"name": "周报骨架", "content_markdown": "# 周报", "export_template_ref": ref},
            headers=auth_headers,
        ).json()

        # 前端「从模板新建」：正文 + 绑定一起透传
        doc = client.post(
            DOCS.format(wid=wid),
            json={"title": "本周周报", "content": template["content_markdown"], "export_template_ref": ref},
            headers=auth_headers,
        )
        assert doc.status_code == 201, doc.text
        assert doc.json()["export_template_ref"] == ref


class TestMigration:
    def test_upgrade_and_downgrade(self, tmp_path):
        from alembic import command
        from sqlalchemy import create_engine

        from cndb.core.migrations import _build_config

        url = f"sqlite:///{(tmp_path / 'binding.db').as_posix()}"
        cfg = _build_config(url)
        command.upgrade(cfg, "e0f1a2b3c4d6")
        engine = create_engine(url)
        assert "export_template_ref" in {c["name"] for c in inspect(engine).get_columns("documents_document")}
        assert "export_template_ref" in {c["name"] for c in inspect(engine).get_columns("documents_contenttemplate")}

        command.downgrade(cfg, "d9e0f1a2b3c5")
        assert "export_template_ref" not in {c["name"] for c in inspect(engine).get_columns("documents_document")}
        assert "export_template_ref" not in {
            c["name"] for c in inspect(engine).get_columns("documents_contenttemplate")
        }


class TestBackup:
    def test_export_contains_bindings_and_import_scrubs_ids(self, client, db, auth_headers, tmp_path):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.models import ContentTemplate
        from cndb.plugins.workspaces.services.backup_io import (
            _import_content_templates,
            _restored_template_ref,
        )
        from cndb.plugins.workspaces.services.workspace_backup import build_workspace_backup_v17

        wid = _ws(client, auth_headers, "绑定备份源")
        ref = _template(client, wid, auth_headers)
        doc = _doc(client, wid, auth_headers)
        _bind(client, wid, auth_headers, doc["id"], "builtin:thesis")
        client.post(
            CONTENT.format(wid=wid),
            json={"name": "备份骨架", "content_markdown": "", "export_template_ref": ref},
            headers=auth_headers,
        )

        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        backup, _files = build_workspace_backup_v17(db, wid, owner, rows_dir=tmp_path)
        assert backup["documents"][0]["export_template_ref"] == "builtin:thesis"
        assert backup["content_templates"][0]["export_template_ref"] == ref

        # 导入端：id 型 ref 清空、builtin 保留、旧包缺键按 None
        target = _ws(client, auth_headers, "绑定备份目标")
        imported, errors = _import_content_templates(target, backup, owner, db)
        assert imported == 1, errors
        row = db.query(ContentTemplate).filter(ContentTemplate.workspace_id == target).one()
        assert row.export_template_ref is None

        payload = {
            "content_templates": [
                {"name": "保留内置", "content_markdown": "", "export_template_ref": "builtin:thesis"},
                {"name": "旧包缺键", "content_markdown": ""},
            ]
        }
        imported, errors = _import_content_templates(target, payload, owner, db)
        assert imported == 2, errors
        refs = {
            row.name: row.export_template_ref
            for row in db.query(ContentTemplate).filter(ContentTemplate.workspace_id == target).all()
        }
        assert refs["保留内置"] == "builtin:thesis"
        assert refs["旧包缺键"] is None

        assert _restored_template_ref("12") is None
        assert _restored_template_ref("builtin:") is None
        assert _restored_template_ref(None) is None
