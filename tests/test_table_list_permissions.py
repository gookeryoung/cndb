"""数据表列表的权限可见性测试 —— 受限表标记 + 批量判定与逐表判定等价.

背景：
1. 列表此前返回工作区全部表（仅按 trashed 过滤），而详情/记录接口按 `TableAction.READ` 拦截，
   两者不一致 → 无权限用户仍能看到受限表的名称/成员数。上一轮已改为按 READ 过滤；
   本轮补充**受限标记**（`read_role` / `is_restricted`）并修正 `my_access` 的语义。
2. 逐表 `check_action` 会各产生 ~3 次查询（工作区角色 + TableMember + TablePermission），
   本轮改为一次性预取 + 纯计算判定；本文件锁定"批量判定 == 逐表判定"，
   避免优化引入语义漂移。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, TableMember, TablePermission
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_action,
    preload_table_access,
)
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
        self.owner = _user(db, "tl_owner")
        self.ws = Workspace(name="TableListWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _user(db, "tl_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _user(db, "tl_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _make_table(client: TestClient, env: Env, name: str) -> dict:
    r = client.post(
        TABLES.format(ws=env.ws.id),
        json={"name": name, "description": ""},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code == 201, r.text
    return r.json()


class TestListExposesReadRole:
    def test_open_table_is_not_restricted_and_my_access_is_read(self, client, db):
        env = Env(db)
        _make_table(client, env, "开放表")
        rows = client.get(TABLES.format(ws=env.ws.id), headers=_login(client, env.viewer.username)).json()
        assert [r["name"] for r in rows] == ["开放表"]
        row = rows[0]
        assert row["read_role"] == ""
        assert row["is_restricted"] is False
        # 工作区成员默认可读：my_access 不再错误地显示为 none
        assert row["my_access"] == "read"

    def test_restricted_table_hidden_from_viewer_but_flagged_for_owner(self, client, db):
        env = Env(db)
        open_table = _make_table(client, env, "人人可读")
        restricted = _make_table(client, env, "仅所有者可读")
        r = client.put(
            f"{TABLES.format(ws=env.ws.id)}/{restricted['id']}/permissions",
            json={"read_role": "owner"},
            headers=_login(client, env.owner.username),
        )
        assert r.status_code in (200, 201), r.text

        viewer_rows = client.get(TABLES.format(ws=env.ws.id), headers=_login(client, env.viewer.username)).json()
        assert [r["name"] for r in viewer_rows] == ["人人可读"]
        assert all(not r["is_restricted"] for r in viewer_rows)

        owner_rows = client.get(TABLES.format(ws=env.ws.id), headers=_login(client, env.owner.username)).json()
        by_name = {r["name"]: r for r in owner_rows}
        assert by_name["人人可读"]["is_restricted"] is False
        assert by_name["仅所有者可读"]["is_restricted"] is True
        assert by_name["仅所有者可读"]["read_role"] == "owner"
        assert by_name["仅所有者可读"]["my_access"] == "owner"
        assert open_table["id"] in [r["id"] for r in owner_rows]

    def test_editor_threshold_is_restricted_for_viewer_but_visible_to_editor(self, client, db):
        env = Env(db)
        table = _make_table(client, env, "编辑者及以上可读")
        r = client.put(
            f"{TABLES.format(ws=env.ws.id)}/{table['id']}/permissions",
            json={"read_role": "editor"},
            headers=_login(client, env.owner.username),
        )
        assert r.status_code in (200, 201), r.text

        viewer_rows = client.get(TABLES.format(ws=env.ws.id), headers=_login(client, env.viewer.username)).json()
        assert viewer_rows == []

        editor_rows = client.get(TABLES.format(ws=env.ws.id), headers=_login(client, env.editor.username)).json()
        assert [r["name"] for r in editor_rows] == ["编辑者及以上可读"]
        assert editor_rows[0]["is_restricted"] is True  # 对普通成员受限（编辑器能看到）


class TestPreloadEquivalence:
    """批量预取判定必须与逐表 check_action 完全一致（防止优化引入权限漂移）."""

    def _make_matrix(self, db: Session, env: Env) -> list[DataTable]:
        tables: list[DataTable] = []
        for idx, cfg in enumerate(
            [
                {},  # 无权限行、无成员记录
                {"read_role": "viewer"},
                {"read_role": "editor"},
                {"read_role": "owner"},
                {"read_role": "OWNER"},  # 大写（历史数据）
                {"read_role": "not-a-role"},  # 非法
                {"read_role": "editor", "edit_records_role": "owner"},
            ]
        ):
            t = DataTable(
                workspace_id=env.ws.id,
                name=f"矩阵{idx}",
                db_table_name=f"t_matrix_{idx}",
                owner_id=env.owner.id,
            )
            db.add(t)
            db.flush()
            if cfg:
                db.add(TablePermission(table_id=t.id, **cfg))
            tables.append(t)
        # 表成员授权：viewer 被显式授权 write（应优先于阈值判定）
        member_table = DataTable(
            workspace_id=env.ws.id, name="成员授权表", db_table_name="t_matrix_member", owner_id=env.owner.id
        )
        db.add(member_table)
        db.flush()
        db.add(TablePermission(table_id=member_table.id, read_role="owner"))
        db.add(TableMember(table_id=member_table.id, user_id=env.viewer.id, role="write"))
        tables.append(member_table)
        db.commit()
        return tables

    def test_preload_matches_check_action_for_all_actions(self, db):
        env = Env(db)
        tables = self._make_matrix(db, env)
        for user in (env.viewer, env.editor, env.owner):
            preload = preload_table_access(db, tables, user)
            for t in tables:
                for action in (TableAction.READ, TableAction.EDIT_RECORDS, TableAction.EDIT_SCHEMA):
                    assert preload.check(db, t, user, action) == check_action(db, t, user, action), (
                        t.name,
                        user.username,
                        action,
                    )

    def test_member_grant_overrides_threshold(self, db):
        """成员 write 授权优先于 read_role=owner 的阈值（保持既有优先级语义）."""
        env = Env(db)
        tables = self._make_matrix(db, env)
        member_table = next(t for t in tables if t.name == "成员授权表")
        assert check_action(db, member_table, env.viewer, TableAction.READ) is True
        assert check_action(db, member_table, env.viewer, TableAction.EDIT_RECORDS) is True

    def test_preload_query_count_is_constant(self, db):
        """预取 + N 张表判定：查询数不随表数增长（回归 N+1）."""
        env = Env(db)
        self._make_matrix(db, env)
        # 重新查询以获得**未过期**的实例：_make_matrix 末尾 commit 会让 ORM 实例过期，
        # 之后访问属性会逐条 SELECT —— 那是测试写法问题，不是生产路径（路由里是刚查出来的对象）。
        tables = db.query(DataTable).filter(DataTable.workspace_id == env.ws.id).all()
        assert len(tables) >= 8

        engine = db.get_bind()
        counter = {"n": 0}

        def _before(*_args: object, **_kwargs: object) -> None:
            counter["n"] += 1

        event.listen(engine, "before_cursor_execute", _before)
        try:
            preload = preload_table_access(db, tables, env.viewer)
            for table in tables:
                preload.check(db, table, env.viewer, TableAction.READ)
        finally:
            event.remove(engine, "before_cursor_execute", _before)

        # 工作区查询 1 + 成员映射 1 + 权限行 1 = 3（判定全部为纯计算，与表数无关）
        assert counter["n"] <= 4, f"预取判定产生了 {counter['n']} 次查询，疑似 N+1"
