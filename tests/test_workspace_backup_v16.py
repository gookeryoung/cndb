"""工作区备份 v16（ADR 0075 D8）：表行 NDJSON 分块导出、恢复与旧版兼容."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cndb.core.errors import BadRequestError
from cndb.plugins.workspaces.services.workspace_backup import (
    build_workspace_backup_v9,
    pack_workspace_archive,
    parse_workspace_archive,
    read_rows_chunk,
)

WS = "/api/v1/workspaces"
TABLES = "/api/v1/workspaces/{wid}/tables"


def _new_workspace(client: TestClient, headers: dict[str, str], name: str) -> int:
    r = client.post(WS, json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _add_table(client: TestClient, headers: dict[str, str], wid: int, name: str, values: list[dict]) -> int:
    r = client.post(TABLES.format(wid=wid), json={"name": name, "description": ""}, headers=headers)
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.post(
        f"{TABLES.format(wid=wid)}/{tid}/fields",
        json={"name": "名称", "field_type": "text", "order": 0},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    for value in values:
        r = client.post(f"{TABLES.format(wid=wid)}/{tid}/records", json={"values": value}, headers=headers)
        assert r.status_code in (200, 201), r.text
    return tid


def _seed_workspace(client: TestClient, headers: dict[str, str], wid: int) -> None:
    """两张表共 3 行：用于验证「每表一个分块」与行数据往返."""
    _add_table(client, headers, wid, "甲表", [{"名称": "甲一"}])
    _add_table(client, headers, wid, "乙表", [{"名称": "乙一"}, {"名称": "乙二"}])


def _export_archive(client: TestClient, headers: dict[str, str], wid: int) -> bytes:
    r = client.get(f"{WS}/{wid}/export/archive", headers=headers)
    assert r.status_code == 200, r.text
    return r.content


def _import_archive(client: TestClient, headers: dict[str, str], path: Path) -> dict:
    with path.open("rb") as fh:
        r = client.post(
            f"{WS}/import/archive",
            files={"file": (path.name, fh, "application/gzip")},
            headers=headers,
        )
    assert r.status_code == 201, r.text
    return r.json()


def _minimal_backup(rows_file: str | None) -> dict:
    """最小可导入的 v16 备份载荷（单表 / 单字段）."""
    table: dict = {
        "id": 1,
        "name": "分块表",
        "fields": [{"id": 1, "name": "名称", "field_type": "text", "order": 0}],
        "views": [],
        "links": [],
        "permission": None,
        "row_permissions": [],
        "members": [],
    }
    if rows_file is None:
        table["rows"] = [{"名称": "内联"}]
    else:
        table["rows_file"] = rows_file
    return {
        "version": "16",
        "workspace": {"name": "分块导入", "visibility": "member"},
        "tables": [table],
        "document_tags": [],
        "documents": [],
        "document_versions": [],
        "drafts": [],
        "doc_change_requests": [],
        "sync_jobs": [],
        "datasource_sessions": [],
        "file_owners": [],
        "charts": [],
        "pipelines": [],
        "designs": [],
        "library_refs": [],
        "include_secrets": False,
    }


def _write_archive(path: Path, backup: dict, chunks: dict[str, bytes] | None = None) -> Path:
    """按归档协议手写一个 tar.gz（manifest + backup.json + 可选分块）."""
    manifest = {"version": "1", "kind": "workspace_backup", "backup_version": backup.get("version", "16")}
    members = {
        "payload/manifest.json": json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        "payload/backup.json": json.dumps(backup, ensure_ascii=False).encode("utf-8"),
        **{f"payload/{name}": data for name, data in (chunks or {}).items()},
    }
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


class TestChunkedExport:
    def test_each_table_exported_to_own_ndjson_chunk(
        self, client: TestClient, auth_headers: dict[str, str], tmp_path: Path
    ) -> None:
        wid = _new_workspace(client, auth_headers, "分块导出")
        _seed_workspace(client, auth_headers, wid)

        archive_file = tmp_path / "chunked.tar.gz"
        archive_file.write_bytes(_export_archive(client, auth_headers, wid))
        archive = parse_workspace_archive(archive_file)
        try:
            assert archive.backup["version"] == "16"
            assert archive.manifest["backup_version"] == "16"
            tables = archive.backup["tables"]
            assert [t["name"] for t in tables] == ["甲表", "乙表"]
            # backup.json 不再内联行数据，只留分块引用；每表一份分块文件
            assert all("rows" not in t for t in tables)
            assert [t["rows_file"] for t in tables] == ["tables/000.ndjson", "tables/001.ndjson"]
            assert [len(read_rows_chunk(archive.files_dir / t["rows_file"])) for t in tables] == [1, 2]
            assert read_rows_chunk(archive.files_dir / tables[1]["rows_file"])[0]["名称"] == "乙一"
            # stats.files 只数附件 / 外存内容，分块不占这个口径
            assert archive.manifest["stats"]["files"] == 0
        finally:
            archive.cleanup()

    def test_chunked_archive_roundtrip_imports_rows(
        self, client: TestClient, auth_headers: dict[str, str], tmp_path: Path
    ) -> None:
        wid = _new_workspace(client, auth_headers, "分块往返")
        _seed_workspace(client, auth_headers, wid)

        archive_file = tmp_path / "roundtrip.tar.gz"
        archive_file.write_bytes(_export_archive(client, auth_headers, wid))
        body = _import_archive(client, auth_headers, archive_file)

        assert body["errors"] == []
        assert body["imported_tables"] == 2
        # 行数据经 NDJSON 分块读回并落库（1 + 2 行）
        assert body["imported_rows"] == 3


class TestChunkGuards:
    def test_missing_chunk_rejected(self, tmp_path: Path) -> None:
        path = _write_archive(tmp_path / "missing.tar.gz", _minimal_backup("tables/000.ndjson"))
        with pytest.raises(BadRequestError, match="缺少表数据分块"):
            parse_workspace_archive(path)

    def test_rows_file_outside_payload_rejected(self, tmp_path: Path) -> None:
        path = _write_archive(
            tmp_path / "escape.tar.gz",
            _minimal_backup("../evil.ndjson"),
            {"../evil.ndjson": b'{"\xe5\x90\x8d\xe7\xa7\xb0": "\xe8\xb6\x8a\xe7\x95\x8c"}\n'},
        )
        with pytest.raises(BadRequestError, match="越界表数据路径"):
            parse_workspace_archive(path)

    def test_corrupted_chunk_rejected_on_import(
        self, client: TestClient, auth_headers: dict[str, str], tmp_path: Path
    ) -> None:
        path = _write_archive(
            tmp_path / "broken.tar.gz",
            _minimal_backup("tables/000.ndjson"),
            {"tables/000.ndjson": b"{not-json}\n"},
        )
        with path.open("rb") as fh:
            r = client.post(
                f"{WS}/import/archive",
                files={"file": ("broken.tar.gz", fh, "application/gzip")},
                headers=auth_headers,
            )
        assert r.status_code == 400, r.text
        assert "分块损坏" in r.json()["detail"]

    def test_json_import_without_files_dir_rejected(self, client: TestClient, auth_headers: dict[str, str], db) -> None:
        """纯 JSON 导入通道没有 payload 目录，出现 rows_file 引用必须显式拒绝."""
        wid = _new_workspace(client, auth_headers, "JSON分块")
        r = client.post(
            f"{WS}/{wid}/import",
            json={"json_data": _minimal_backup("tables/000.ndjson")},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text
        assert "缺少表数据分块" in r.json()["detail"]


class TestLegacyInlineCompat:
    def test_v15_inline_rows_archive_still_imports(
        self, client: TestClient, auth_headers: dict[str, str], db, tmp_path: Path
    ) -> None:
        """≤v15 归档仍用内联 ``rows``：分块改造不得破坏旧包导入."""
        from cndb.plugins.accounts.models import User

        wid = _new_workspace(client, auth_headers, "旧版内联")
        _seed_workspace(client, auth_headers, wid)

        user = db.query(User).first()
        backup, files = build_workspace_backup_v9(db, wid, user, include_secrets=False)
        assert backup["version"] == "15"
        assert all("rows" in tbl for tbl in backup["tables"])

        legacy_file = tmp_path / "legacy-v15.tar.gz"
        pack_workspace_archive(backup, files, legacy_file)

        body = _import_archive(client, auth_headers, legacy_file)
        assert body["errors"] == []
        assert body["imported_rows"] == 3
