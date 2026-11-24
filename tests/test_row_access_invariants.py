"""行级权限不变量（路线图 0141 P0-4，需求 0141 C1 ④）.

构建"规则集 × 用户 × 行"的确定性矩阵，断言 H15 / H17 的口径恒成立：

- I1 天花板（H15）：行级授权永不放行「表外的人」—— 用户对表没有 READ 时，
  行级规则再多也不能让他看到行（由 `check_action` 与行范围两道闸共同保证）。
- I2 无泄露（H17）：读范围外的行，单行读 / 写一律按不存在处理（`get_row` 返回 None、
  `can_view_row` False），不做存在性提示。
- I3 并集语义（ADR 0004 §3）：默认档 ∪ 命中的读规则，任一侧命中即可见。
- I4 写范围 ⊇ 读范围之外才有意义：`edit` 规则只影响写范围，不改变读范围口径。

用固定矩阵（角色 × 规则组合 × 行值）而不是随机：失败时可精确复现。
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, RowPermission, TablePermission
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core.access import TableAction, check_action
from cndb.plugins.tables.services.core.row_access import can_edit_row, can_view_row
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")

#: 有效成员档位取值见 row_access._effective_member_role：``read`` / ``write``
READ_RULE = {
    "subject_type": "member_role",
    "subject_id": "read",
    "action": "read",
    "filters": [{"field_name": "分组", "op": "eq", "value": "A"}],
}
EDIT_RULE = {
    "subject_type": "member_role",
    "subject_id": "read",
    "action": "edit",
    "filters": [{"field_name": "分组", "op": "eq", "value": "A"}],
}


@pytest.fixture
def env(db):
    """工作区 + 表（分组字段 + 3 行：A / B / 空）+ 3 个用户（owner / editor / viewer）."""
    users: dict[str, User] = {}
    for name, _role in (
        ("owner", WorkspaceRole.OWNER),
        ("editor", WorkspaceRole.EDITOR),
        ("viewer", WorkspaceRole.VIEWER),
    ):
        u = User(username=f"inv_{name}", nickname=name)
        u.set_password("passw0rd")
        db.add(u)
        db.flush()
        users[name] = u

    ws = Workspace(name="InvariantWS", created_by_id=users["owner"].id)
    db.add(ws)
    db.flush()
    for name, role in (
        ("owner", WorkspaceRole.OWNER),
        ("editor", WorkspaceRole.EDITOR),
        ("viewer", WorkspaceRole.VIEWER),
    ):
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=users[name].id, role=role))
    db.commit()
    db.refresh(ws)

    engine = db.get_bind()
    table = DataTable(workspace_id=ws.id, name="不变量表")
    table.ensure_db_name()
    db.add(table)
    db.flush()
    field = DataField(table_id=table.id, name="分组", field_type="select", order=0)
    field.ensure_db_name()
    field.config = {"options": [{"value": "A"}, {"value": "B"}]}
    db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(engine, table)

    rows = {
        "A": rec.create_row(engine, table, {"分组": "A"}, db=db)["id"],
        "B": rec.create_row(engine, table, {"分组": "B"}, db=db)["id"],
        "空": rec.create_row(engine, table, {}, db=db)["id"],
    }
    return {"db": db, "engine": engine, "ws": ws, "table": table, "users": users, "rows": rows}


def _set_default_scope(db, table, filters):
    db.add(TablePermission(table_id=table.id, row_filters=filters or [], row_filter_type="AND"))
    db.commit()
    db.refresh(table)


def _add_rule(db, table, spec):
    db.add(RowPermission(table_id=table.id, granted_by_id=None, filter_type="AND", **spec))
    db.commit()
    db.refresh(table)


def _visible(env, user) -> set[str]:
    db, table, engine, sa = env["db"], env["table"], env["engine"], None
    sa = ddl.get_reflected_table(engine, table.db_table_name)
    return {key for key, row_id in env["rows"].items() if can_view_row(db, table, sa, row_id, user)}


class TestRowScopeInvariants:
    def test_no_rules_means_full_visibility(self, env):
        """无任何规则：全体成员都能看到全部行（存量行为不变，H16）。"""
        for name in ("owner", "editor", "viewer"):
            assert _visible(env, env["users"][name]) == {"A", "B", "空"}

    def test_default_scope_limits_everyone_except_owner(self, env):
        """默认档命中 A：非所有者只看到 A；所有者/超管豁免（ADR 0004 §3）。"""
        _set_default_scope(env["db"], env["table"], [{"field_name": "分组", "op": "eq", "value": "A"}])

        assert _visible(env, env["users"]["owner"]) == {"A", "B", "空"}
        assert _visible(env, env["users"]["editor"]) == {"A"}
        assert _visible(env, env["users"]["viewer"]) == {"A"}

    def test_read_rule_is_union_with_default_scope(self, env):
        """I3：默认档 A ∪ viewer 读规则 B → viewer 看到 A / B，看不到「空」。"""
        _set_default_scope(env["db"], env["table"], [{"field_name": "分组", "op": "eq", "value": "A"}])
        _add_rule(env["db"], env["table"], READ_RULE | {"filters": [{"field_name": "分组", "op": "eq", "value": "B"}]})

        assert _visible(env, env["users"]["viewer"]) == {"A", "B"}
        # editor 没有命中规则 → 仍只有默认档
        assert _visible(env, env["users"]["editor"]) == {"A"}

    def test_out_of_scope_rows_are_invisible_via_read_paths(self, env):
        """I2（H17）：范围外的行，单行读返回 None、列表里不出现、也不存在性提示。"""
        _set_default_scope(env["db"], env["table"], [{"field_name": "分组", "op": "eq", "value": "A"}])
        viewer = env["users"]["viewer"]
        engine, table, db = env["engine"], env["table"], env["db"]

        assert rec.get_row(engine, table, env["rows"]["B"], db=db, user=viewer) is None
        rows, total = rec.list_rows(engine, table, db=db, user=viewer)
        assert total == 1 and [r["分组"] for r in rows] == ["A"]
        assert rec.count_rows(engine, table, db=db, user=viewer) == 1

    def test_edit_rule_only_widens_write_scope(self, env):
        """I4：edit 规则让 viewer 可写 A，但不因此多看到 B（读范围仍由读侧决定）。"""
        _set_default_scope(env["db"], env["table"], [{"field_name": "分组", "op": "eq", "value": "A"}])
        _add_rule(env["db"], env["table"], EDIT_RULE)
        viewer = env["users"]["viewer"]
        sa = ddl.get_reflected_table(env["engine"], env["table"].db_table_name)

        assert can_edit_row(env["db"], env["table"], sa, env["rows"]["A"], viewer) is True
        assert can_edit_row(env["db"], env["table"], sa, env["rows"]["B"], viewer) is False
        # 写范围扩大不改变读范围可见性
        assert _visible(env, viewer) == {"A"}

    def test_table_ceiling_never_bypassed(self, env):
        """I1（H15）：表级 READ 被收回后，行规则再多也看不到行（天花板优先）。"""
        tp = TablePermission(table_id=env["table"].id, read_role=WorkspaceRole.EDITOR.value, row_filters=[])
        env["db"].add(tp)
        env["db"].commit()
        _add_rule(env["db"], env["table"], READ_RULE)
        env["db"].refresh(env["table"])

        viewer = env["users"]["viewer"]
        # 表级动作判定已拒绝 → 行级规则无从生效（调用方一律 403/404）
        assert check_action(env["db"], env["table"], viewer, TableAction.READ) is False
        # 所有者不受影响
        assert check_action(env["db"], env["table"], env["users"]["owner"], TableAction.READ) is True

    def test_trashed_rows_never_visible(self, env):
        """软删行对任何非管理员角色都不可见（回收站要显式查询，ADR 0139）。"""
        _set_default_scope(env["db"], env["table"], None)
        env["db"].refresh(env["table"])
        rec.trash_rows(env["engine"], env["table"], [env["rows"]["A"]], db=env["db"])
        sa = ddl.get_reflected_table(env["engine"], env["table"].db_table_name)

        for name in ("editor", "viewer"):
            assert can_view_row(env["db"], env["table"], sa, env["rows"]["A"], env["users"][name]) is False
        rows, total = rec.list_rows(env["engine"], env["table"], db=env["db"], user=env["users"]["viewer"])
        assert total == 2
        assert "A" not in {r.get("分组") for r in rows}
        # `_trashed_at` 已写入，回收站可见
        only_rows, only_total = rec.list_rows(env["engine"], env["table"], db=env["db"], only_trashed=True)
        assert only_total == 1 and only_rows[0]["id"] == env["rows"]["A"]


def test_row_scope_matrix_is_monotonic(env):
    """单调性：给用户加一条"放宽"的读规则，可见集合只能是超集（不会变少）。"""
    db, table, engine = env["db"], env["table"], env["engine"]
    viewer = env["users"]["viewer"]
    _set_default_scope(db, table, [{"field_name": "分组", "op": "eq", "value": "A"}])
    before = _visible(env, viewer)

    _add_rule(db, table, READ_RULE | {"filters": [{"field_name": "分组", "op": "eq", "value": "B"}]})
    after = _visible(env, viewer)

    assert before <= after
    assert after - before == {"B"}
    sa = ddl.get_reflected_table(engine, table.db_table_name)
    with engine.connect() as conn:
        assert conn.execute(select(sa.c.id)).fetchall()
