"""工作区备份 v12（ADR 0080 D7）：modules 随备份导出导入、旧备份映射兼容."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

WS = "/api/v1/workspaces"
ALL = ["tables", "documents", "design"]


def _new_workspace(
    client: TestClient,
    headers: dict[str, str],
    name: str,
    modules: list[str] | None = None,
) -> dict:
    payload: dict = {"name": name}
    if modules is not None:
        payload["modules"] = modules
    r = client.post(WS, json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _export_archive(client: TestClient, headers: dict[str, str], wid: int) -> bytes:
    r = client.get(f"{WS}/{wid}/export/archive", headers=headers)
    assert r.status_code == 200, r.text
    return r.content


class TestBackupV12Modules:
    def test_v12_exports_modules_and_roundtrip(
        self, client: TestClient, auth_headers: dict[str, str], tmp_path: Path
    ) -> None:
        ws = _new_workspace(client, auth_headers, "模块备份", ["tables", "design"])
        raw = _export_archive(client, auth_headers, ws["id"])
        archive_file = tmp_path / "ws.tar.gz"
        archive_file.write_bytes(raw)

        from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

        archive = parse_workspace_archive(archive_file)
        try:
            assert archive.backup["version"] == "13"
            assert archive.backup["workspace"]["modules"] == ["tables", "design"]
            assert "workspace_type" not in archive.backup["workspace"]
        finally:
            archive.cleanup()

        # 从归档创建新工作区：模块口径保留
        with archive_file.open("rb") as fh:
            r = client.post(
                f"{WS}/import/archive", files={"file": ("ws.tar.gz", fh, "application/gzip")}, headers=auth_headers
            )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["workspace"]["modules"] == ["tables", "design"]
        assert body["errors"] == []

    def test_restore_restores_modules(self, client: TestClient, auth_headers: dict[str, str], tmp_path: Path) -> None:
        src = _new_workspace(client, auth_headers, "恢复源", ["documents"])
        raw = _export_archive(client, auth_headers, src["id"])
        archive_file = tmp_path / "restore.tar.gz"
        archive_file.write_bytes(raw)

        target = _new_workspace(client, auth_headers, "恢复目标", ["tables"])
        with archive_file.open("rb") as fh:
            r = client.post(
                f"{WS}/{target['id']}/restore",
                files={"file": ("restore.tar.gz", fh, "application/gzip")},
                headers=auth_headers,
            )
        assert r.status_code == 200, r.text
        assert r.json()["errors"] == []
        detail = client.get(f"{WS}/{target['id']}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        assert detail.json()["modules"] == ["documents"]


class TestLegacyBackupImport:
    def test_v11_workspace_type_mapped(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        """≤v11 备份的 workspace_type 按映射回填（ADR 0080 D5/D7）."""
        data = {
            "version": "11",
            "tables": [],
            "workspace": {"name": "旧文档工作区", "workspace_type": "doc"},
        }
        r = client.post(f"{WS}/import", json={"json_data": data}, headers=auth_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["workspace"]["modules"] == ["documents", "design"]
        assert body["errors"] == []

    def test_unknown_workspace_type_falls_back_with_error(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        data = {
            "version": "11",
            "tables": [],
            "workspace": {"name": "未知类型", "workspace_type": "bogus"},
        }
        r = client.post(f"{WS}/import", json={"json_data": data}, headers=auth_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["workspace"]["modules"] == ALL
        assert any("workspace_type" in e for e in body["errors"])

    def test_no_meta_defaults_all(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        data = {"version": "11", "tables": [], "workspace": {"name": "无类型"}}
        r = client.post(f"{WS}/import", json={"json_data": data}, headers=auth_headers)
        assert r.status_code == 201, r.text
        assert r.json()["workspace"]["modules"] == ALL


class TestArchiveInspect:
    """导入前预检：归档元信息 + 同名 owner 工作区（决定是否提供覆盖恢复）."""

    def test_inspect_returns_meta_and_existing_target(
        self, client: TestClient, auth_headers: dict[str, str], tmp_path: Path
    ) -> None:
        ws = _new_workspace(client, auth_headers, "预检归档", ["tables", "documents"])
        raw = _export_archive(client, auth_headers, ws["id"])
        archive_file = tmp_path / "inspect.tar.gz"
        archive_file.write_bytes(raw)

        with archive_file.open("rb") as fh:
            r = client.post(
                f"{WS}/import/archive/inspect",
                files={"file": ("inspect.tar.gz", fh, "application/gzip")},
                headers=auth_headers,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["workspace_name"] == "预检归档"
        assert body["backup_version"] == "13"
        assert body["include_secrets"] is True
        assert body["stats"]["tables"] == 0
        assert body["existing_workspace"] == {"id": ws["id"], "name": "预检归档", "role": "owner"}

    def test_inspect_without_existing_target(
        self, client: TestClient, auth_headers: dict[str, str], tmp_path: Path
    ) -> None:
        ws = _new_workspace(client, auth_headers, "已删除来源", ["tables"])
        raw = _export_archive(client, auth_headers, ws["id"])
        assert client.delete(f"{WS}/{ws['id']}", headers=auth_headers).status_code in (200, 204)

        archive_file = tmp_path / "gone.tar.gz"
        archive_file.write_bytes(raw)
        with archive_file.open("rb") as fh:
            r = client.post(
                f"{WS}/import/archive/inspect",
                files={"file": ("gone.tar.gz", fh, "application/gzip")},
                headers=auth_headers,
            )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["workspace_name"] == "已删除来源"
        assert body["existing_workspace"] is None

    def test_inspect_rejects_invalid_archive(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        r = client.post(
            f"{WS}/import/archive/inspect",
            files={"file": ("bad.tar.gz", b"not-a-tar", "application/gzip")},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text
