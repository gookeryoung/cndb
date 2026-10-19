"""行级权限规则写路径接入（ADR 0004，P1）.

覆盖单行 update / delete 的按行三态分派：
1. `edit` 规则命中行 → 直编（默认档外也可直编）；
2. 可查看但不在写范围内 → 202 修改申请；
3. 读范围外 → 404 且不落库（I6，不泄露存在性）；
4. `edit` 规则写权**独立于表 EDIT_RECORDS**（D2）；
5. 工作区 viewer 无直编资格 → 一律 202（沿用双轨制）；
6. 管理员（表 owner）豁免行规则；
7. `member_role` 按**有效档位**匹配（write 档命中）；
8. 规则条件引用被隐藏字段 → 条件静默丢弃（侧信道保护）；
9. 存量不变（I3）：无规则时直编 / 202 / 403 与今天逐条一致；
10. 批量端点沿用表级 EDIT_RECORDS 门槛（§7-6）。
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, RowAction, RowPermission, RowSubject, TablePermission
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core import row_access
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

TABLES = "/api/v1/workspaces/{ws}/tables"
RECORDS = "/api/v1/workspaces/{ws}/tables/{tb}/records"


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
        self.owner = _make_user(db, "rw_owner")
        self.ws = Workspace(name="RowWriteWS", created_by_id=self.owner.id)
        db.add(self.ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.owner.id, role=WorkspaceRole.OWNER))
        self.editor = _make_user(db, "rw_editor")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.editor.id, role=WorkspaceRole.EDITOR))
        self.viewer = _make_user(db, "rw_viewer")
        db.add(WorkspaceMember(workspace_id=self.ws.id, user_id=self.viewer.id, role=WorkspaceRole.VIEWER))
        db.commit()


def _setup(client: TestClient, db: Session) -> tuple[Env, int, dict[str, int]]:
    env = Env(db)
    auth = _login(client, env.owner.username)
    r = client.post(TABLES.format(ws=env.ws.id), json={"name": "行写路径表", "description": ""}, headers=auth)
    assert r.status_code == 201, r.text
    tid = int(r.json()["id"])
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
        r = client.post(f"{TABLES.format(ws=env.ws.id)}/{tid}/records", json={"values": values}, headers=auth)
        assert r.status_code in (200, 201), r.text
        row_ids[values["status"]] = int(r.json()["id"])
    return env, tid, row_ids


def _set_permission(
    db: Session,
    table_id: int,
    *,
    filters: list[dict] | None = None,
    hidden: dict | None = None,
    edit_records_role: str = "",
) -> None:
    db.add(
        TablePermission(
            table_id=table_id,
            read_role="viewer",
            hidden_fields=hidden or {},
            row_filters=filters or [],
            row_filter_type="AND",
            edit_records_role=edit_records_role,
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
) -> None:
    db.add(
        RowPermission(
            table_id=table_id,
            subject_type=subject_type,
            subject_id=subject_id,
            action=action,
            filters=filters,
            filter_type="AND",
        )
    )
    db.commit()


def _patch(client: TestClient, env: Env, tid: int, row_id: int, username: str, values: dict):
    return client.patch(
        f"{RECORDS.format(ws=env.ws.id, tb=tid)}/{row_id}",
        json={"values": values},
        headers=_login(client, username),
    )


def _delete(client: TestClient, env: Env, tid: int, row_id: int, username: str, *, soft: bool = True):
    return client.delete(
        f"{RECORDS.format(ws=env.ws.id, tb=tid)}/{row_id}",
        params={"soft": str(soft).lower()},
        headers=_login(client, username),
    )


def _stored(db: Session, env: Env, table_id: int, row_id: int, field: str):
    """以 owner 身份直读（豁免行规则），验证落库真值."""
    table = db.get(DataTable, table_id)
    row = rec.get_row(db.get_bind(), table, row_id, db=db, user=env.owner)
    return row[field] if row else None


class TestEditRuleGrantsWrite:
    """`edit` 规则命中行可直编；仅可查看的行 → 202（ADR §4）."""

    def test_edit_rule_row_is_directly_writable_outside_default(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.editor.id),
            action=RowAction.EDIT,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        # secret 行在默认档外，但被 edit 规则命中 → 直编落库
        r = _patch(client, env, tid, rows["secret"], env.editor.username, {"secret_note": "B1"})
        assert r.status_code == 200, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B1"

    def test_default_row_still_directly_writable(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.editor.id),
            action=RowAction.EDIT,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        r = _patch(client, env, tid, rows["public"], env.editor.username, {"secret_note": "A1"})
        assert r.status_code == 200, r.text
        assert _stored(db, env, tid, rows["public"], "secret_note") == "A1"

    def test_viewable_but_not_writable_returns_202(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        # 只给 draft 读权，不给写权 → 可看不可改 → 202
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.editor.id),
            action=RowAction.VIEW,
            filters=[{"field_name": "status", "op": "=", "value": "draft"}],
        )
        r = _patch(client, env, tid, rows["draft"], env.editor.username, {"secret_note": "C1"})
        assert r.status_code == 202, r.text
        assert "change_request" in r.json()
        assert _stored(db, env, tid, rows["draft"], "secret_note") == "C"


class TestEditRuleIndependentOfTableThreshold:
    """D2：`edit` 规则写权独立于表 EDIT_RECORDS."""

    def test_denied_editor_writes_granted_row(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(
            db,
            tid,
            filters=[{"field_name": "status", "op": "=", "value": "public"}],
            edit_records_role="owner",  # editor 表级编辑被拒
        )
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.editor.id),
            action=RowAction.EDIT,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        r = _patch(client, env, tid, rows["secret"], env.editor.username, {"secret_note": "B2"})
        assert r.status_code == 200, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B2"

    def test_denied_editor_non_granted_row_is_403(self, client, db):
        """表级阈值拦截 + 该行未被 edit 规则命中 → 保留存量 403 语义."""
        env, tid, rows = _setup(client, db)
        _set_permission(
            db,
            tid,
            filters=[{"field_name": "status", "op": "=", "value": "public"}],
            edit_records_role="owner",
        )
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.editor.id),
            action=RowAction.EDIT,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        r = _patch(client, env, tid, rows["public"], env.editor.username, {"secret_note": "A2"})
        assert r.status_code == 403, r.text
        assert _stored(db, env, tid, rows["public"], "secret_note") == "A"


class TestViewerNeverDirect:
    """工作区 viewer 无直编资格 → 命中 edit 规则也走 202（沿用双轨制）."""

    def test_viewer_with_edit_rule_still_202(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.viewer.id),
            action=RowAction.EDIT,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        r = _patch(client, env, tid, rows["secret"], env.viewer.username, {"secret_note": "B3"})
        assert r.status_code == 202, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B"


class TestOutOfReadScopeReturns404:
    """读范围外 → 404 且不落库（I6）."""

    def test_update_out_of_read_scope_404(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        r = _patch(client, env, tid, rows["secret"], env.viewer.username, {"secret_note": "X"})
        assert r.status_code == 404, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B"

    def test_soft_delete_out_of_read_scope_404(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        r = _delete(client, env, tid, rows["secret"], env.viewer.username)
        assert r.status_code == 404, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B"


class TestAdminBypass:
    """D3：表 owner 豁免行规则，任意行可直编."""

    def test_owner_edits_row_outside_default(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        r = _patch(client, env, tid, rows["secret"], env.owner.username, {"secret_note": "BY"})
        assert r.status_code == 200, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "BY"


class TestMemberRoleEditTier:
    """`member_role` 写档命中：editor（write）可直编，viewer（read）不命中."""

    def test_write_tier_edit_rule(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.MEMBER_ROLE,
            subject_id="write",
            action=RowAction.EDIT,
            filters=[{"field_name": "status", "op": "=", "value": "draft"}],
        )
        r = _patch(client, env, tid, rows["draft"], env.editor.username, {"secret_note": "C2"})
        assert r.status_code == 200, r.text
        assert _stored(db, env, tid, rows["draft"], "secret_note") == "C2"
        # viewer 为 read 档，不命中 write 规则，draft 也不在默认档 → 读范围外 404
        r = _patch(client, env, tid, rows["draft"], env.viewer.username, {"secret_note": "C3"})
        assert r.status_code == 404, r.text


class TestHiddenFieldDegradation:
    """规则条件引用被隐藏字段 → 条件丢弃，规则不额外开放该行."""

    def test_edit_rule_on_hidden_field_is_dropped(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(
            db,
            tid,
            filters=[{"field_name": "status", "op": "=", "value": "public"}],
            hidden={"editor": ["tag"]},
        )
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.editor.id),
            action=RowAction.EDIT,
            filters=[{"field_name": "tag", "op": "=", "value": "t2"}],
        )
        # tag 条件被丢弃 → 无有效 edit 条件 → secret 行既不可读也不可写 → 404
        r = _patch(client, env, tid, rows["secret"], env.editor.username, {"secret_note": "H1"})
        assert r.status_code == 404, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B"


class TestBulkStaysTableLevel:
    """§7-6：批量端点沿用表级 EDIT_RECORDS 门槛，不为行级 edit 权开旁路."""

    def test_denied_editor_bulk_update_403(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(
            db,
            tid,
            filters=[{"field_name": "status", "op": "=", "value": "public"}],
            edit_records_role="owner",
        )
        _add_rule(
            db,
            tid,
            subject_type=RowSubject.USER,
            subject_id=str(env.editor.id),
            action=RowAction.EDIT,
            filters=[{"field_name": "status", "op": "=", "value": "secret"}],
        )
        r = client.post(
            f"{RECORDS.format(ws=env.ws.id, tb=tid)}/bulk-update",
            json={"row_ids": [rows["secret"]], "values": {"secret_note": "BK"}},
            headers=_login(client, env.editor.username),
        )
        assert r.status_code == 403, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B"


class TestLegacyUnchanged:
    """I3：无任何行规则时，直编 / 202 / 403 与今天逐条一致."""

    def test_no_rules_editor_direct(self, client, db):
        env, tid, rows = _setup(client, db)
        r = _patch(client, env, tid, rows["secret"], env.editor.username, {"secret_note": "L1"})
        assert r.status_code == 200, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "L1"

    def test_no_rules_viewer_202(self, client, db):
        env, tid, rows = _setup(client, db)
        r = _patch(client, env, tid, rows["secret"], env.viewer.username, {"secret_note": "L2"})
        assert r.status_code == 202, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B"

    def test_no_rules_table_threshold_denies_editor_403(self, client, db):
        env, tid, rows = _setup(client, db)
        _set_permission(db, tid, edit_records_role="owner")
        r = _patch(client, env, tid, rows["secret"], env.editor.username, {"secret_note": "L3"})
        assert r.status_code == 403, r.text
        assert _stored(db, env, tid, rows["secret"], "secret_note") == "B"


class TestRouterDefensiveBranches:
    """路由层分派后的防御分支：create 403、delete 403、写函数返回 None/False → 404."""

    def test_create_denied_editor_403(self, client, db):
        """表级 EDIT_RECORDS 受限的 editor 建行 → 403（_dispatch_or_403 存量语义）."""
        env, tid, _ = _setup(client, db)
        _set_permission(db, tid, edit_records_role="owner")
        r = client.post(
            RECORDS.format(ws=env.ws.id, tb=tid),
            json={"values": {"status": "x"}},
            headers=_login(client, env.editor.username),
        )
        assert r.status_code == 403, r.text

    def test_delete_denied_editor_non_granted_row_403(self, client, db):
        """表级阈值拦截 + 行未被 edit 规则命中 → 删除 403（存量语义）."""
        env, tid, rows = _setup(client, db)
        _set_permission(
            db,
            tid,
            filters=[{"field_name": "status", "op": "=", "value": "public"}],
            edit_records_role="owner",
        )
        r = _delete(client, env, tid, rows["public"], env.editor.username)
        assert r.status_code == 403, r.text

    def test_update_row_none_after_direct_404(self, client, db):
        """分派为直编但底层 update_row 返回 None（竞态/边界）→ 404."""
        env, tid, rows = _setup(client, db)
        with patch("cndb.plugins.tables.routers.records.update_row", return_value=None):
            r = _patch(client, env, tid, rows["public"], env.owner.username, {"secret_note": "Z"})
        assert r.status_code == 404, r.text

    def test_delete_row_false_after_direct_404(self, client, db):
        """分派为直编但底层 trash_row 返回 False（竞态/边界）→ 404."""
        env, tid, rows = _setup(client, db)
        with patch("cndb.plugins.tables.routers.records.trash_row", return_value=False):
            r = _delete(client, env, tid, rows["public"], env.owner.username)
        assert r.status_code == 404, r.text


class TestInternalScopeBranches:
    """内部行范围合成函数的边界分支（db=None / 默认档编译 / 无表权限用户 / 隐藏字段嵌套）."""

    def test_edit_scope_none_db(self, client, db):
        env, tid, _ = _setup(client, db)
        table = db.get(DataTable, tid)
        sa_table = rec._get_sa_table(db.get_bind(), table)
        assert row_access.row_edit_scope_where(None, table, sa_table, env.owner) is None

    def test_read_scope_none_db(self, client, db):
        env, tid, _ = _setup(client, db)
        table = db.get(DataTable, tid)
        sa_table = rec._get_sa_table(db.get_bind(), table)
        assert row_access.row_read_scope_where(None, table, sa_table, env.owner) is None

    def test_write_scope_none_db(self, client, db):
        env, tid, _ = _setup(client, db)
        table = db.get(DataTable, tid)
        sa_table = rec._get_sa_table(db.get_bind(), table)
        assert rec._build_row_write_scope_where(table, sa_table, None, env.owner, enforce_row_rules=True) is None

    def test_default_scope_compiled_when_configured(self, client, db):
        """默认档非空且调用者不豁免 → 走默认档编译（内部/批量路径）."""
        env, tid, _ = _setup(client, db)
        _set_permission(db, tid, filters=[{"field_name": "status", "op": "=", "value": "public"}])
        table = db.get(DataTable, tid)
        sa_table = rec._get_sa_table(db.get_bind(), table)
        assert rec._build_row_scope_where(table, sa_table, db, env.editor) is not None

    def test_applicable_rules_without_table_read(self, client, db):
        """无表 READ 的用户：有效档位 None、不命中任何规则（I1）."""
        _, tid, _ = _setup(client, db)
        table = db.get(DataTable, tid)
        outsider = _make_user(db, "rw_outsider")
        assert row_access._effective_member_role(db, table, outsider) is None
        assert row_access.applicable_row_rules(db, table, outsider) == []

    def test_strip_hidden_nested_group_dropped(self):
        """嵌套分组引用了隐藏字段 → 整组丢弃."""
        hidden = {"tag"}
        nested = {"__and__": [{"field_name": "tag", "op": "=", "value": "x"}]}
        assert row_access._strip_hidden_conditions(nested, hidden) is None

    def test_strip_hidden_plain_value_passthrough(self):
        """非 dict/list 的条件项原样返回."""
        assert row_access._strip_hidden_conditions("plain", {"tag"}) == "plain"
