"""Bug 回归测试 —— 提交后正确性检查发现的两个缺陷.

Bug 1: _authenticate_jwt 遇到 sub 非合法 int 时 ValueError → 500.
Bug 2: records.create_row 在 set_links 失败前主行已 commit，返回 500 但主行入库.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from jose import jwt


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
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_rb"})
    wid = ws.json()["id"]

    # Target table with real row
    tgt = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "tgt_rb"},
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

    # Source table with link field
    src = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "src_rb"},
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
