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

    def test_put_alias_matches_patch(self, client, auth_headers):
        """ADR 0177 D6：内容模板同时接受 PUT 与 PATCH，语义一致."""
        wid = _ws(client, auth_headers, "内容模板动词")
        base = API.format(wid=wid)
        created = _create(client, wid, auth_headers, "会议纪要")

        r = client.put(f"{base}/{created['id']}", json={"name": "会议纪要 PUT"}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "会议纪要 PUT"
        # 未传字段保持（PUT 与 PATCH 同口径，不做全量替换语义）
        assert r.json()["content_markdown"] == "# 标题\n\n正文"

        r = client.patch(f"{base}/{created['id']}", json={"sort_order": 7}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["sort_order"] == 7

    def test_list_envelope_has_total(self, client, auth_headers):
        """ADR 0177 C4：列表载荷统一为 {items, total}."""
        wid = _ws(client, auth_headers, "内容模板清单")
        _create(client, wid, auth_headers, "周报")
        _create(client, wid, auth_headers, "月报")
        body = client.get(API.format(wid=wid), headers=auth_headers).json()
        assert body["total"] == 2
        assert len(body["items"]) == 2

    def test_duplicate_endpoint_increments_name(self, client, auth_headers):
        """ADR 0177 C5：副本名称「原名 副本」并递增，正文 / 说明一并复制."""
        wid = _ws(client, auth_headers, "内容模板副本")
        base = API.format(wid=wid)
        source = _create(client, wid, auth_headers, "周报", content_markdown="# 周报", description="周会骨架")

        first = client.post(f"{base}/{source['id']}/duplicate", headers=auth_headers)
        assert first.status_code == 201, first.text
        assert first.json()["name"] == "周报 副本"
        assert first.json()["content_markdown"] == "# 周报"
        assert first.json()["description"] == "周会骨架"

        second = client.post(f"{base}/{source['id']}/duplicate", headers=auth_headers)
        assert second.status_code == 201, second.text
        assert second.json()["name"] == "周报 副本 2"

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


class TestBuiltinContentLibrary:
    """ADR 0185：内置库是代码常量，只读、不入库、不进备份."""

    def test_category_and_template_keys_unique(self):
        """I2：分类 key 唯一；模板 key 扁平全局唯一（跨分类也不重复）."""
        from cndb.plugins.documents.services.content_builtins import (
            BUILTIN_CONTENT_CATEGORIES,
            BUILTIN_CONTENT_TEMPLATES,
        )

        category_keys = [c.key for c in BUILTIN_CONTENT_CATEGORIES]
        assert len(category_keys) == len(set(category_keys))
        # 模板 dict 的 key 与模板自身 key 一致，天然去重；再断言等价于列表长度
        assert set(BUILTIN_CONTENT_TEMPLATES) == {t.key for t in BUILTIN_CONTENT_TEMPLATES.values()}

    def test_every_template_belongs_to_existing_category(self):
        """I2：模板 category 必须存在于分类常量."""
        from cndb.plugins.documents.services.content_builtins import (
            BUILTIN_CONTENT_CATEGORIES,
            BUILTIN_CONTENT_TEMPLATES,
        )

        categories = {c.key for c in BUILTIN_CONTENT_CATEGORIES}
        for template in BUILTIN_CONTENT_TEMPLATES.values():
            assert template.category in categories, template.key

    def test_ref_prefix_and_no_key_collision_with_export_templates(self):
        """I3：ref 恒为 `builtin:<key>`，且与导出模板内置 key 集合无交集."""
        from cndb.plugins.documents.services.content_builtins import BUILTIN_CONTENT_TEMPLATES
        from cndb.plugins.documents.services.export.templates import BUILTIN_TEMPLATES

        for key, template in BUILTIN_CONTENT_TEMPLATES.items():
            assert template.ref == f"builtin:{key}"
            assert key not in BUILTIN_TEMPLATES, f"内容模板 key 与导出模板内置 key 撞名：{key}"

    def test_content_is_portable(self):
        """I4：正文非空、不以一级标题起、不含任何动态引用."""
        from cndb.plugins.documents.services.content_builtins import (
            BUILTIN_CONTENT_TEMPLATES,
            FORBIDDEN_CONTENT_SNIPPETS,
        )

        for key, template in BUILTIN_CONTENT_TEMPLATES.items():
            body = template.content_markdown
            assert body.strip(), key
            assert body.lstrip().startswith("## "), key
            assert "\n# " not in f"\n{body}", key
            for snippet in FORBIDDEN_CONTENT_SNIPPETS:
                assert snippet not in body, f"{key} 正文含动态引用 {snippet}"

    def test_first_batch_sections(self):
        """C3：首批 6 套覆盖立项 → 执行 → 结题，章节标题可断言."""
        from cndb.plugins.documents.services.content_builtins import BUILTIN_CONTENT_TEMPLATES

        expected = {
            "research-pm.project-proposal": ["一、项目基本信息", "三、研究目标与研究内容", "六、经费预算"],
            "research-pm.project-plan": ["二、任务分解（WBS）", "三、考核指标", "四、里程碑计划"],
            "research-pm.progress-report": ["二、主要进展", "三、考核指标完成情况", "四、经费执行情况"],
            "research-pm.weekly-report": ["一、本周进展", "三、风险与阻塞", "四、下周计划"],
            "research-pm.meeting-notes": ["一、会议信息", "四、决议事项", "五、待办事项"],
            "research-pm.final-report": ["二、任务与指标完成情况", "三、主要研究成果", "四、经费决算"],
        }
        assert set(BUILTIN_CONTENT_TEMPLATES) == set(expected)
        for key, headings in expected.items():
            body = BUILTIN_CONTENT_TEMPLATES[key].content_markdown
            for heading in headings:
                assert f"## {heading}" in body, f"{key} 缺章节：{heading}"

    def test_library_follows_sort_order(self):
        """I2：接口顺序即 sort_order 顺序，前端不重排."""
        from cndb.plugins.documents.services.content_templates import list_builtin_content_templates

        library = list_builtin_content_templates()
        categories = library["categories"]
        assert [c["key"] for c in categories] == ["research-pm"]
        orders = [t["sort_order"] for t in categories[0]["templates"]]
        assert orders == sorted(orders)
        assert len(categories[0]["templates"]) == 6

    def test_api_exposes_builtin_library(self, client, auth_headers):
        """D4：`GET .../builtin` 成员可读，结构与常量一致；未被 `/{id}` 遮蔽."""
        wid = _ws(client, auth_headers, "内置库读取")
        base = API.format(wid=wid)

        r = client.get(f"{base}/builtin", headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert list(body) == ["categories"]
        category = body["categories"][0]
        assert category["key"] == "research-pm"
        assert category["name"] == "科研项目管理"
        template = category["templates"][0]
        assert template["ref"] == "builtin:research-pm.project-proposal"
        assert template["content_markdown"].startswith("## 一、项目基本信息")

    def test_builtin_route_not_shadowed_by_id_route(self, client, auth_headers):
        """回归：`/builtin` 不能被 `/{template_id}` 当成 int 解析（422）."""
        wid = _ws(client, auth_headers, "内置库路由")
        r = client.get(f"{API.format(wid=wid)}/builtin", headers=auth_headers)
        assert r.status_code == 200, r.text

    def test_custom_list_payload_unaffected(self, client, auth_headers):
        """C6：内置库不出现在自定义列表的 items / total 中."""
        wid = _ws(client, auth_headers, "内置库不影响列表")
        _create(client, wid, auth_headers, "周报")
        body = client.get(API.format(wid=wid), headers=auth_headers).json()
        assert body["total"] == 1
        assert all(item["name"] != "项目周报" for item in body["items"])

    def test_builtin_ref_is_invalid_template_id(self, client, auth_headers):
        """内置无写端点：以 `builtin:xx` 取单条按非法 id 处理（422）."""
        wid = _ws(client, auth_headers, "内置库无写路径")
        r = client.get(f"{API.format(wid=wid)}/builtin:research-pm.weekly-report", headers=auth_headers)
        assert r.status_code == 422, r.text

    def test_non_member_cannot_read_builtin(self, client, auth_headers):
        """H64：内置库同自定义列表同一门槛（成员可读）."""
        wid = _ws(client, auth_headers, "内置库私密")
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "builtin_outsider", "email": "builtin_outsider@example.com", "password": "passw0rd"},
        )
        assert r.status_code in (200, 201), r.text
        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "builtin_outsider", "password": "passw0rd"},
        )
        outsider = {"Authorization": f"Bearer {r.json()['access_token']}"}
        r = client.get(f"{API.format(wid=wid)}/builtin", headers=outsider)
        assert r.status_code in (403, 404), r.text

    def test_backup_has_no_builtin_entries(self, db, client, auth_headers, tmp_path):
        """I1：备份 `content_templates[]` 与内置库无交集."""
        from cndb.plugins.accounts.models import User
        from cndb.plugins.documents.services.content_builtins import (
            BUILTIN_CONTENT_TEMPLATES,
            builtin_content_ref,
        )
        from cndb.plugins.workspaces.services.workspace_backup import build_workspace_backup_v17

        wid = _ws(client, auth_headers, "内置库备份")
        _create(client, wid, auth_headers, "会议纪要")
        owner = db.query(User).filter(User.username == "testuser").first()
        assert owner is not None
        backup, _files = build_workspace_backup_v17(db, wid, owner, rows_dir=tmp_path)
        names = {row["name"] for row in backup["content_templates"]}
        builtin_names = {t.name for t in BUILTIN_CONTENT_TEMPLATES.values()}
        assert names == {"会议纪要"}
        assert names.isdisjoint(builtin_names)
        assert not any(str(row.get("name", "")).startswith("builtin:") for row in backup["content_templates"])
        assert builtin_content_ref("research-pm.weekly-report") not in str(backup["content_templates"])
