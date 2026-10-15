"""表列表统计的批量预取 + preferences 的表可读性校验（第 3 项）.

两部分都是"低危硬化"，但都有明确可测的行为：

1. **统计字段去 N+1**：列表此前对每张表各查 `field_count` / `view_count` / `record_count`
   （≈3N 次查询）。现改为分组查询 + 一次 UNION ALL，查询数不随表数增长；本文件同时校验
   统计值仍正确（避免"快了但算错"）。
2. **preferences active-view**：此前只校验"表存在"，任何登录用户都能拿到任意表 id 的
   偏好回显（存在性提示）。现要求 `TableAction.READ`，不可读 → 403。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from cndb.core.cache import list_cache
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"


def _login(client: TestClient, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


class Env:
    def __init__(self, db: Session) -> None:
        self.owner = _user(db, "stats_owner")
        self.ws = Workspace(name="StatsWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.viewer = _user(db, "stats_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _table_with_stats(client: TestClient, env: Env, *, name: str, rows: int = 3) -> int:
    auth = _login(client, env.owner.username)
    r = client.post(TABLES.format(ws=env.ws.id), json={"name": name, "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
    for idx, fname in enumerate(["名称", "备注"]):
        client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/fields",
            json={"name": fname, "field_type": "text", "order": idx},
            headers=auth,
        )
    for i in range(rows):
        client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/records",
            json={"values": {"名称": f"行{i}"}},
            headers=auth,
        )
    client.post(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/views", json={"name": "默认视图", "view_type": "grid"}, headers=auth
    )
    return tid


class TestTableListStatsPrefetched:
    def test_stats_values_are_correct(self, client, db):
        env = Env(db)
        _table_with_stats(client, env, name="统计表A", rows=3)
        _table_with_stats(client, env, name="统计表B", rows=1)
        list_cache.clear()

        rows = client.get(TABLES.format(ws=env.ws.id), headers=_login(client, env.owner.username)).json()
        by_name = {r["name"]: r for r in rows}
        assert by_name["统计表A"]["field_count"] == 2
        assert by_name["统计表A"]["record_count"] == 3
        assert by_name["统计表A"]["view_count"] >= 1
        assert by_name["统计表B"]["record_count"] == 1

    def test_query_count_does_not_scale_with_table_count(self, client, db):
        """列表查询数与表数无关（回归 N+1：此前每表 3 次统计查询）."""
        env = Env(db)
        for i in range(6):
            _table_with_stats(client, env, name=f"规模表{i}", rows=1)
        auth = _login(client, env.owner.username)

        statements: list[str] = []
        engine = db.get_bind()

        def _before(_conn: object, _cursor: object, statement: str, *_a: object, **_kw: object) -> None:
            statements.append(" ".join(statement.split()))

        list_cache.clear()
        event.listen(engine, "before_cursor_execute", _before)
        try:
            r = client.get(TABLES.format(ws=env.ws.id), headers=auth)
        finally:
            event.remove(engine, "before_cursor_execute", _before)

        assert r.status_code == 200, r.text
        assert len(r.json()) == 6
        # 固定开销：工作区角色 + 成员映射 + 权限行 + 字段分组 + 视图分组 + 行数 UNION + owner/member_count/my_member
        assert len(statements) <= 14, f"6 张表用了 {len(statements)} 次查询，疑似仍有 N+1"


class TestPreferencesRequiresTableRead:
    def test_restricted_table_preference_is_denied(self, client, db):
        env = Env(db)
        tid = _table_with_stats(client, env, name="仅所有者表")
        r = client.put(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/permissions",
            json={"read_role": "owner"},
            headers=_login(client, env.owner.username),
        )
        assert r.status_code in (200, 201), r.text

        url = f"/api/v1/accounts/preferences/tables/{tid}/active-view"
        viewer_status = client.get(url, headers=_login(client, env.viewer.username)).status_code
        assert viewer_status == 403, f"普通成员不应能查询受限表的偏好：{viewer_status}"

        # 所有者可读 → 200
        assert client.get(url, headers=_login(client, env.owner.username)).status_code == 200

    def test_unknown_table_still_404(self, client, db):
        env = Env(db)
        url = "/api/v1/accounts/preferences/tables/999999/active-view"
        assert client.get(url, headers=_login(client, env.owner.username)).status_code == 404
