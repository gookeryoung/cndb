"""工作区全量备份 v9（ADR 0075）：归档结构、往返一致与密钥口径校验."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient

from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

WS = "/api/v1/workspaces"
DOCS = "/api/v1/workspaces/{wid}/documents"
TABLES = "/api/v1/workspaces/{wid}/tables"


def _new_workspace(client: TestClient, headers: dict[str, str], name: str) -> int:
    r = client.post(WS, json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _seed_workspace(client: TestClient, headers: dict[str, str], db, wid: int) -> None:
    """构造覆盖 v9 全部新增维度的源工作区（表/行/文档/版本/草稿/分享/议题/回收站/附件/会话）."""
    from cndb.plugins.accounts.models import User
    from cndb.plugins.datasource.models import DatasourceSession
    from cndb.plugins.documents.models import (
        DocumentIssue,
        DocumentIssueComment,
        DocumentShare,
        DocumentVersion,
    )
    from cndb.plugins.files.models import FileOwner
    from cndb.plugins.files.services import resolve_workspace_file

    # 表 + 字段 + 行
    r = client.post(TABLES.format(wid=wid), json={"name": "库存表", "description": ""}, headers=headers)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.post(
        f"{TABLES.format(wid=wid)}/{tid}/fields",
        json={"name": "商品", "field_type": "text", "order": 0},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    r = client.post(f"{TABLES.format(wid=wid)}/{tid}/records", json={"values": {"商品": "苹果"}}, headers=headers)
    assert r.status_code in (200, 201), r.text

    # 文档（两个版本：创建 + 直接插 v2）
    r = client.post(DOCS.format(wid=wid), json={"title": "笔记", "content": "第一版正文\n"}, headers=headers)
    assert r.status_code == 201, r.text
    doc = r.json()
    user = db.query(User).first()
    db.add(
        DocumentVersion(
            document_id=doc["id"],
            version_number=2,
            content="第二版正文\n",
            content_size=18,
            content_hash="h2",
            change_summary="第二次编辑",
            change_type="manual",
            created_by_id=user.id,
        )
    )
    db.commit()

    # 草稿 / 分享 / 议题+评论
    from cndb.plugins.documents.models import DocumentDraft

    db.add(
        DocumentDraft(
            document_id=doc["id"],
            user_id=user.id,
            content="草稿内容",
            content_size=12,
            content_hash="",
            base_version_number=1,
        )
    )
    db.add(DocumentShare(document_id=doc["id"], token="tok-backup-test-1", permission="viewer", created_by_id=user.id))
    issue = DocumentIssue(
        workspace_id=wid,
        document_id=doc["id"],
        title="数据有误",
        description="错别字",
        category="other",
        created_by_id=user.id,
    )
    db.add(issue)
    db.flush()
    db.add(DocumentIssueComment(issue_id=issue.id, content="已确认", created_by_id=user.id))

    # 回收站文档
    r = client.post(DOCS.format(wid=wid), json={"title": "已删除", "content": "回收站正文\n"}, headers=headers)
    deleted_doc = r.json()
    r = client.delete(f"{DOCS.format(wid=wid)}/{deleted_doc['id']}", headers=headers)
    assert r.status_code in (200, 204), r.text

    # 附件（直接落盘 + 归属记录）
    key = "backup-attach-test.txt"
    resolve_workspace_file(wid, key).write_bytes("附件内容".encode())
    db.add(FileOwner(file_key=key, workspace_id=wid, uploaded_by_id=user.id))

    # 数据源会话（含密钥）
    db.add(
        DatasourceSession(
            workspace_id=wid, created_by=user.id, name="源站会话", headers={"UA": "x"}, secrets={"api_key": "k-123"}
        )
    )
    db.commit()


def _export_archive(
    client: TestClient, headers: dict[str, str], wid: int, include_secrets: bool | None = None
) -> bytes:
    url = f"{WS}/{wid}/export/archive"
    if include_secrets is not None:
        url += f"?include_secrets={'true' if include_secrets else 'false'}"
    r = client.get(url, headers=headers)
    assert r.status_code == 200, r.text
    return r.content


class TestArchiveStructure:
    def test_archive_manifest_and_payload(self, client, auth_headers, db, tmp_path: Path):
        wid = _new_workspace(client, auth_headers, "结构测试")
        _seed_workspace(client, auth_headers, db, wid)

        raw = _export_archive(client, auth_headers, wid)
        archive_file = tmp_path / "a.tar.gz"
        archive_file.write_bytes(raw)
        archive = parse_workspace_archive(archive_file)
        try:
            m = archive.manifest
            assert m["kind"] == "workspace_backup"
            assert m["version"] == "1"
            assert m["include_secrets"] is True
            backup = archive.backup
            assert backup["version"] == "9"
            assert backup["include_secrets"] is True
            # v9 新增顶层键齐全
            for key in (
                "document_versions",
                "drafts",
                "doc_change_requests",
                "datasource_sessions",
                "entrant_cursors",
                "file_owners",
            ):
                assert key in backup, key
            # 表行附 __row_id；表 members 键存在
            table = backup["tables"][0]
            assert table["rows"] and "__row_id" in table["rows"][0]
            assert "members" in table
            # 软删除文档随备份携带
            docs = {d["title"]: d for d in backup["documents"]}
            assert set(docs) == {"笔记", "已删除"}
            assert docs["已删除"]["is_deleted"] is True
            # 版本历史：笔记两版（回收站文档另有 v1）
            note_versions = [v for v in backup["document_versions"] if v["document_id"] == docs["笔记"]["id"]]
            assert len(note_versions) == 2
            assert note_versions[1]["content"] == "第二版正文\n"
            # 草稿 / 分享 / 议题 / 会话密钥
            assert backup["drafts"][0]["content"] == "草稿内容"
            assert docs["笔记"]["shares"][0]["token"] == "tok-backup-test-1"
            assert docs["笔记"]["issue"][0]["title"] == "数据有误"
            assert backup["datasource_sessions"][0]["secrets"] == {"api_key": "k-123"}
            # 附件条目
            assert backup["file_owners"][0]["file_key"] == "backup-attach-test.txt"
            assert (archive.files_dir / "files" / "uploads" / "backup-attach-test.txt").is_file()
        finally:
            archive.cleanup()

    def test_v8_export_has_no_v9_keys(self, client, auth_headers, db):
        wid = _new_workspace(client, auth_headers, "v8降采样")
        _seed_workspace(client, auth_headers, db, wid)
        backup = client.get(f"{WS}/{wid}/export", headers=auth_headers).json()
        assert backup["version"] == "8"
        for key in (
            "document_versions",
            "drafts",
            "doc_change_requests",
            "datasource_sessions",
            "entrant_cursors",
            "file_owners",
            "include_secrets",
        ):
            assert key not in backup, key
        assert "__row_id" not in backup["tables"][0]["rows"][0]
        assert "members" not in backup["tables"][0]
        titles = {d["title"] for d in backup["documents"]}
        assert "已删除" not in titles  # v8 口径过滤回收站


class TestRestoreRoundtrip:
    def test_full_roundtrip_restores_everything(self, client, auth_headers, db, tmp_path: Path):
        wid = _new_workspace(client, auth_headers, "往返源")
        _seed_workspace(client, auth_headers, db, wid)
        raw = _export_archive(client, auth_headers, wid)
        archive_file = tmp_path / "full.tar.gz"
        archive_file.write_bytes(raw)

        # 覆盖恢复到同一工作区（clear + import）
        r = client.post(
            f"{WS}/{wid}/restore",
            files={"file": ("backup.tar.gz", io.BytesIO(raw), "application/gzip")},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported_tables"] == 1
        assert body["errors"] == [], body["errors"]

        from cndb.plugins.datasource.models import DatasourceSession
        from cndb.plugins.documents.models import (
            Document,
            DocumentDraft,
            DocumentIssue,
            DocumentShare,
            DocumentVersion,
        )
        from cndb.plugins.files.models import FileOwner
        from cndb.plugins.files.services import resolve_workspace_file

        docs = db.query(Document).filter(Document.workspace_id == wid).all()
        assert len(docs) == 2  # 含回收站文档
        doc = next(d for d in docs if d.title == "笔记")
        versions = db.query(DocumentVersion).filter(DocumentVersion.document_id == doc.id).all()
        assert {v.version_number for v in versions} == {1, 2}
        assert db.query(DocumentDraft).filter(DocumentDraft.document_id == doc.id).count() == 1
        assert db.query(DocumentShare).filter(DocumentShare.document_id == doc.id).count() == 1
        assert db.query(DocumentIssue).filter(DocumentIssue.document_id == doc.id).count() == 1
        deleted = next(d for d in docs if d.title == "已删除")
        assert deleted.is_deleted is True
        # 附件：归属记录 + 落盘文件
        assert (
            db.query(FileOwner)
            .filter(FileOwner.workspace_id == wid, FileOwner.file_key == "backup-attach-test.txt")
            .count()
            == 1
        )
        assert resolve_workspace_file(wid, "backup-attach-test.txt").read_bytes() == "附件内容".encode()
        # 会话密钥还原
        session = db.query(DatasourceSession).filter(DatasourceSession.workspace_id == wid).first()
        assert session is not None and session.secrets == {"api_key": "k-123"}
        # 行数据还原
        r = client.get(f"{TABLES.format(wid=wid)}", headers=auth_headers)
        tables = r.json()["items"] if isinstance(r.json(), dict) else r.json()
        tid = tables[0]["id"]
        r = client.get(f"{TABLES.format(wid=wid)}/{tid}/records", headers=auth_headers)
        records = r.json()
        rows = records["items"] if isinstance(records, dict) else records
        assert any((row.get("商品") == "苹果") or (row.get("values", {}).get("商品") == "苹果") for row in rows)

    def test_import_archive_creates_new_workspace(self, client, auth_headers, db, tmp_path: Path):
        wid = _new_workspace(client, auth_headers, "导入源")
        _seed_workspace(client, auth_headers, db, wid)
        raw = _export_archive(client, auth_headers, wid)

        r = client.post(
            f"{WS}/import/archive",
            files={"file": ("backup.tar.gz", io.BytesIO(raw), "application/gzip")},
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        new_wid = r.json()["workspace"]["id"]
        assert new_wid != wid
        assert r.json()["errors"] == []
        from cndb.plugins.documents.models import Document

        assert db.query(Document).filter(Document.workspace_id == new_wid).count() == 2

    def test_include_secrets_false_leaves_secrets_empty(self, client, auth_headers, db, tmp_path: Path):
        wid = _new_workspace(client, auth_headers, "无密钥")
        _seed_workspace(client, auth_headers, db, wid)
        raw = _export_archive(client, auth_headers, wid, include_secrets=False)

        archive_file = tmp_path / "nosec.tar.gz"
        archive_file.write_bytes(raw)
        archive = parse_workspace_archive(archive_file)
        try:
            assert archive.manifest["include_secrets"] is False
            assert archive.backup["datasource_sessions"][0]["secrets"] is None
        finally:
            archive.cleanup()

        r = client.post(
            f"{WS}/{wid}/restore",
            files={"file": ("n.tar.gz", io.BytesIO(raw), "application/gzip")},
            headers=auth_headers,
        )
        assert r.status_code == 200, r.text
        from cndb.plugins.datasource.models import DatasourceSession

        session = db.query(DatasourceSession).filter(DatasourceSession.workspace_id == wid).first()
        assert session is not None
        assert session.secrets == {}

    def test_restore_rejects_non_archive(self, client, auth_headers):
        wid = _new_workspace(client, auth_headers, "坏归档")
        r = client.post(
            f"{WS}/{wid}/restore",
            files={"file": ("bad.tar.gz", io.BytesIO(b"not a tar"), "application/gzip")},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text
