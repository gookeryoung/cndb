"""需求 0126：工作区贡献统计（按编辑者，含曾为编辑者）."""

from __future__ import annotations

import datetime as dt

from cndb.plugins.accounts.models import User
from cndb.plugins.design.models import DesignDesign, DesignDesignVersion
from cndb.plugins.documents.models import Document, DocumentVersion
from cndb.plugins.tables.models import AuditLog, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

WS = "/api/v1/workspaces"


def _user(db, username: str, nickname: str = "") -> User:
    user = User(username=username, nickname=nickname or username)
    user.set_password("passw0rd")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _workspace(db, owner: User, name: str = "贡献统计") -> Workspace:
    ws = Workspace(name=name, created_by_id=owner.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    return ws


def _member(db, ws: Workspace, user: User, role: WorkspaceRole, *, pinned: bool = False) -> None:
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role, pinned=pinned))
    db.commit()


def _login(client, username: str) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": "passw0rd"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _add_audit(db, table: DataTable, action: str, actor: User | None, at: dt.datetime) -> None:
    db.add(
        AuditLog(
            table_id=table.id,
            action=action,
            actor_id=actor.id if actor else None,
            detail={},
            created_at=at,
        )
    )
    db.commit()


def _add_doc(db, ws: Workspace, author: User, edits: list[tuple[User, dt.datetime]]) -> Document:
    doc = Document(
        workspace_id=ws.id,
        title="文档",
        slug=f"doc-{ws.id}-{author.id}-{len(edits)}",
        created_by_id=author.id,
        created_at=dt.datetime(2026, 1, 1, 8, 0),
    )
    db.add(doc)
    db.flush()
    version_time = dt.datetime(2026, 1, 1, 8, 0)
    db.add(
        DocumentVersion(
            document_id=doc.id,
            version_number=1,
            content="v1",
            created_by_id=author.id,
            created_at=version_time,
        )
    )
    for number, (editor, at) in enumerate(edits, start=2):
        db.add(
            DocumentVersion(
                document_id=doc.id,
                version_number=number,
                content=f"v{number}",
                created_by_id=editor.id,
                created_at=at,
            )
        )
    db.commit()
    return doc


def _add_design(db, ws: Workspace, author: User, edits: list[tuple[User, dt.datetime]]) -> DesignDesign:
    design = DesignDesign(
        workspace_id=ws.id,
        title=f"设计-{author.id}",
        file_key=f"k-{ws.id}-{author.id}",
        content="root=1;",
        created_by_id=author.id,
        created_at=dt.datetime(2026, 1, 2, 8, 0),
    )
    db.add(design)
    db.flush()
    db.add(
        DesignDesignVersion(
            design_id=design.id,
            workspace_id=ws.id,
            version_number=1,
            content="root=1;",
            created_by_id=author.id,
            created_at=dt.datetime(2026, 1, 2, 8, 0),
        )
    )
    for number, (editor, at) in enumerate(edits, start=2):
        db.add(
            DesignDesignVersion(
                design_id=design.id,
                workspace_id=ws.id,
                version_number=number,
                content="root=1;",
                created_by_id=editor.id,
                created_at=at,
            )
        )
    db.commit()
    return design


def _seed(db, client) -> tuple[Workspace, dict[str, User]]:
    owner = _user(db, "contrib-owner")
    editor = _user(db, "contrib-editor")
    idle_editor = _user(db, "contrib-idle-editor")
    former = _user(db, "contrib-former")  # 当前 viewer，曾编辑
    removed = _user(db, "contrib-removed")  # 已移出，曾编辑
    outsider = _user(db, "contrib-outsider")

    ws = _workspace(db, owner)
    _member(db, ws, editor, WorkspaceRole.EDITOR)
    _member(db, ws, idle_editor, WorkspaceRole.EDITOR)
    _member(db, ws, former, WorkspaceRole.VIEWER)

    table = DataTable(workspace_id=ws.id, name="需求表", db_table_name=f"t_contrib_{ws.id}")
    db.add(table)
    db.commit()
    db.refresh(table)

    morning = dt.datetime(2026, 1, 1, 9, 0)
    _add_audit(db, table, "create", owner, morning)
    _add_audit(db, table, "create", owner, morning)
    _add_audit(db, table, "update", owner, morning)
    _add_audit(db, table, "create", editor, morning)
    _add_audit(db, table, "update", former, dt.datetime(2026, 1, 3, 9, 0))
    _add_audit(db, table, "update", former, dt.datetime(2026, 1, 3, 9, 0))
    _add_audit(db, table, "create", None, morning)  # 历史行 / 系统写入：不计入

    trashed = DataTable(
        workspace_id=ws.id,
        name="回收站表",
        db_table_name=f"t_contrib_trash_{ws.id}",
        trashed=True,
        trashed_at=morning,
    )
    db.add(trashed)
    db.commit()
    db.refresh(trashed)
    _add_audit(db, trashed, "create", owner, morning)  # 回收站表：不计入

    _add_doc(db, ws, former, [(editor, dt.datetime(2026, 1, 4, 9, 0)), (owner, dt.datetime(2026, 1, 4, 10, 0))])
    _add_design(db, ws, removed, [(removed, dt.datetime(2026, 1, 5, 9, 0)), (editor, dt.datetime(2026, 1, 5, 10, 0))])
    db.commit()
    return ws, {
        "owner": owner,
        "editor": editor,
        "idle": idle_editor,
        "former": former,
        "removed": removed,
        "outsider": outsider,
    }


