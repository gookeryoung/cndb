"""字段业务元数据的工作区备份往返（ADR 0188 C10）."""

from __future__ import annotations

import io
import json
import tarfile
from pathlib import Path

from fastapi.testclient import TestClient

WS = "/api/v1/workspaces"
TABLES = "/api/v1/workspaces/{wid}/tables"


def _new_workspace(client: TestClient, headers: dict[str, str], name: str) -> int:
    r = client.post(WS, json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _export_archive(client: TestClient, headers: dict[str, str], wid: int) -> bytes:
    r = client.get(f"{WS}/{wid}/export/archive", headers=headers)
    assert r.status_code == 200, r.text
    return r.content


def _read_backup(raw: bytes) -> dict:
    """从归档字节里取出 backup.json."""
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        member = next(n for n in tar.getnames() if n.endswith("backup.json"))
        fh = tar.extractfile(member)
        assert fh is not None
        return json.loads(fh.read().decode("utf-8"))


def _write_archive(path: Path, backup: dict) -> Path:
    """按归档协议手写一个 tar.gz（manifest + backup.json）."""
    manifest = {
        "version": "1",
        "kind": "workspace_backup",
        "backup_version": backup.get("version", "17"),
    }
    members = {
        "payload/manifest.json": json.dumps(manifest, ensure_ascii=False).encode("utf-8"),
        "payload/backup.json": json.dumps(backup, ensure_ascii=False).encode("utf-8"),
    }
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_backup_carries_field_business_metadata(client, auth_headers):
    """C10：导出备份的 fields[] 带 6 个业务元数据键."""
    wid = _new_workspace(client, auth_headers, "元数据备份")
    r = client.post(f"{TABLES.format(wid=wid)}", json={"name": "表A"}, headers=auth_headers)
    tid = r.json()["id"]
    r = client.post(
        f"{TABLES.format(wid=wid)}/{tid}/fields",
        headers=auth_headers,
        json={
            "name": "金额",
            "field_type": "float",
            "business_meaning": "含税金额",
            "unit": "元",
            "sensitivity": "confidential",
            "standard_ref": "FIN-001",
            "example_value": "1200.00",
        },
    )
    assert r.status_code == 201, r.text

    backup = _read_backup(_export_archive(client, auth_headers, wid))
    field = backup["tables"][0]["fields"][0]
    assert field["business_meaning"] == "含税金额"
    assert field["unit"] == "元"
    assert field["sensitivity"] == "confidential"
    assert field["standard_ref"] == "FIN-001"
    assert field["example_value"] == "1200.00"
    # owner_id 随导出保留（同实例往返可复原）
    assert "owner_id" in field


def test_backup_roundtrip_restores_metadata(client, auth_headers, tmp_path):
    """C10：导出 → 导入新工作区，业务元数据一致；owner_id 不迁移."""
    wid = _new_workspace(client, auth_headers, "元数据往返源")
    r = client.post(f"{TABLES.format(wid=wid)}", json={"name": "表B"}, headers=auth_headers)
    tid = r.json()["id"]
    r = client.post(
        f"{TABLES.format(wid=wid)}/{tid}/fields",
        headers=auth_headers,
        json={
            "name": "客户编号",
            "field_type": "text",
            "business_meaning": "客户唯一编号",
            "unit": "无",
            "sensitivity": "internal",
            "standard_ref": "CRM-001",
            "example_value": "C0001",
        },
    )
    assert r.status_code == 201, r.text

    raw = _export_archive(client, auth_headers, wid)
    archive_file = tmp_path / "meta.tar.gz"
    archive_file.write_bytes(raw)
    with archive_file.open("rb") as fh:
        r = client.post(
            f"{WS}/import/archive",
            files={"file": (archive_file.name, fh, "application/gzip")},
            headers=auth_headers,
        )
    assert r.status_code == 201, r.text
    new_wid = r.json()["workspace"]["id"]

    r = client.get(f"{TABLES.format(wid=new_wid)}", headers=auth_headers)
    new_tid = r.json()[0]["id"]
    r = client.get(f"{TABLES.format(wid=new_wid)}/{new_tid}/fields", headers=auth_headers)
    field = r.json()[0]
    assert field["business_meaning"] == "客户唯一编号"
    assert field["unit"] == "无"
    assert field["sensitivity"] == "internal"
    assert field["standard_ref"] == "CRM-001"
    assert field["example_value"] == "C0001"
    # 责任人 id 不跨实例迁移（本实例里同 id 的账号属于别的语义）
    assert field["owner_id"] is None


def test_old_backup_without_metadata_imports_empty(client, auth_headers, tmp_path):
    """C10：旧包（fields[] 无这些键）按空还原，不报错."""
    backup = {
        "version": "17",
        "workspace": {"name": "旧包", "visibility": "member"},
        "tables": [
            {
                "id": 1,
                "name": "旧表",
                "fields": [{"id": 1, "name": "名称", "field_type": "text", "order": 0}],
                "views": [],
                "links": [],
                "permission": None,
                "row_permissions": [],
                "members": [],
                "rows": [{"名称": "甲"}],
            }
        ],
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
        "templates": [],
        "content_templates": [],
        "include_secrets": False,
    }
    archive_file = _write_archive(tmp_path / "old.tar.gz", backup)
    with archive_file.open("rb") as fh:
        r = client.post(
            f"{WS}/import/archive",
            files={"file": (archive_file.name, fh, "application/gzip")},
            headers=auth_headers,
        )
    assert r.status_code == 201, r.text
    new_wid = r.json()["workspace"]["id"]

    r = client.get(f"{TABLES.format(wid=new_wid)}", headers=auth_headers)
    new_tid = r.json()[0]["id"]
    r = client.get(f"{TABLES.format(wid=new_wid)}/{new_tid}/fields", headers=auth_headers)
    field = r.json()[0]
    for key in ("business_meaning", "unit", "sensitivity", "owner_id", "standard_ref", "example_value"):
        assert field[key] is None, f"{key} 应为 None"


def test_field_import_copies_metadata(client, auth_headers):
    """C10 派生：字段引入复制业务元数据（owner_id 除外）."""
    wid = _new_workspace(client, auth_headers, "字段引入")
    r = client.post(f"{TABLES.format(wid=wid)}", json={"name": "源表"}, headers=auth_headers)
    src_tid = r.json()["id"]
    r = client.post(
        f"{TABLES.format(wid=wid)}/{src_tid}/fields",
        headers=auth_headers,
        json={
            "name": "金额",
            "field_type": "float",
            "business_meaning": "含税金额",
            "unit": "元",
            "sensitivity": "public",
            "standard_ref": "FIN-001",
            "example_value": "1.00",
        },
    )
    assert r.status_code == 201, r.text

    r = client.post(f"{TABLES.format(wid=wid)}", json={"name": "目标表"}, headers=auth_headers)
    dst_tid = r.json()["id"]
    r = client.post(
        f"{TABLES.format(wid=wid)}/{dst_tid}/fields/import",
        headers=auth_headers,
        json={"source_table_id": src_tid, "import_all_fields": True},
    )
    assert r.status_code == 201, r.text
    created = r.json()["created"][0]
    assert created["business_meaning"] == "含税金额"
    assert created["unit"] == "元"
    assert created["sensitivity"] == "public"
    assert created["standard_ref"] == "FIN-001"
    assert created["example_value"] == "1.00"
