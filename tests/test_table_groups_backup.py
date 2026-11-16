"""表分组随工作区备份往返（需求 0137）.

覆盖：归档导出包含 ``table_groups`` 与 ``tables[].group_id``，覆盖恢复后
分组重建且表重新挂回对应分组；旧版备份缺少分组键时按未分组处理。
"""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

WS = "/api/v1/workspaces"
TABLES = "/api/v1/workspaces/{wid}/tables"
GROUPS = "/api/v1/workspaces/{wid}/table-groups"


def _new_workspace(client: TestClient, headers: dict[str, str], name: str) -> int:
    r = client.post(WS, json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_table_groups_roundtrip(client, auth_headers):
    wid = _new_workspace(client, auth_headers, "分组备份源")
    group = client.post(GROUPS.format(wid=wid), json={"name": "销售"}, headers=auth_headers)
    assert group.status_code == 201, group.text
    gid = group.json()["id"]
    table = client.post(TABLES.format(wid=wid), json={"name": "客户", "group_id": gid}, headers=auth_headers)
    assert table.status_code == 201, table.text

    exported = client.get(f"{WS}/{wid}/export/archive", headers=auth_headers)
    assert exported.status_code == 200, exported.text

    restored = client.post(
        f"{WS}/{wid}/restore",
        files={"file": ("backup.tar.gz", io.BytesIO(exported.content), "application/gzip")},
        headers=auth_headers,
    )
    assert restored.status_code == 200, restored.text
    body = restored.json()
    assert body["errors"] == [], body["errors"]
    assert body["imported_tables"] == 1

    groups = client.get(GROUPS.format(wid=wid), headers=auth_headers).json()
    real = [g for g in groups if not g["is_ungrouped"]]
    assert [g["name"] for g in real] == ["销售"]
    tables = client.get(TABLES.format(wid=wid), headers=auth_headers).json()
    assert [t["name"] for t in tables] == ["客户"]
    assert tables[0]["group_id"] == real[0]["id"]


def test_export_payload_contains_groups(client, auth_headers):
    wid = _new_workspace(client, auth_headers, "分组备份结构")
    gid = client.post(GROUPS.format(wid=wid), json={"name": "运营"}, headers=auth_headers).json()["id"]
    tid = client.post(TABLES.format(wid=wid), json={"name": "指标", "group_id": gid}, headers=auth_headers).json()["id"]

    # v8 JSON 出口保持旧结构（不带分组键）
    v8 = client.get(f"{WS}/{wid}/export", headers=auth_headers).json()
    assert "table_groups" not in v8
    assert all("group_id" not in t for t in v8["tables"])

    # 归档内 backup.json 携带分组与 group_id
    from cndb.plugins.workspaces.services.workspace_backup import parse_workspace_archive

    raw = client.get(f"{WS}/{wid}/export/archive", headers=auth_headers).content
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as fh:
        fh.write(raw)
        path = Path(fh.name)
    archive = parse_workspace_archive(path)
    try:
        real = [g for g in archive.backup["table_groups"] if not g.get("is_ungrouped")]
        assert [g["name"] for g in real] == ["运营"]
        assert archive.backup["tables"][0]["group_id"] == gid
        assert archive.backup["tables"][0]["id"] == tid
    finally:
        archive.cleanup()
        path.unlink(missing_ok=True)
