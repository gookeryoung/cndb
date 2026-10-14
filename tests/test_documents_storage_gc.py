"""文档外存内容体检与物理回收（services.storage）测试.

覆盖：有效引用识别、丢失文件报告、孤儿/命名不规范/位置不规范文件的发现、
dry-run 与 --apply 语义、软删除（回收站）文件不得被回收、根目录缺失兜底。
"""

from __future__ import annotations

import pytest
from sqlalchemy import delete

from cndb.plugins.documents.models import DocumentVersion
from cndb.plugins.documents.services import content as content_service
from cndb.plugins.documents.services.storage import purge_external_orphans, scan_external_storage

API = "/api/v1/workspaces/{wid}/documents"
BIG_SIZE = content_service.EXTERNAL_MIN_SIZE + 4096


@pytest.fixture
def workspace_id(client, auth_headers) -> int:
    r = client.post("/api/v1/workspaces", json={"name": "docs-gc-ws"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def doc_api(workspace_id: int) -> str:
    return API.format(wid=workspace_id)


@pytest.fixture
def docs_dir(monkeypatch, tmp_path):
    target = tmp_path / "docs"
    monkeypatch.setattr(content_service, "_DOCS_DIR", target)
    return target


def _create_big_doc(client, doc_api, auth_headers) -> dict:
    r = client.post(
        doc_api,
        json={"title": "外存文档", "content": "A" * BIG_SIZE},
        headers=auth_headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestScanExternalStorage:
    def test_all_referenced_no_orphan(self, client, doc_api, auth_headers, docs_dir, db):
        doc = _create_big_doc(client, doc_api, auth_headers)
        report = scan_external_storage(db)
        assert report.root == docs_dir
        assert report.referenced_files == 1
        assert report.orphan_files == []
        assert report.missing_files == []
        assert report.orphan_bytes == 0
        assert (docs_dir / str(doc["id"]) / "v1.md.gz").is_file()

    def test_missing_referenced_file_reported(self, client, doc_api, auth_headers, docs_dir, db):
        doc = _create_big_doc(client, doc_api, auth_headers)
        target = docs_dir / str(doc["id"]) / "v1.md.gz"
        target.unlink()
        report = scan_external_storage(db)
        assert report.referenced_files == 0
        assert report.missing_files == [target]
        assert report.orphan_files == []

    def test_orphan_and_irregular_files_detected(self, client, doc_api, auth_headers, docs_dir, db):
        doc = _create_big_doc(client, doc_api, auth_headers)
        doc_dir = docs_dir / str(doc["id"])

        orphan_dir = docs_dir / "999"  # 无对应文档的目录
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "v1.md.gz").write_bytes(b"x")
        (doc_dir / "v9.md.gz").write_bytes(b"y")  # 失去版本引用
        (doc_dir / "notes.txt").write_bytes(b"z")  # 命名不规范
        (docs_dir / "stray.md.gz").write_bytes(b"s")  # 位置不规范

        report = scan_external_storage(db)
        reasons = {item.path.name: item.reason for item in report.orphan_files}
        assert set(reasons) == {"v1.md.gz", "v9.md.gz", "notes.txt", "stray.md.gz"}
        assert reasons["v9.md.gz"] == "失去版本引用"
        assert "命名不规范" in reasons["notes.txt"]
        assert "位置不规范" in reasons["stray.md.gz"]
        assert report.orphan_bytes == 4

    def test_soft_deleted_document_files_still_referenced(self, client, doc_api, auth_headers, docs_dir, db):
        doc = _create_big_doc(client, doc_api, auth_headers)
        assert client.delete(f"{doc_api}/{doc['id']}", headers=auth_headers).status_code == 200
        report = scan_external_storage(db)
        assert report.orphan_files == []
        assert report.referenced_files == 1

    def test_versions_gone_makes_file_orphan(self, client, doc_api, auth_headers, docs_dir, db):
        doc = _create_big_doc(client, doc_api, auth_headers)
        db.execute(delete(DocumentVersion).where(DocumentVersion.document_id == doc["id"]))
        db.commit()
        report = scan_external_storage(db)
        assert [item.path.name for item in report.orphan_files] == ["v1.md.gz"]

    def test_missing_root_returns_empty_report(self, db, tmp_path):
        report = scan_external_storage(db, root=tmp_path / "not-exist")
        assert report.orphan_files == [] and report.missing_files == []


class TestPurgeExternalOrphans:
    def _seed_orphan(self, docs_dir):
        orphan_dir = docs_dir / "999"
        orphan_dir.mkdir(parents=True)
        (orphan_dir / "v1.md.gz").write_bytes(b"x")
        return orphan_dir

    def test_dry_run_keeps_files(self, client, doc_api, auth_headers, docs_dir, db):
        doc = _create_big_doc(client, doc_api, auth_headers)
        orphan_dir = self._seed_orphan(docs_dir)

        report = purge_external_orphans(db, dry_run=True)

        assert report.dry_run is True
        assert report.removed_files == 0 and report.removed_dirs == 0
        assert (orphan_dir / "v1.md.gz").is_file()
        assert (docs_dir / str(doc["id"]) / "v1.md.gz").is_file()

    def test_apply_removes_orphans_and_empty_dirs(self, client, doc_api, auth_headers, docs_dir, db):
        doc = _create_big_doc(client, doc_api, auth_headers)
        orphan_dir = self._seed_orphan(docs_dir)
        (docs_dir / str(doc["id"]) / "notes.txt").write_bytes(b"z")

        report = purge_external_orphans(db, dry_run=False)

        assert report.dry_run is False
        assert report.removed_files == 2  # 999/v1.md.gz + notes.txt
        assert report.removed_dirs == 1  # 999 空目录
        assert not orphan_dir.exists()
        # 被引用的外存文件与所在目录保留
        assert (docs_dir / str(doc["id"]) / "v1.md.gz").is_file()
        assert (docs_dir / str(doc["id"])).is_dir()

    def test_apply_idempotent(self, docs_dir, db):
        self._seed_orphan(docs_dir)
        first = purge_external_orphans(db, dry_run=False)
        second = purge_external_orphans(db, dry_run=False)
        assert first.removed_files == 1
        assert second.orphan_files == [] and second.removed_files == 0