class TestWorkspaceContributions:
    def test_contributions_include_editors_and_former_editors(self, client, db):
        ws, users = _seed(db, client)
        headers = _login(client, "contrib-owner")

        r = client.get(f"{WS}/{ws.id}/stats/contributions", headers=headers)
        assert r.status_code == 200, r.text
        payload = r.json()
        assert payload["generated_at"]
        items = {item["user_id"]: item for item in payload["items"]}

        # owner：3 行数据 + 1 次文档保存
        owner = items[users["owner"].id]
        assert owner["role"] == "owner"
        assert owner["is_member"] is True
        assert owner["is_former_editor"] is False
        assert owner["rows_created"] == 2
        assert owner["rows_updated"] == 1
        assert owner["documents_edited"] == 1
        assert owner["total"] == 4

        # editor：1 行新建 + 1 次文档保存 + 1 次设计保存
        editor = items[users["editor"].id]
        assert editor["rows_created"] == 1
        assert editor["documents_edited"] == 1
        assert editor["designs_edited"] == 1
        assert editor["total"] == 3
        assert editor["is_former_editor"] is False

        # 当前 editor 即使 0 贡献也展示
        idle = items[users["idle"].id]
        assert idle["total"] == 0
        assert idle["role"] == "editor"
        assert idle["last_active_at"] is None

        # editor → viewer：历史活动推断为曾为编辑者
        former = items[users["former"].id]
        assert former["role"] == "viewer"
        assert former["is_member"] is True
        assert former["is_former_editor"] is True
        assert former["rows_updated"] == 2
        assert former["documents_created"] == 1
        assert former["total"] == 3

        # 已移出：仍展示并标记曾为编辑者
        removed = items[users["removed"].id]
        assert removed["role"] is None
        assert removed["is_member"] is False
        assert removed["is_former_editor"] is True
        assert removed["designs_created"] == 1
        assert removed["designs_edited"] == 1
        assert removed["total"] == 2

        # 非成员且无活动：不出现
        assert users["outsider"].id not in items

        # 合计降序；最近活动时间取自各活动源
        totals = [item["total"] for item in payload["items"]]
        assert totals == sorted(totals, reverse=True)
        assert removed["last_active_at"].startswith("2026-01-05T09:00")

    def test_contributions_require_workspace_member(self, client, db):
        ws, _users = _seed(db, client)
        headers = _login(client, "contrib-outsider")
        r = client.get(f"{WS}/{ws.id}/stats/contributions", headers=headers)
        assert r.status_code == 404

    def test_contributions_missing_workspace(self, client, db):
        _seed(db, client)
        headers = _login(client, "contrib-owner")
        r = client.get(f"{WS}/999999/stats/contributions", headers=headers)
        assert r.status_code == 404

    def test_empty_workspace_returns_current_editors(self, client, db):
        user = _user(db, "contrib-empty-owner")
        ws = _workspace(db, user, name="空工作区")
        headers = _login(client, "contrib-empty-owner")
        r = client.get(f"{WS}/{ws.id}/stats/contributions", headers=headers)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["user_id"] == user.id
        assert items[0]["total"] == 0


class TestRowAuditActor:
    def test_create_and_update_row_record_actor(self, client, auth_headers, db):
        ws = client.post(WS, headers=auth_headers, json={"name": "行审计归属"}).json()
        wid = ws["id"]
        table = client.post(f"{WS}/{wid}/tables", headers=auth_headers, json={"name": "t_actor"}).json()
        tid = table["id"]
        client.post(
            f"{WS}/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "title", "field_type": "text", "order": 0},
        )

        created = client.post(
            f"{WS}/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"title": "第一行"}},
        )
        assert created.status_code == 201, created.text
        record_id = created.json()["id"]
        updated = client.patch(
            f"{WS}/{wid}/tables/{tid}/records/{record_id}",
            headers=auth_headers,
            json={"values": {"title": "改过"}},
        )
        assert updated.status_code == 200, updated.text

        user = db.query(User).filter(User.username == "testuser").one()
        rows = (
            db.query(AuditLog)
            .filter(AuditLog.table_id == tid, AuditLog.action.in_(("create", "update")))
            .order_by(AuditLog.id)
            .all()
        )
        assert [row.action for row in rows] == ["create", "update"]
        assert all(row.actor_id == user.id for row in rows)

    def test_row_audit_actor_feeds_contributions(self, client, auth_headers, db):
        ws = client.post(WS, headers=auth_headers, json={"name": "行贡献"}).json()
        wid = ws["id"]
        table = client.post(f"{WS}/{wid}/tables", headers=auth_headers, json={"name": "t_feed"}).json()
        tid = table["id"]
        client.post(
            f"{WS}/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "title", "field_type": "text", "order": 0},
        )
        client.post(
            f"{WS}/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"title": "贡献行"}},
        )

        r = client.get(f"{WS}/{wid}/stats/contributions", headers=auth_headers)
        assert r.status_code == 200, r.text
        user = db.query(User).filter(User.username == "testuser").one()
        item = next(item for item in r.json()["items"] if item["user_id"] == user.id)
        assert item["rows_created"] == 1
        assert item["total"] == 1
