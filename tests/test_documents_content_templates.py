"""文档内容模板（需求 0169）测试.

覆盖：CRUD API、工作区内重名 400、跨工作区 404、成员读/非成员拒绝、
备份往返（新包含 content_templates[]、旧包缺键兼容）、覆盖恢复清表、
以及「从模板新建文档」的正文解析契约。
"""

from __future__ import annotations

API = "/api/v1/workspaces/{wid}/document-content-templates"


def _ws(client, auth_headers, name: str) -> int:
    r = client.post("/api/v1/workspaces", json={"name": name}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create(client, wid: int, auth, name: str, **overrides) -> dict:
    payload = {"name": name, "content_markdown": "# 标题\n\n正文", **overrides}
    r = client.post(API.format(wid=wid), json=payload, headers=auth)
    assert r.status_code == 201, r.text
    return r.json()


class TestContentTemplatesApi:
    def test_crud_roundtrip(self, client, auth_headers):
        wid = _ws(client, auth_headers, "内容模板 CRUD")
        base = API.format(wid=wid)

        created = _create(client, wid, auth_headers, "会议纪要", description="周会", icon="📝", sort_order=3)
        assert created["workspace_id"] == wid
        assert created["content_markdown"] == "# 标题\n\n正文"

        listed = client.get(base, headers=auth_headers)
        assert listed.status_code == 200, listed.text
        assert listed.json()["total"] == 1

        detail = client.get(f"{base}/{created['id']}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["name"] == "会议纪要"

        patched = client.patch(
            f"{base}/{created['id']}",
            json={"name": "会议纪要模板", "content_markdown": "# 新模板", "sort_order": 1},
            headers=auth_headers,
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["name"] == "会议纪要模板"
        assert patched.json()["content_markdown"] == "# 新模板"
        assert patched.json()["description"] == "周会"  # 未传字段保持不变

        assert client.delete(f"{base}/{created['id']}", headers=auth_headers).status_code == 200
        assert client.get(base, headers=auth_headers).json()["total"] == 0

    def test_duplicate_name_rejected(self, client, auth_headers):
        wid = _ws(client, auth_headers, "内容模板重名")
        _create(client, wid, auth_headers, "周报")
        r = client.post(API.format(wid=wid), json={"name": "周报", "content_markdown": ""}, headers=auth_headers)
        assert r.status_code == 400, r.text

    def test_cross_workspace_is_404(self, client, auth_headers):
        wid = _ws(client, auth_headers, "模板本区")
        other = _ws(client, auth_headers, "模板他区")
        created = _create(client, wid, auth_headers, "本区模板")

        r = client.get(API.format(wid=other) + f"/{created['id']}", headers=auth_headers)
        assert r.status_code == 404, r.text
        r = client.patch(
            API.format(wid=other) + f"/{created['id']}",
            json={"name": "越权改名"},
            headers=auth_headers,
        )
        assert r.status_code == 404, r.text

    def test_non_member_cannot_read(self, client, auth_headers):
        wid = _ws(client, auth_headers, "模板私密")
        # 注册第二个用户（不加入工作区）
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "tpl_outsider", "email": "tpl_outsider@example.com", "password": "passw0rd"},
        )
        assert r.status_code in (200, 201), r.text
        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "tpl_outsider", "password": "passw0rd"},
        )
        assert r.status_code == 200, r.text
        outsider = {"Authorization": f"Bearer {r.json()['access_token']}"}

        r = client.get(API.format(wid=wid), headers=outsider)
        assert r.status_code in (403, 404), r.text

    def test_resolve_template_content_for_new_document(self, client, auth_headers, db):
        from cndb.plugins.documents.services import content_templates as svc

        wid = _ws(client, auth_headers, "模板建文档")
        created = _create(client, wid, auth_headers, "周报", content_markdown="# 周报\n\n## 本周")

        # 前端拿这段正文作为 create_document 的 content，验证解析契约
        assert svc.resolve_template_content(db, wid, created["id"]) == "# 周报\n\n## 本周"


class TestContentTemplatesBackup:
    def test_new_backup_roundtrip(self, db, client, auth_headers, tmp_path):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.models import ContentTemplate
        from cndb.plugins.workspaces.services.backup_io import _import_content_templates
        from cndb.plugins.workspaces.services.workspace_backup import build_workspace_backup_v17

        wid = _ws(client, auth_headers, "模板备份源")
        _create(client, wid, auth_headers, "会议纪要", content_markdown="# 纪要", icon="📝", sort_order=2)

        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        backup, _files = build_workspace_backup_v17(db, wid, owner, rows_dir=tmp_path)
        assert len(backup["content_templates"]) == 1
        assert backup["content_templates"][0]["name"] == "会议纪要"

        other = _ws(client, auth_headers, "模板备份目标")
        imported, errors = _import_content_templates(other, backup, owner, db)
        assert imported == 1, errors
        rows = db.query(ContentTemplate).filter(ContentTemplate.workspace_id == other).all()
        assert len(rows) == 1
        assert rows[0].content_markdown == "# 纪要"

    def test_old_backup_without_key(self, db, tmp_path):
        from cndb.plugins.accounts.models import User
        from cndb.plugins.workspaces.services.backup_io import _import_content_templates

        owner = db.query(User).filter(User.username == "testuser").first()
        imported, errors = _import_content_templates(999, {"version": "15"}, owner, db)
        assert (imported, errors) == (0, [])

    def test_restore_clears_content_templates(self, db, client, auth_headers):
        from cndb.plugins.documents.models import ContentTemplate
        from cndb.plugins.workspaces.services.workspace_restore import clear_workspace_content

        wid = _ws(client, auth_headers, "模板覆盖恢复")
        _create(client, wid, auth_headers, "待清除模板")
        assert db.query(ContentTemplate).filter(ContentTemplate.workspace_id == wid).count() == 1

        clear_workspace_content(wid, db)
        assert db.query(ContentTemplate).filter(ContentTemplate.workspace_id == wid).count() == 0
