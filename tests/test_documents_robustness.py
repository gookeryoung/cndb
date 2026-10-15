"""documents 插件功能与健壮性专项测试：外存版本 / 回收站 / 断链 / 检索容错 / N+1.

覆盖本轮迭代（iter-35）的回归点：
- 外存（>2MB）多版本内容串档：历史版本必须读到各自文件
- 外存/内联压缩内容缺失或损坏时的降级读取（不再 500）
- 软删除 → 回收站 → 恢复 → 彻底删除的完整生命周期与删除批次语义
- 标签 doc_count 与删除/恢复/彻底删除保持一致
- 出链解析（``[[标题]]`` 命中与断链）
- FTS5 非法查询输入收敛为 400 而非 500
- 列表/树的批量序列化不再逐文档查版本数/标签（N+1）
"""

from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import event, func, select

from cndb.plugins.documents.models import Document, DocumentShare, DocumentTag, DocumentVersion
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services.search import escape_query

API = "/api/v1/workspaces/{wid}/documents"
TAG_API = "/api/v1/workspaces/{wid}/document-tags"
SHARE_API = "/api/v1/documents/share"

# 略高于外存阈值（>2MB 落文件系统），内容高度重复以便 gzip 快速
BIG_SIZE = content_service.EXTERNAL_MIN_SIZE + 4096


