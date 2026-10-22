"""工作区备份 / 恢复：文档、文档标签与表权限的往返校验.

验证 export 端新增的 ``document_tags`` / ``documents``（仅最新正文、含文件夹层级）
与每表 ``permission``；以及 import 端对三者的还原能力，覆盖「从备份创建新工作区」
与「导入到已存在工作区」两条路径。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

WS = "/api/v1/workspaces"
DOCS = "/api/v1/workspaces/{wid}/documents"
TAGS = "/api/v1/workspaces/{wid}/document-tags"
TABLES = "/api/v1/workspaces/{wid}/tables"


def _new_workspace(client: TestClient, headers: dict[str, str], name: str = "备份源") -> int:
    r = client.post(WS, json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_doc(client: TestClient, headers: dict[str, str], wid: int, title: str, **overrides) -> dict:
    r = client.post(DOCS.format(wid=wid), json={"title": title, "content": "", **overrides}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _create_tag(client: TestClient, headers: dict[str, str], wid: int, name: str, color: str = "#FF5500") -> dict:
    r = client.post(TAGS.format(wid=wid), json={"name": name, "color": color}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _seed_source(client: TestClient, headers: dict[str, str]) -> tuple[int, dict]:
    """构造含「表+权限、标签、文档树」的源工作区，返回 (wid, 备份载荷)."""
    wid = _new_workspace(client, headers)

    # 表 + 字段 + 行 + 表权限
    r = client.post(TABLES.format(wid=wid), json={"name": "客户表", "description": ""}, headers=headers)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.post(
        f"{TABLES.format(wid=wid)}/{tid}/fields",
        json={"name": "名称", "field_type": "text", "order": 0},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    r = client.post(f"{TABLES.format(wid=wid)}/{tid}/records", json={"values": {"名称": "甲公司"}}, headers=headers)
    assert r.status_code in (200, 201), r.text
    r = client.put(
        f"{TABLES.format(wid=wid)}/{tid}/permissions",
        json={"read_role": "editor", "hidden_fields": {"viewer": ["名称"]}},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text

    # 文档：标签 + 文件夹 + 子文档 + 根文档
    tag = _create_tag(client, headers, wid, "重要")
    folder = _create_doc(client, headers, wid, "资料夹", is_folder=True)
    _create_doc(
        client,
        headers,
        wid,
        "子文档",
        parent_id=folder["id"],
        content="# 子文档\n\n正文内容 ABC\n",
        status="published",
        tag_ids=[tag["id"]],
    )
    _create_doc(client, headers, wid, "根文档", content="# 根文档\n\n根正文\n")

    backup = client.get(f"{WS}/{wid}/export", headers=headers).json()
    assert backup["version"] == "6"
    return wid, backup


class TestExportCarriesDocumentsAndConfig:
    def test_export_payload_has_documents_tags_and_permission(self, client, auth_headers):
        _wid, backup = _seed_source(client, auth_headers)

        # 文档标签
        assert len(backup["document_tags"]) == 1
        tag = backup["document_tags"][0]
        assert (tag["name"], tag["color"], tag["description"]) == ("重要", "#FF5500", "")

        # 文档树（文件夹 / 正文 / 状态 / 父子 / 标签关联）
        docs = {d["title"]: d for d in backup["documents"]}
        assert set(docs) == {"资料夹", "子文档", "根文档"}
        assert docs["资料夹"]["is_folder"] is True and docs["资料夹"]["content"] == ""
        assert docs["子文档"]["content"] == "# 子文档\n\n正文内容 ABC\n"
        assert docs["子文档"]["status"] == "published"
        assert docs["子文档"]["tag_ids"] == [tag["id"]]
        assert docs["子文档"]["parent_id"] == docs["资料夹"]["id"]

        # 表权限
        table = backup["tables"][0]
        assert table["permission"]["read_role"] == "editor"
        assert table["permission"]["hidden_fields"] == {"viewer": ["名称"]}

    def test_export_excludes_soft_deleted_documents(self, client, auth_headers):
        wid = _new_workspace(client, auth_headers)
        doc = _create_doc(client, auth_headers, wid, "待删除", content="正文\n")
        r = client.delete(f"{DOCS.format(wid=wid)}/{doc['id']}", headers=auth_headers)
        assert r.status_code == 200, r.text

        backup = client.get(f"{WS}/{wid}/export", headers=auth_headers).json()
        assert backup["documents"] == []


class TestRestoreDocumentsAndConfig:
    def test_create_workspace_from_backup_restores_all(self, client, auth_headers):
        src_wid, backup = _seed_source(client, auth_headers)
        src_tag_id = backup["document_tags"][0]["id"]

        r = client.post(f"{WS}/import", json={"json_data": backup}, headers=auth_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["errors"] == []
        assert body["imported_documents"] == 3
        new_wid = body["workspace"]["id"]
        assert new_wid != src_wid

        # 文档树还原：标题集合、文件夹标记、父子层级
        listing = client.get(DOCS.format(wid=new_wid), headers=auth_headers).json()
        restored = {d["title"]: d for d in listing["items"]}
        assert set(restored) == {"资料夹", "子文档", "根文档"}
        assert restored["资料夹"]["is_folder"] is True
        assert restored["子文档"]["parent_id"] == restored["资料夹"]["id"]
        assert restored["子文档"]["status"] == "published"

        # 子文档正文还原
        c = client.get(f"{DOCS.format(wid=new_wid)}/{restored['子文档']['id']}/content", headers=auth_headers)
        assert c.status_code == 200, c.text
        assert c.json()["content"] == "# 子文档\n\n正文内容 ABC\n"

        # 文档标签还原：同名同色、计数正确、自身 id 与源不同（跨工作区重建）
        tags = client.get(TAGS.format(wid=new_wid), headers=auth_headers).json()["items"]
        assert [t["name"] for t in tags] == ["重要"]
        assert tags[0]["color"] == "#FF5500"
        assert tags[0]["doc_count"] == 1
        assert tags[0]["id"] != src_tag_id
        assert restored["子文档"]["tag_ids"] == [tags[0]["id"]]

        # 表权限还原：重导出后比对
        re_export = client.get(f"{WS}/{new_wid}/export", headers=auth_headers).json()
        assert re_export["tables"][0]["permission"]["read_role"] == "editor"
        assert re_export["tables"][0]["permission"]["hidden_fields"] == {"viewer": ["名称"]}

    def test_import_into_existing_workspace_restores_documents(self, client, auth_headers):
        _src_wid, backup = _seed_source(client, auth_headers)
        target = _new_workspace(client, auth_headers, "目标工作区")

        r = client.post(f"{WS}/{target}/import", json={"json_data": backup}, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["errors"] == []
        assert body["imported_documents"] == 3

        listing = client.get(DOCS.format(wid=target), headers=auth_headers).json()
        assert {d["title"] for d in listing["items"]} == {"资料夹", "子文档", "根文档"}

    def test_import_twice_into_same_workspace_reuses_tags(self, client, auth_headers):
        """重复导入同一备份：同名标签复用（无唯一键冲突），文档再次导入为副本."""
        _src_wid, backup = _seed_source(client, auth_headers)
        target = _new_workspace(client, auth_headers, "重复导入目标")

        r1 = client.post(f"{WS}/{target}/import", json={"json_data": backup}, headers=auth_headers)
        assert r1.status_code == 200, r1.text
        assert r1.json()["errors"] == []
        assert r1.json()["imported_documents"] == 3

        r2 = client.post(f"{WS}/{target}/import", json={"json_data": backup}, headers=auth_headers)
        assert r2.status_code == 200, r2.text
        assert r2.json()["errors"] == []
        assert r2.json()["imported_documents"] == 3

        tags = client.get(TAGS.format(wid=target), headers=auth_headers).json()["items"]
        assert [t["name"] for t in tags] == ["重要"]
