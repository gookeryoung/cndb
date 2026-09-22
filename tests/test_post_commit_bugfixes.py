"""Bug 回归测试 —— 提交后正确性检查发现的两个缺陷.

Bug 1: _authenticate_jwt 遇到 sub 非合法 int 时 ValueError → 500.
Bug 2: records 的 link 目标预校验（主行提交前校验 link 目标存在）——
       覆盖 create_row / update_row / bulk_create / bulk_update / bulk_update_rows 五条路径，
       确保预校验失败时返回 400 且主行/物理列不留脏数据.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from jose import jwt
from sqlalchemy import select


def _make_ws_with_link_pair(client, auth_headers, suffix: str) -> tuple[int, int, int]:
    """建 tgt/src 两张表（src 含 link 字段 ref 指向 tgt），返回 (wid, tid_src, tgt_row_id)."""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": f"ws_rb_{suffix}"})
    wid = ws.json()["id"]

    # Target table with real row
    tgt = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": f"tgt_rb_{suffix}"},
    )
    tid_tgt = tgt.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_tgt}/fields",
        headers=auth_headers,
        json={"name": "n", "field_type": "text", "order": 0},
    )
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_tgt}/records",
        headers=auth_headers,
        json={"values": {"n": "real"}},
    )
    rows = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_tgt}/records/list",
        headers=auth_headers,
        json={"offset": 0, "limit": 10},
    ).json()
    tgt_row_id = rows["items"][0]["id"]

    # Source table with link field
    src = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": f"src_rb_{suffix}"},
    )
    tid_src = src.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/fields",
        headers=auth_headers,
        json={"name": "d", "field_type": "text", "order": 0},
    )
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/fields",
        headers=auth_headers,
        json={
            "name": "ref",
            "field_type": "link",
            "order": 1,
            "config": {"target_table_id": tid_tgt},
        },
    )
    return wid, tid_src, tgt_row_id


def test_authenticate_jwt_sub_non_int_returns_none(db_engine, db) -> None:
    """Bug 1: _authenticate_jwt 遇到 sub 非合法 int 时应返回 None."""
    from cndb.api.deps import _authenticate_jwt

    bad_token = jwt.encode(
        {
            "sub": "abc",
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(minutes=60)).timestamp()),
        },
        key="cndb-dev-secret-change-in-production",
        algorithm="HS256",
    )

    user = _authenticate_jwt(bad_token, db)
    assert user is None, "sub 非 int 应返回 None，不应抛 500"


def test_create_row_invalid_link_target_not_persisted(client, auth_headers) -> None:
    """Bug 2: create_row 传入不存在的 link target id 时，主行不应入库."""
    wid, tid_src, _ = _make_ws_with_link_pair(client, auth_headers, "create")

    # Try POST with non-existent target id
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records",
        headers=auth_headers,
        json={"values": {"d": "oops", "ref": [99999]}},
    )
    assert r.status_code == 400, f"应返回 400（link target 无效），但收到 {r.status_code}。Body: {r.text[:200]}"

    # Critical: source table must have zero rows — no orphan commits
    rows = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/list",
        headers=auth_headers,
        json={"offset": 0, "limit": 10},
    )
    assert rows.status_code == 200, f"list failed: {rows.status_code}"
    body = rows.json()
    assert body["total"] == 0, f"源表不应有残留行，但 total={body['total']} —— Bug 未修：主行已脏提交但 link 写入失败"


def test_update_row_invalid_link_target_not_persisted(client, auth_headers) -> None:
    """Bug 2 变体: update_row 传入不存在的 link target id 时，返回 400 且物理列不被更新."""
    wid, tid_src, _ = _make_ws_with_link_pair(client, auth_headers, "upd")
    rid = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records",
        headers=auth_headers,
        json={"values": {"d": "orig"}},
    ).json()["id"]

    r = client.patch(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/{rid}",
        headers=auth_headers,
        json={"values": {"d": "changed", "ref": [99999]}},
    )
    assert r.status_code == 400, f"应返回 400，但收到 {r.status_code}。Body: {r.text[:200]}"

    row = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/{rid}",
        headers=auth_headers,
    ).json()
    assert row["d"] == "orig", f"物理列不应被更新，但 d={row['d']!r} —— 预校验未在主行提交前拦截"


def test_bulk_create_invalid_link_target_no_partial_rows(client, auth_headers) -> None:
    """Bug 2 变体: bulk_create 混合行（部分 link 目标无效）时，任何主行都不应入库."""
    wid, tid_src, tgt_row_id = _make_ws_with_link_pair(client, auth_headers, "bc")

    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/bulk-create",
        headers=auth_headers,
        json={
            "rows": [
                {"values": {"d": "ok_row", "ref": [tgt_row_id]}},
                {"values": {"d": "bad_row", "ref": [99999]}},
            ]
        },
    )
    assert r.status_code == 400, f"应返回 400，但收到 {r.status_code}。Body: {r.text[:200]}"

    rows = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/list",
        headers=auth_headers,
        json={"offset": 0, "limit": 10},
    ).json()
    assert rows["total"] == 0, (
        f"部分主行已脏提交但后续 link 写入失败：total={rows['total']}，期望 0（预校验应在所有主行提交前整体拦截）"
    )


def test_bulk_update_invalid_link_target_not_applied(client, auth_headers) -> None:
    """Bug 2 变体: bulk_update（N 行共用一组 values）link 目标无效时，物理列不被更新."""
    wid, tid_src, _ = _make_ws_with_link_pair(client, auth_headers, "bu")
    rid1 = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records",
        headers=auth_headers,
        json={"values": {"d": "one"}},
    ).json()["id"]
    rid2 = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records",
        headers=auth_headers,
        json={"values": {"d": "two"}},
    ).json()["id"]

    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/bulk-update",
        headers=auth_headers,
        json={"row_ids": [rid1, rid2], "values": {"d": "changed", "ref": [99999]}},
    )
    assert r.status_code == 400, f"应返回 400，但收到 {r.status_code}。Body: {r.text[:200]}"

    for rid, orig in ((rid1, "one"), (rid2, "two")):
        row = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/{rid}",
            headers=auth_headers,
        ).json()
        assert row["d"] == orig, f"行 {rid} 物理列不应被更新，但 d={row['d']!r}"


def test_bulk_update_rows_invalid_link_target_not_applied(client, auth_headers, db_engine, db) -> None:
    """Bug 2 变体: bulk_update_rows（导入 upsert 分流路径）预校验失败抛 ValueError，物理列不更新."""
    from cndb.plugins.tables.services.core import records as rec
    from cndb.plugins.tables.models import DataTable

    wid, tid_src, _ = _make_ws_with_link_pair(client, auth_headers, "bur")
    rid = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records",
        headers=auth_headers,
        json={"values": {"d": "orig"}},
    ).json()["id"]

    table = db.execute(select(DataTable).where(DataTable.id == tid_src)).scalar_one()
    with pytest.raises(ValueError, match="关联的目标行不存在"):
        rec.bulk_update_rows(
            db_engine,
            table,
            [{"row_id": rid, "values": {"d": "changed", "ref": [99999]}}],
            db=db,
        )

    row = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/{rid}",
        headers=auth_headers,
    ).json()
    assert row["d"] == "orig", f"物理列不应被更新，但 d={row['d']!r}"