@pytest.fixture
def workspace_id(client, auth_headers) -> int:
    r = client.post("/api/v1/workspaces", json={"name": "docs-robust-ws"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def doc_api(workspace_id: int) -> str:
    return API.format(wid=workspace_id)


@pytest.fixture
def docs_dir(monkeypatch, tmp_path):
    """把外存根目录重定向到临时目录，避免污染真实用户数据目录."""
    target = tmp_path / "docs"
    monkeypatch.setattr(content_service, "_DOCS_DIR", target)
    return target


def _create_doc(client, doc_api, auth_headers, **overrides) -> dict:
    payload = {"title": "测试文档", "content": "# 标题\n\n正文\n", **overrides}
    r = client.post(doc_api, json=payload, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()


def _get_content(client, doc_api, auth_headers, doc_id: int) -> dict:
    r = client.get(f"{doc_api}/{doc_id}/content", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def _delete(client, doc_api, auth_headers, doc_id: int):
    r = client.delete(f"{doc_api}/{doc_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r


# ── 外存内容存储 ──


class TestExternalContentStorage:
    def test_version_history_does_not_crosstalk(self, client, doc_api, auth_headers, docs_dir):
        """回归：>2MB 文档 v1 曾读到 v2 内容（doc.content_path 被覆盖）."""
        first = "A" * BIG_SIZE
        second = "B" * BIG_SIZE
        doc = _create_doc(client, doc_api, auth_headers, title="外存文档", content=first)
        doc_dir = docs_dir / str(doc["id"])
        assert (doc_dir / "v1.md.gz").is_file()

        r = client.put(f"{doc_api}/{doc['id']}/content", json={"content": second}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert (doc_dir / "v2.md.gz").is_file()

        assert client.get(f"{doc_api}/{doc['id']}/versions/1", headers=auth_headers).json()["content"] == first
        assert client.get(f"{doc_api}/{doc['id']}/versions/2", headers=auth_headers).json()["content"] == second
        assert _get_content(client, doc_api, auth_headers, doc["id"])["content"] == second

    def test_rollback_restores_external_target_version(self, client, doc_api, auth_headers, docs_dir):
        first = "A" * BIG_SIZE
        doc = _create_doc(client, doc_api, auth_headers, title="外存回滚", content=first)
        r = client.put(
            f"{doc_api}/{doc['id']}/content",
            json={"content": "B" * BIG_SIZE},
            headers=auth_headers,
        )
        assert r.status_code == 200
        r = client.post(f"{doc_api}/{doc['id']}/rollback", json={"target_version": 1}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert _get_content(client, doc_api, auth_headers, doc["id"])["content"] == first

    def test_missing_external_file_degrades_to_empty(self, client, doc_api, auth_headers, docs_dir):
        doc = _create_doc(client, doc_api, auth_headers, title="丢文件", content="A" * BIG_SIZE)
        (docs_dir / str(doc["id"]) / "v1.md.gz").unlink()
        data = _get_content(client, doc_api, auth_headers, doc["id"])
        assert data["content"] == ""

    def test_corrupt_external_file_degrades_to_empty(self, client, doc_api, auth_headers, docs_dir):
        doc = _create_doc(client, doc_api, auth_headers, title="坏文件", content="A" * BIG_SIZE)
        (docs_dir / str(doc["id"]) / "v1.md.gz").write_bytes(b"not-a-gzip-stream")
        assert _get_content(client, doc_api, auth_headers, doc["id"])["content"] == ""
        # 版本详情同样降级而非 500
        r = client.get(f"{doc_api}/{doc['id']}/versions/1", headers=auth_headers)
        assert r.status_code == 200 and r.json()["content"] == ""

    def test_legacy_content_path_fallback(self, client, doc_api, auth_headers, docs_dir, db):
        """历史文件被搬到非标准位置但文件名仍是 v{n}.md.gz → 仍可读取."""
        first = "A" * BIG_SIZE
        doc = _create_doc(client, doc_api, auth_headers, title="迁移路径", content=first)
        moved_dir = docs_dir / "relocated"
        moved_dir.mkdir(parents=True)
        moved = moved_dir / "v1.md.gz"
        (docs_dir / str(doc["id"]) / "v1.md.gz").rename(moved)
        row = db.get(Document, doc["id"])
        row.content_path = str(moved)
        db.commit()

        assert _get_content(client, doc_api, auth_headers, doc["id"])["content"] == first

    def test_legacy_path_name_mismatch_ignored(self, client, doc_api, auth_headers, docs_dir, db):
        """冗余路径文件名与版本号不符时不得当作本版本内容（防再次串档）."""
        first = "A" * BIG_SIZE
        doc = _create_doc(client, doc_api, auth_headers, title="错配路径", content=first)
        doc_dir = docs_dir / str(doc["id"])
        (doc_dir / "v1.md.gz").unlink()
        decoy = doc_dir / "v9.md.gz"
        decoy.write_bytes(b"decoy")
        row = db.get(Document, doc["id"])
        row.content_path = str(decoy)
        db.commit()

        assert _get_content(client, doc_api, auth_headers, doc["id"])["content"] == ""

    def test_inline_compressed_roundtrip(self, docs_dir):
        """50KB~2MB 区间内联 gzip+base64 存储可无损读取."""
        text = "中" * (content_service.INLINE_MAX_SIZE // 3 + 100)
        stored = content_service._store_content_bytes(Document(id=4242), 1, text, len(text.encode("utf-8")))
        assert stored.startswith("gz:")
        assert content_service._decode_inline_compressed(stored) == text

    def test_inline_compressed_corrupt_degrades(self, docs_dir):
        assert content_service._decode_inline_compressed("gz:!!!not-base64!!!") == ""

    def test_load_content_none_version(self, docs_dir):
        assert content_service.load_content(None, Document(id=1)) == ""


# ── 回收站生命周期 ──


class TestTrashLifecycle:
    def test_delete_trash_restore_roundtrip(self, client, doc_api, auth_headers):
        doc = _create_doc(client, doc_api, auth_headers, title="待删文档")
        _delete(client, doc_api, auth_headers, doc["id"])

        trash = client.get(f"{doc_api}/trash", headers=auth_headers).json()
        assert trash["total"] == 1
        item = trash["items"][0]
        assert item["id"] == doc["id"]
        assert item["deleted_at"] and item["deleted_by_id"]

        assert client.get(doc_api, headers=auth_headers).json()["total"] == 0
        assert client.get(f"{doc_api}/{doc['id']}", headers=auth_headers).status_code == 404

        r = client.post(f"{doc_api}/{doc['id']}/restore", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["restored_count"] == 1
        assert r.json()["reparented_to_root"] is False
        assert client.get(f"{doc_api}/trash", headers=auth_headers).json()["total"] == 0
        assert client.get(doc_api, headers=auth_headers).json()["total"] == 1

    def test_folder_cascade_delete_and_same_batch_restore(self, client, doc_api, auth_headers):
        folder = _create_doc(client, doc_api, auth_headers, title="上级目录", is_folder=True)
        sub = _create_doc(client, doc_api, auth_headers, title="子目录", is_folder=True, parent_id=folder["id"])
        _create_doc(client, doc_api, auth_headers, title="叶子文档", parent_id=sub["id"])

        _delete(client, doc_api, auth_headers, folder["id"])
        assert client.get(f"{doc_api}/trash", headers=auth_headers).json()["total"] == 3

        r = client.post(f"{doc_api}/{folder['id']}/restore", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["restored_count"] == 3
        assert client.get(f"{doc_api}/trash", headers=auth_headers).json()["total"] == 0
        assert client.get(doc_api, headers=auth_headers).json()["total"] == 3

    def test_independent_delete_not_resurrected(self, client, doc_api, auth_headers):
        folder = _create_doc(client, doc_api, auth_headers, title="父目录", is_folder=True)
        kept = _create_doc(client, doc_api, auth_headers, title="先删的子项", parent_id=folder["id"])
        _create_doc(client, doc_api, auth_headers, title="随父删除的子项", parent_id=folder["id"])

        _delete(client, doc_api, auth_headers, kept["id"])  # 独立删除批次
        _delete(client, doc_api, auth_headers, folder["id"])
        assert client.get(f"{doc_api}/trash", headers=auth_headers).json()["total"] == 3

        r = client.post(f"{doc_api}/{folder['id']}/restore", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["restored_count"] == 2  # 父目录 + 随父删除的子项
        trash = client.get(f"{doc_api}/trash", headers=auth_headers).json()
        assert trash["total"] == 1
        assert trash["items"][0]["id"] == kept["id"]

    def test_restore_reparents_when_parent_still_deleted(self, client, doc_api, auth_headers):
        folder = _create_doc(client, doc_api, auth_headers, title="仍在回收站的父目录", is_folder=True)
        child = _create_doc(client, doc_api, auth_headers, title="子项", parent_id=folder["id"])

        _delete(client, doc_api, auth_headers, child["id"])
        _delete(client, doc_api, auth_headers, folder["id"])
        r = client.post(f"{doc_api}/{child['id']}/restore", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["reparented_to_root"] is True
        assert r.json()["parent_id"] is None
        assert client.get(doc_api, headers=auth_headers).json()["total"] == 1

    def test_restore_non_deleted_document_404(self, client, doc_api, auth_headers):
        doc = _create_doc(client, doc_api, auth_headers)
        assert client.post(f"{doc_api}/{doc['id']}/restore", headers=auth_headers).status_code == 404

    def test_legacy_rows_without_deleted_at_restore_subtree(self, client, doc_api, auth_headers, db):
        """迁移前删除的历史数据 deleted_at 为空 → 按整棵子树宽松恢复."""
        folder = _create_doc(client, doc_api, auth_headers, title="历史目录", is_folder=True)
        _create_doc(client, doc_api, auth_headers, title="历史子项", parent_id=folder["id"])
        _delete(client, doc_api, auth_headers, folder["id"])

        for row in db.execute(select(Document).where(Document.is_deleted == True)).scalars():  # noqa: E712
            row.deleted_at = None
        db.commit()

        r = client.post(f"{doc_api}/{folder['id']}/restore", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["restored_count"] == 2

    def test_trash_pagination(self, client, doc_api, auth_headers):
        ids = [_create_doc(client, doc_api, auth_headers, title=f"删除-{i}")["id"] for i in range(3)]
        for doc_id in ids:
            _delete(client, doc_api, auth_headers, doc_id)
        r = client.get(f"{doc_api}/trash", params={"limit": 2, "offset": 0}, headers=auth_headers)
        assert r.json()["total"] == 3
        assert len(r.json()["items"]) == 2


# ── 彻底删除 ──


class TestPurge:
    def test_purge_requires_deleted_first(self, client, doc_api, auth_headers):
        doc = _create_doc(client, doc_api, auth_headers)
        r = client.delete(f"{doc_api}/{doc['id']}/purge", headers=auth_headers)
        assert r.status_code == 409

    def test_purge_cleans_rows_versions_share_tags_and_fts(self, client, workspace_id, doc_api, auth_headers, db):
        doc = _create_doc(
            client, doc_api, auth_headers, title="彻底删除", content="purge-token-unique", status="published"
        )
        share = client.post(f"{doc_api}/{doc['id']}/share", json={"permission": "viewer"}, headers=auth_headers).json()
        tag = client.post(TAG_API.format(wid=workspace_id), json={"name": "purge-tag"}, headers=auth_headers).json()
        client.post(f"{doc_api}/{doc['id']}/tags", json={"tag_ids": [tag["id"]]}, headers=auth_headers)
        _delete(client, doc_api, auth_headers, doc["id"])

        r = client.delete(f"{doc_api}/{doc['id']}/purge", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["purged_count"] == 1

        doc_id = doc["id"]
        assert db.execute(select(func.count()).select_from(Document).where(Document.id == doc_id)).scalar_one() == 0
        assert db.execute(select(func.count()).where(DocumentVersion.document_id == doc_id)).scalar_one() == 0
        assert db.execute(select(func.count()).where(DocumentShare.document_id == doc_id)).scalar_one() == 0
        assert db.execute(select(func.count()).where(DocumentTag.document_id == doc_id)).scalar_one() == 0
        # 公开分享随之失效、FTS 不再命中
        assert client.get(f"{SHARE_API}/{share['token']}").status_code == 404
        assert (
            client.get(f"{doc_api}/search", params={"q": "purge-token-unique"}, headers=auth_headers).json()["total"]
            == 0
        )

    def test_purge_folder_removes_subtree(self, client, doc_api, auth_headers, db):
        folder = _create_doc(client, doc_api, auth_headers, title="待彻底删除目录", is_folder=True)
        child = _create_doc(client, doc_api, auth_headers, title="子项", parent_id=folder["id"])
        _delete(client, doc_api, auth_headers, folder["id"])

        r = client.delete(f"{doc_api}/{folder['id']}/purge", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["purged_count"] == 2
        assert db.execute(select(func.count()).where(Document.id.in_([folder["id"], child["id"]]))).scalar_one() == 0
        assert client.get(f"{doc_api}/trash", headers=auth_headers).json()["total"] == 0

    def test_purge_removes_external_files(self, client, doc_api, auth_headers, docs_dir):
        doc = _create_doc(client, doc_api, auth_headers, title="外存彻底删除", content="A" * BIG_SIZE)
        doc_dir = docs_dir / str(doc["id"])
        assert doc_dir.is_dir()
        _delete(client, doc_api, auth_headers, doc["id"])

        r = client.delete(f"{doc_api}/{doc['id']}/purge", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["files_removed"] == 1
        assert not doc_dir.exists()

    def test_purge_detaches_live_child(self, client, doc_api, auth_headers, db):
        """异常状态防御：文件夹处于删除态但子项存活 → 子项挂根而非被销毁."""
        folder = _create_doc(client, doc_api, auth_headers, title="脏状态目录", is_folder=True)
        child = _create_doc(client, doc_api, auth_headers, title="存活子项", parent_id=folder["id"])
        row = db.get(Document, folder["id"])
        row.is_deleted = True
        row.deleted_at = dt.datetime.now(dt.UTC)
        db.commit()

        r = client.delete(f"{doc_api}/{folder['id']}/purge", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["detached"] == 1
        child_row = db.get(Document, child["id"])
        assert child_row.is_deleted is False
        assert child_row.parent_id is None

    def test_viewer_cannot_restore_or_purge(self, client, workspace_id, doc_api, auth_headers):
        client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "doc-viewer", "email": "docviewer@example.com", "password": "passw0rd"},
        )
        login = client.post("/api/v1/accounts/auth/login", json={"login": "doc-viewer", "password": "passw0rd"}).json()
        viewer_headers = {"Authorization": f"Bearer {login['access_token']}"}
        r = client.post(
            f"/api/v1/workspaces/{workspace_id}/members",
            json={"username": "doc-viewer", "role": "viewer"},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text

        doc = _create_doc(client, doc_api, auth_headers, title="查看者无权")
        _delete(client, doc_api, auth_headers, doc["id"])

        # 查看者可读回收站
        assert client.get(f"{doc_api}/trash", headers=viewer_headers).status_code == 200
        assert client.post(f"{doc_api}/{doc['id']}/restore", headers=viewer_headers).status_code == 403
        # 彻底删除不可逆：先判可见性 → 看不见的（他人草稿）返回 404（不泄露存在性）
        assert client.delete(f"{doc_api}/{doc['id']}/purge", headers=viewer_headers).status_code == 404


# ── 数据一致性 / 性能 ──


class TestDataConsistency:
    def test_tag_count_refreshed_across_delete_restore_purge(self, client, workspace_id, doc_api, auth_headers):
        tag_api = TAG_API.format(wid=workspace_id)
        tag = client.post(tag_api, json={"name": "计数标签"}, headers=auth_headers).json()
        folder = _create_doc(client, doc_api, auth_headers, title="计数目录", is_folder=True)
        child = _create_doc(client, doc_api, auth_headers, title="计数子项", parent_id=folder["id"])
        client.post(f"{doc_api}/{child['id']}/tags", json={"tag_ids": [tag["id"]]}, headers=auth_headers)
        assert client.get(tag_api, headers=auth_headers).json()["items"][0]["doc_count"] == 1

        _delete(client, doc_api, auth_headers, folder["id"])
        assert client.get(tag_api, headers=auth_headers).json()["items"][0]["doc_count"] == 0

        client.post(f"{doc_api}/{folder['id']}/restore", headers=auth_headers)
        assert client.get(tag_api, headers=auth_headers).json()["items"][0]["doc_count"] == 1

        _delete(client, doc_api, auth_headers, folder["id"])
        client.delete(f"{doc_api}/{folder['id']}/purge", headers=auth_headers)
        assert client.get(tag_api, headers=auth_headers).json()["items"][0]["doc_count"] == 0

    def test_delete_survives_parent_cycle(self, client, doc_api, auth_headers, db):
        """脏数据形成父子环时删除不得无限递归."""
        a = _create_doc(client, doc_api, auth_headers, title="环A", is_folder=True)
        b = _create_doc(client, doc_api, auth_headers, title="环B", is_folder=True)
        row_a = db.get(Document, a["id"])
        row_b = db.get(Document, b["id"])
        row_a.parent_id = b["id"]
        row_b.parent_id = a["id"]
        db.commit()

        r = client.delete(f"{doc_api}/{a['id']}", headers=auth_headers)
        assert r.status_code == 200
        assert client.get(f"{doc_api}/trash", headers=auth_headers).json()["total"] == 2

    def test_tree_serialization_is_batched(self, client, workspace_id, doc_api, auth_headers, db_engine):
        """列表/树不再逐文档查版本数与标签（N+1 回归）."""
        tag = client.post(TAG_API.format(wid=workspace_id), json={"name": "批量标签"}, headers=auth_headers).json()
        ids: list[int] = []
        for index in range(5):
            doc = _create_doc(client, doc_api, auth_headers, title=f"批量-{index}", content=f"内容 {index}")
            ids.append(doc["id"])
            client.post(f"{doc_api}/{doc['id']}/tags", json={"tag_ids": [tag["id"]]}, headers=auth_headers)
        for doc_id in ids[:2]:
            full = _get_content(client, doc_api, auth_headers, doc_id)
            client.put(
                f"{doc_api}/{doc_id}/content",
                json={"content": "更新后的内容", "base_updated_at": full["updated_at"]},
                headers=auth_headers,
            )

        statements: list[str] = []

        def _record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)

        event.listen(db_engine, "before_cursor_execute", _record)
        try:
            r = client.get(f"{doc_api}/tree", headers=auth_headers)
        finally:
            event.remove(db_engine, "before_cursor_execute", _record)

        items = r.json()["items"]
        assert len(items) == 5
        by_id = {item["id"]: item for item in items}
        assert by_id[ids[0]]["version_count"] == 2
        assert by_id[ids[2]]["version_count"] == 1
        assert all(item["tag_ids"] == [tag["id"]] for item in items)

        version_queries = [s for s in statements if "documents_documentversion" in s and "count" in s.lower()]
        tag_queries = [s for s in statements if "documents_documenttag" in s]
        assert len(version_queries) <= 1, statements
        assert len(tag_queries) <= 1, statements

    def test_list_batch_serialization_matches_single(self, client, doc_api, auth_headers):
        doc = _create_doc(client, doc_api, auth_headers, title="一致性")
        listed = client.get(doc_api, headers=auth_headers).json()["items"][0]
        detail = client.get(f"{doc_api}/{doc['id']}", headers=auth_headers).json()
        assert listed["version_count"] == detail["version_count"] == 1
        assert listed["tag_ids"] == detail["tag_ids"] == []


# ── 出链解析 ──


class TestOutgoingLinks:
    def test_resolve_hits_and_broken(self, client, doc_api, auth_headers):
        target = _create_doc(client, doc_api, auth_headers, title="目标文档")
        folder = _create_doc(client, doc_api, auth_headers, title="目录A", is_folder=True)
        src = _create_doc(
            client,
            doc_api,
            auth_headers,
            title="来源文档",
            content="见 [[目标文档]]、[[目录A]]，还有 [[不存在]]。\n",
        )
        r = client.get(f"{doc_api}/{src['id']}/links", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 3
        assert data["broken"] == 1
        by_title = {item["title"]: item for item in data["items"]}
        assert by_title["目标文档"]["document_id"] == target["id"]
        assert by_title["目标文档"]["exists"] is True
        assert by_title["目录A"]["document_id"] == folder["id"]
        assert by_title["不存在"] == {"title": "不存在", "document_id": None, "exists": False, "broken": True}

    def test_code_fence_links_ignored(self, client, doc_api, auth_headers):
        _create_doc(client, doc_api, auth_headers, title="真链接")
        src = _create_doc(
            client,
            doc_api,
            auth_headers,
            title="带代码块",
            content="```\n[[真链接]]\n```\n\n正文 [[真链接]]\n",
        )
        data = client.get(f"{doc_api}/{src['id']}/links", headers=auth_headers).json()
        assert data["total"] == 1
        assert data["broken"] == 0

    def test_self_link_and_no_links(self, client, doc_api, auth_headers):
        self_ref = _create_doc(client, doc_api, auth_headers, title="自链文档", content="引用 [[自链文档]]\n")
        data = client.get(f"{doc_api}/{self_ref['id']}/links", headers=auth_headers).json()
        assert data["items"][0]["document_id"] == self_ref["id"]

        plain = _create_doc(client, doc_api, auth_headers, title="无链接", content="纯正文")
        data = client.get(f"{doc_api}/{plain['id']}/links", headers=auth_headers).json()
        assert data == {"items": [], "total": 0, "broken": 0}


# ── 断链修复 ──


class TestLinkRepair:
    def test_repair_broken_link_creates_version(self, client, doc_api, auth_headers):
        target = _create_doc(client, doc_api, auth_headers, title="正确标题")
        src = _create_doc(client, doc_api, auth_headers, title="来源文档", content="见 [[错标题]] 与 [[无此文档]]。\n")

        r = client.post(
            f"{doc_api}/{src['id']}/links/repair",
            json={"repairs": [{"title": "错标题", "target_document_id": target["id"]}]},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["replaced"] == 1
        assert data["version_number"] == 2
        assert data["repaired"][0]["new_title"] == "正确标题"

        content = _get_content(client, doc_api, auth_headers, src["id"])["content"]
        assert "[[正确标题]]" in content and "[[错标题]]" not in content
        assert "[[无此文档]]" in content  # 未请求修复的断链保持原样

        links = client.get(f"{doc_api}/{src['id']}/links", headers=auth_headers).json()
        assert links["total"] == 2 and links["broken"] == 1
        assert {item["title"] for item in links["items"] if item["exists"]} == {"正确标题"}

    def test_repair_multiple_links_in_one_request(self, client, doc_api, auth_headers):
        first = _create_doc(client, doc_api, auth_headers, title="甲目标")
        second = _create_doc(client, doc_api, auth_headers, title="乙目标")
        src = _create_doc(client, doc_api, auth_headers, title="多链接", content="[[旧甲]] 与 [[旧乙]]\n")

        r = client.post(
            f"{doc_api}/{src['id']}/links/repair",
            json={
                "repairs": [
                    {"title": "旧甲", "target_document_id": first["id"]},
                    {"title": "旧乙", "target_document_id": second["id"]},
                ]
            },
            headers=auth_headers,
        )
        assert r.status_code == 200
        assert r.json()["replaced"] == 2
        content = _get_content(client, doc_api, auth_headers, src["id"])["content"]
        assert "[[甲目标]]" in content and "[[乙目标]]" in content

    def test_repeated_repair_returns_409(self, client, doc_api, auth_headers):
        target = _create_doc(client, doc_api, auth_headers, title="目标")
        src = _create_doc(client, doc_api, auth_headers, title="来源", content="[[旧名]]\n")
        payload = {"repairs": [{"title": "旧名", "target_document_id": target["id"]}]}
        assert client.post(f"{doc_api}/{src['id']}/links/repair", json=payload, headers=auth_headers).status_code == 200

        r = client.post(f"{doc_api}/{src['id']}/links/repair", json=payload, headers=auth_headers)
        assert r.status_code == 409
        assert r.json()["code"] == "no_link_repaired"

    def test_repair_same_title_is_noop_409(self, client, doc_api, auth_headers):
        target = _create_doc(client, doc_api, auth_headers, title="同名文档")
        src = _create_doc(client, doc_api, auth_headers, title="来源", content="[[同名文档]]\n")
        r = client.post(
            f"{doc_api}/{src['id']}/links/repair",
            json={"repairs": [{"title": "同名文档", "target_document_id": target["id"]}]},
            headers=auth_headers,
        )
        assert r.status_code == 409

    def test_repair_unknown_target_404(self, client, doc_api, auth_headers):
        src = _create_doc(client, doc_api, auth_headers, title="来源", content="[[旧名]]\n")
        r = client.post(
            f"{doc_api}/{src['id']}/links/repair",
            json={"repairs": [{"title": "旧名", "target_document_id": 999999}]},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_repair_cross_workspace_target_404(self, client, doc_api, auth_headers, workspace_id):
        other = client.post("/api/v1/workspaces", json={"name": "其它工作区"}, headers=auth_headers).json()
        foreign = client.post(
            API.format(wid=other["id"]), json={"title": "外部目标", "content": "x"}, headers=auth_headers
        ).json()
        src = _create_doc(client, doc_api, auth_headers, title="来源", content="[[旧名]]\n")
        r = client.post(
            f"{doc_api}/{src['id']}/links/repair",
            json={"repairs": [{"title": "旧名", "target_document_id": foreign["id"]}]},
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_repair_folder_source_409(self, client, doc_api, auth_headers):
        target = _create_doc(client, doc_api, auth_headers, title="目标")
        folder = _create_doc(client, doc_api, auth_headers, title="目录", is_folder=True)
        r = client.post(
            f"{doc_api}/{folder['id']}/links/repair",
            json={"repairs": [{"title": "旧名", "target_document_id": target["id"]}]},
            headers=auth_headers,
        )
        assert r.status_code == 409

    def test_repair_empty_payload_rejected(self, client, doc_api, auth_headers):
        src = _create_doc(client, doc_api, auth_headers, title="来源", content="[[旧名]]\n")
        r = client.post(f"{doc_api}/{src['id']}/links/repair", json={"repairs": []}, headers=auth_headers)
        assert r.status_code == 422


# ── 检索健壮性 ──


class TestSearchRobustness:
    @pytest.mark.parametrize(
        "query",
        [
            "AND",
            "OR",
            "NOT",
            "a AND",
            "NOT a",
            "OR OR",
            "*",
            "***",
            '"unclosed',
            "()",
            "a AND OR b",
            "^~:{}[]",
        ],
    )
    def test_invalid_syntax_never_500(self, client, doc_api, auth_headers, query):
        _create_doc(client, doc_api, auth_headers, title="检索样本", content="and or not 关键字样例")
        r = client.get(f"{doc_api}/search", params={"q": query}, headers=auth_headers)
        assert r.status_code in (200, 400), f"{query!r} -> {r.status_code}: {r.text}"

    def test_symbols_only_query_400(self, client, doc_api, auth_headers):
        r = client.get(f"{doc_api}/search", params={"q": "()"}, headers=auth_headers)
        assert r.status_code == 400

    def test_boolean_combination_still_works(self, client, doc_api, auth_headers):
        _create_doc(client, doc_api, auth_headers, title="布尔A", content="alpha beta gamma")
        _create_doc(client, doc_api, auth_headers, title="布尔B", content="alpha only")
        r = client.get(f"{doc_api}/search", params={"q": "alpha AND beta"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_bare_operator_searches_literal_word(self, client, doc_api, auth_headers):
        _create_doc(client, doc_api, auth_headers, title="字面量", content="the and operator word")
        r = client.get(f"{doc_api}/search", params={"q": "AND"}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 1

    def test_unclosed_quote_treated_as_phrase(self, client, doc_api, auth_headers):
        _create_doc(client, doc_api, auth_headers, title="短语", content="hello brave world")
        r = client.get(f"{doc_api}/search", params={"q": '"brave world'}, headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["total"] == 1


class TestEscapeQuery:
    def test_bare_operator_quoted(self):
        assert escape_query("AND") == '"AND"'

    def test_boolean_preserved_between_terms(self):
        assert escape_query("foo AND bar") == '"foo" AND "bar"'

    def test_dangling_operator_becomes_literal(self):
        assert escape_query("a AND") == '"a" "AND"'

    def test_adjacent_operators_degrade_to_literal(self):
        assert escape_query("a AND OR b") == '"a" AND "OR" "b"'

    def test_prefix_kept(self):
        assert escape_query("foo*") == '"foo"*'

    def test_phrase_kept(self):
        assert escape_query('"foo bar" baz') == '"foo bar" "baz"'

    def test_unclosed_quote_closed(self):
        assert escape_query('"foo bar') == '"foo bar"'

    def test_syntax_chars_split_words(self):
        assert escape_query("foo(bar)") == '"foo" "bar"'

    @pytest.mark.parametrize("query", ["***", "()", '""', "   "])
    def test_no_effective_token_rejected(self, query):
        from cndb.core.errors import BadRequestError

        with pytest.raises(BadRequestError):
            escape_query(query)


# ── 并发写入 ──


class TestVersionConflict:
    def test_stale_version_pointer_yields_409(self, client, doc_api, auth_headers, db, monkeypatch):
        """并发保存导致版本号竞争时返回 409（doc_version_conflict），而非 500."""
        doc = _create_doc(client, doc_api, auth_headers, content="第一版")
        full = _get_content(client, doc_api, auth_headers, doc["id"])
        r = client.put(
            f"{doc_api}/{doc['id']}/content",
            json={"content": "第二版", "base_updated_at": full["updated_at"]},
            headers=auth_headers,
        )
        assert r.status_code == 200

        stale = db.execute(
            select(DocumentVersion).where(DocumentVersion.document_id == doc["id"], DocumentVersion.version_number == 1)
        ).scalar_one()
        monkeypatch.setattr(content_service, "latest_version", lambda _db, _doc_id: stale)

        r = client.put(f"{doc_api}/{doc['id']}/content", json={"content": "第三版"}, headers=auth_headers)
        assert r.status_code == 409, r.text
        assert r.json()["code"] == "doc_version_conflict"
