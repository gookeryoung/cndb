"""行级 / 字段级权限的端到端验证（记录列表接口）.

**为什么需要**：表级权限行 `TablePermission` 曾用 `db.get(TablePermission, table.id)`（按主键）取，
会读到**别的表**的权限行 —— 后果是 A 表被套用了 B 表的 `row_filters` / `hidden_fields`，
或该生效的规则没生效。单元层已锁定（tests/test_table_permission_isolation.py），
这里再走一遍**真实接口**，确认用户最终看到的数据行/字段确实被正确裁剪：

1. 未配置权限行的表：不受任何行过滤 / 字段隐藏影响（关键回归）；
2. 配置了 `row_filters` 的表：只返回命中条件的行；
3. 配置了 `hidden_fields` 的表：对相应角色隐藏字段，另一张表不受影响；
4. 工作区 OWNER 不受表级隐藏影响（可管理）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import TablePermission
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _make_user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _make_user(db, "rowperm_owner")
        self.ws = Workspace(name="RowPermWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.viewer = _make_user(db, "rowperm_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _create_table(client: TestClient, env: Env, name: str) -> dict:
    r = client.post(
        TABLES.format(ws=env.ws.id),
        json={"name": name, "description": ""},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code == 201, r.text
    return r.json()


def _add_field(client: TestClient, env: Env, table_id: int, name: str, order: int) -> None:
    r = client.post(
        f"{TABLES.format(ws=env.ws.id)}/{table_id}/fields",
        json={"name": name, "field_type": "text", "order": order},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code in (200, 201), r.text


def _create_row(client: TestClient, env: Env, table_id: int, values: dict) -> int:
    r = client.post(
        f"{TABLES.format(ws=env.ws.id)}/{table_id}/records",
        json={"values": values},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code in (200, 201), r.text
    return int(r.json()["id"])


def _list_rows(client: TestClient, env: Env, table_id: int, username: str) -> list[dict]:
    r = client.post(
        f"{TABLES.format(ws=env.ws.id)}/{table_id}/records/list",
        json={"limit": 50, "offset": 0},
        headers=_login(client, username),
    )
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _setup_two_tables(client: TestClient, db: Session) -> tuple[Env, dict, dict]:
    env = Env(db)
    open_table = _create_table(client, env, "无权限行表")
    restricted = _create_table(client, env, "带行过滤表")
    for tid in (open_table["id"], restricted["id"]):
        _add_field(client, env, tid, "status", 1)
        _add_field(client, env, tid, "secret_note", 2)
    _create_row(client, env, open_table["id"], {"status": "secret", "secret_note": "A-机密"})
    _create_row(client, env, open_table["id"], {"status": "public", "secret_note": "A-公开"})
    _create_row(client, env, restricted["id"], {"status": "secret", "secret_note": "B-机密"})
    _create_row(client, env, restricted["id"], {"status": "public", "secret_note": "B-公开"})

    # 仅"带行过滤表"配置：只允许看 status=public，并对 viewer 隐藏 secret_note
    db.add(
        TablePermission(
            table_id=restricted["id"],
            read_role="viewer",
            hidden_fields={"viewer": ["secret_note"]},
            row_filters=[{"field_name": "status", "op": "=", "value": "public"}],
            row_filter_type="AND",
        )
    )
    db.commit()
    return env, open_table, restricted


class TestRowLevelPermissionsEndToEnd:
    def test_table_without_permission_row_is_unfiltered(self, client, db):
        """关键回归：没有权限行的表绝不能套用别的表的行过滤/字段隐藏."""
        env, open_table, _restricted = _setup_two_tables(client, db)

        rows = _list_rows(client, env, open_table["id"], env.viewer.username)
        assert len(rows) == 2, rows
        statuses = {r["status"] for r in rows}
        assert statuses == {"secret", "public"}
        # 字段未被隐藏
        assert all(r.get("secret_note") for r in rows)

    def test_configured_table_applies_row_filter_and_field_hiding(self, client, db):
        env, _open_table, restricted = _setup_two_tables(client, db)

        rows = _list_rows(client, env, restricted["id"], env.viewer.username)
        assert len(rows) == 1, rows
        assert rows[0]["status"] == "public"
        # 隐藏字段对 viewer 不可见
        assert "secret_note" not in rows[0] or rows[0].get("secret_note") in (None, "")

    def test_row_filters_filter_members_but_owner_bypasses(self, client, db):
        """口径统一后的语义（见 services/core/access.py: row_filters_bypass）.

        - `row_filters` 对**普通成员**生效（这里是 workspace VIEWER）；
        - 表所有者 / 工作区 OWNER / 超管与 `check_action`、`hidden_fields` 的口径一致 —— **豁免**行过滤；
        - `hidden_fields` 仍是按角色键配置：这里只给 viewer 配了隐藏，owner 不受影响。
        """
        env, _open_table, restricted = _setup_two_tables(client, db)

        # 普通成员：只看到命中行过滤的那一行
        viewer_rows = _list_rows(client, env, restricted["id"], env.viewer.username)
        assert [r["status"] for r in viewer_rows] == ["public"], viewer_rows

        # 工作区 OWNER（本用例中也是表所有者）：豁免行过滤，看到全部行与全部字段
        owner_rows = _list_rows(client, env, restricted["id"], env.owner.username)
        assert sorted(r["status"] for r in owner_rows) == ["public", "secret"], owner_rows
        assert any(r.get("secret_note") == "B-机密" for r in owner_rows)

    def test_row_filter_does_not_leak_to_other_table_after_update(self, client, db):
        """先查无权限行的表（可能进缓存/反射），再改另一表权限，前者仍不受影响."""
        env, open_table, restricted = _setup_two_tables(client, db)
        assert len(_list_rows(client, env, open_table["id"], env.viewer.username)) == 2

        perm = db.query(TablePermission).filter(TablePermission.table_id == restricted["id"]).first()
        perm.row_filters = [{"field_name": "status", "op": "=", "value": "secret"}]
        db.commit()

        # 受限表随配置变化
        restricted_rows = _list_rows(client, env, restricted["id"], env.viewer.username)
        assert [r["status"] for r in restricted_rows] == ["secret"]
        # 无权限行的表依旧完整
        assert len(_list_rows(client, env, open_table["id"], env.viewer.username)) == 2
