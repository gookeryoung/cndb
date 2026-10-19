"""行级权限规则（tables_rowpermission）判定与读路径接入（ADR 0004，P0）.

覆盖：
1. I3 存量不变：无任何规则时行为与今天一致（仅 row_filters 生效）；
2. `user` + `view`：指定成员额外可见命中行，其他成员不受影响；
3. `member_role` 按**有效档位**匹配（viewer→read，editor→write，无需 TableMember 行）；
4. 读 ⊇ 写（I4）：`edit` 规则命中行同时并入读范围；
5. 管理员豁免（表 owner / 工作区 OWNER）看到全表；
6. 默认档为空时规则读侧不产生额外效果（ADR §7-5）；
7. 规则条件引用当前用户隐藏字段 → 条件静默丢弃（侧信道保护，ADR §7-1）；
8. `applicable_row_rules` 命中口径（user / member_role）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import RowAction, RowPermission, RowSubject, TablePermission
from cndb.plugins.tables.services.core.row_access import applicable_row_rules
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
        self.owner = _make_user(db, "rowrule_owner")
        self.ws = Workspace(name="RowRuleWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _make_user(db, "rowrule_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _make_user(db, "rowrule_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _create_table(client: TestClient, env: Env) -> int:
    r = client.post(
        TABLES.format(ws=env.ws.id),
        json={"name": "行规则表", "description": ""},
        headers=_login(client, env.owner.username),
    )
    assert r.status_code == 201, r.text
    return int(r.json()["id"])


def _setup(client: TestClient, db: Session) -> tuple[Env, int, dict[str, int]]:
    env = Env(db)
    tid = _create_table(client, env)
    auth = _login(client, env.owner.username)
    for order, name in enumerate(["status", "secret_note", "tag"]):
        r = client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/fields",
            json={"name": name, "field_type": "text", "order": order},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
    row_ids: dict[str, int] = {}
    for values in (
        {"status": "public", "secret_note": "A", "tag": "t1"},
        {"status": "secret", "secret_note": "B", "tag": "t2"},
        {"status": "draft", "secret_note": "C", "tag": "t3"},
    ):
        r = client.post(
            f"{TABLES.format(ws=env.ws.id)}/{tid}/records",
            json={"values": values},
            headers=auth,
        )
        assert r.status_code in (200, 201), r.text
        row_ids[values["status"]] = int(r.json()["id"])
    return env, tid, row_ids


def _set_default_bucket(db: Session, table_id: int, *, filters: list[dict], hidden: dict | None = None) -> None:
    """配置默认档（TablePermission.row_filters + hidden_fields）."""
    db.add(
        TablePermission(
            table_id=table_id,
            read_role="viewer",
            hidden_fields=hidden or {},
            row_filters=filters,
            row_filter_type="AND",
        )
    )
    db.commit()


def _add_rule(
    db: Session,
    table_id: int,
    *,
    subject_type: str,
    subject_id: str,
    action: str,
    filters: list[dict],
    filter_type: str = "AND",
) -> None:
    db.add(
        RowPermission(
            table_id=table_id,
            subject_type=subject_type,
            subject_id=subject_id,
            action=action,
            filters=filters,
            filter_type=filter_type,
        )
    )
    db.commit()


def _list_statuses(client: TestClient, env: Env, tid: int, username: str) -> list[str]:
    r = client.post(
        f"{TABLES.format(ws=env.ws.id)}/{tid}/records/list",
        json={"limit": 50, "offset": 0},
        headers=_login(client, username),
    )
    assert r.status_code == 200, r.text
    return sorted(item["status"] for item in r.json()["items"])


class TestNoRulesUnchanged:
    def test_table_without_any_config_sees_all_rows(self, client, db):
        """I3：无默认档、无规则 → 全表可见."""
        env, tid, _rows = _setup(client, db)
        assert _list_statuses(client, env, tid, env.viewer.username) == ["draft", "public", "secret"]

    def test_default_bucket_alone_still_applies(self, client, db):
        """I3：仅默认档（无规则）→ 与今天逐条一致."""
        env, tid, _rows = _setup(client, db)
        _set_default_bucket(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        assert _list_statuses(client, env, tid, env.viewer.username) == ["public"]
        assert _list_statuses(client, env, tid, env.editor.username) == ["public"]


class TestUserRule:
    def test_view_rule_grants_extra_rows_to_target_member(self, client, db):
        env, tid, _rows = _setup(client, db)
        _set_default_bucket(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.viewer.id),
            action=RowAction.VIEW,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        # 被授权成员：默认档 ∪ 命中规则
        assert _list_statuses(client, env, tid, env.viewer.username) == ["public", "secret"]
        # 未授权成员：仅默认档
        assert _list_statuses(client, env, tid, env.editor.username) == ["public"]

    def test_edit_rule_row_is_also_readable(self, client, db):
        """I4 读 ⊇ 写：edit 规则命中行同时并入读范围."""
        env, tid, _rows = _setup(client, db)
        _set_default_bucket(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.viewer.id),
            action=RowAction.EDIT,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        assert _list_statuses(client, env, tid, env.viewer.username) == ["public", "secret"]


class TestMemberRoleRule:
    def test_read_rule_matches_read_tier_only(self, client, db):
        """member_role 按有效档位：viewer→read 命中；editor→write 不命中 read 规则."""
        env, tid, _rows = _setup(client, db)
        _set_default_bucket(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.MEMBER_ROLE,
            subject_id="read",
            action=RowAction.VIEW,
            filters=[{"field_name": "status", "op": "=", "value": "draft"}],
        )
        assert _list_statuses(client, env, tid, env.viewer.username) == ["draft", "public"]
        # editor（EDIT_RECORDS 通过 → write 档）不命中 read 规则
        assert _list_statuses(client, env, tid, env.editor.username) == ["public"]

    def test_write_rule_matches_write_tier(self, client, db):
        env, tid, _rows = _setup(client, db)
        _set_default_bucket(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.MEMBER_ROLE,
            subject_id="write",
            action=RowAction.VIEW,
            filters=[{"field_name": "status", "op": "=", "value": "draft"}],
        )
        assert _list_statuses(client, env, tid, env.editor.username) == ["draft", "public"]
        assert _list_statuses(client, env, tid, env.viewer.username) == ["public"]


class TestAdminBypass:
    def test_table_owner_sees_everything(self, client, db):
        """D3：表 owner 豁免行规则，看到全表."""
        env, tid, _rows = _setup(client, db)
        _set_default_bucket(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.viewer.id),
            action=RowAction.VIEW,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        assert _list_statuses(client, env, tid, env.owner.username) == ["draft", "public", "secret"]


class TestDefaultBucketEmpty:
    def test_rule_read_side_has_no_effect_when_default_open(self, client, db):
        """默认档为空（人人可见全表）→ 规则读侧不产生额外效果（ADR §7-5）."""
        env, tid, _rows = _setup(client, db)
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.viewer.id),
            action=RowAction.VIEW,
            filters=[{"field_name": "status", "op": "=", "value": "public"}],
        )
        # 仍看到全部行（规则未收紧）
        assert _list_statuses(client, env, tid, env.viewer.username) == ["draft", "public", "secret"]


class TestHiddenFieldDegradation:
    def test_rule_condition_on_hidden_field_is_dropped(self, client, db):
        """规则条件引用被隐藏字段 → 条件静默丢弃，规则不额外开放行（侧信道保护）."""
        env, tid, _rows = _setup(client, db)
        _set_default_bucket(
            db,
            tid,
            filters=[{"field_name": "status", "op": "=", "value": "public"}],
            hidden={"viewer": ["tag"]},
        )
        # tag 对 viewer 隐藏 → 该条件被丢弃 → 规则无有效条件 → 仅默认档
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.viewer.id),
            action=RowAction.VIEW,
            filters=[{"field_name": "tag", "op": "=", "value": "t2"}],
        )
        assert _list_statuses(client, env, tid, env.viewer.username) == ["public"]

    def test_visible_field_condition_is_applied(self, client, db):
        """对照：条件引用可见字段时规则正常生效（证明上面不是"规则整体失效"）."""
        env, tid, _rows = _setup(client, db)
        _set_default_bucket(
            db,
            tid,
            filters=[{"field_name": "status", "op": "=", "value": "public"}],
            hidden={"viewer": ["tag"]},
        )
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.viewer.id),
            action=RowAction.VIEW,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        assert _list_statuses(client, env, tid, env.viewer.username) == ["public", "secret"]


class TestApplicableRules:
    def test_user_and_member_role_hits(self, client, db):
        env, tid, _rows = _setup(client, db)
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.viewer.id),
            action=RowAction.VIEW,
            filters=[],
        )
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.MEMBER_ROLE,
            subject_id="read",
            action=RowAction.EDIT,
            filters=[],
        )
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.MEMBER_ROLE,
            subject_id="write",
            action=RowAction.VIEW,
            filters=[],
        )
        from cndb.plugins.tables.models import DataTable

        table = db.get(DataTable, tid)

        # viewer（read 档）：命中 user 规则 + read 规则，不命中 write 规则
        viewer_rules = applicable_row_rules(db, table, env.viewer)
        assert {(r.subject_type, r.subject_id, r.action) for r in viewer_rules} == {
            ("user", str(env.viewer.id), "view"),
            ("member_role", "read", "edit"),
        }
        # editor（write 档）：仅命中 write 规则（user 规则指向 viewer，不同人）
        editor_rules = applicable_row_rules(db, table, env.editor)
        assert {(r.subject_type, r.subject_id, r.action) for r in editor_rules} == {
            ("member_role", "write", "view"),
        }
