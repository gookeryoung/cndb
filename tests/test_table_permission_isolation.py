"""表级权限必须"按表隔离" —— 回归锁定 TablePermission 查询错位缺陷.

**背景**：``TablePermission`` 的主键是自增 ``id``，``table_id`` 才是外键列。
``access.py`` 里曾用 ``db.get(TablePermission, table.id)`` 取权限行，等于**按主键**查：
- 当某张表的 ``id`` 恰好等于另一张表权限行的 ``id`` 时，会读到**别的表**的规则；
- 否则取不到（退回默认），使该表实际生效的权限与其配置不一致。

后果：读写阈值、隐藏字段（``hidden_fields``）、行级过滤（``row_filters``）整体错位 ——
本该受限的表可能对普通成员开放，或本该开放的字段/行被错误隐藏。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, TablePermission
from cndb.plugins.tables.services.core.access import (
    TableAction,
    check_action,
    get_hidden_field_names,
    get_row_scope,
    row_filter_conjunction,
)
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


def _user(db: Session, username: str) -> User:
    u = User(username=username, nickname=username)
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def env(db):
    owner = _user(db, "perm_owner")
    ws = Workspace(name="PermWS", created_by_id=owner.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    viewer = _user(db, "perm_viewer")
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=viewer.id, role=WorkspaceRole.VIEWER))
    db.commit()

    open_table = DataTable(workspace_id=ws.id, name="开放表", db_table_name="t_perm_open", owner_id=owner.id)
    restricted = DataTable(workspace_id=ws.id, name="受限表", db_table_name="t_perm_restricted", owner_id=owner.id)
    db.add_all([open_table, restricted])
    db.flush()

    # 只给"受限表"写权限行：读门槛 OWNER + 隐藏 secret 字段 + 行级过滤
    perm = TablePermission(
        table_id=restricted.id,
        read_role="owner",
        hidden_fields={"viewer": ["secret"]},
        row_filters=[{"field_name": "status", "op": "=", "value": "public"}],
        row_filter_type="AND",
    )
    db.add(perm)
    db.commit()
    db.refresh(open_table)
    db.refresh(restricted)
    return {"owner": owner, "viewer": viewer, "open": open_table, "restricted": restricted}


class TestTablePermissionIsolation:
    def test_read_threshold_applies_only_to_configured_table(self, db, env):
        open_table, restricted, viewer, owner = env["open"], env["restricted"], env["viewer"], env["owner"]
        # 配置了 read_role=OWNER 的表：viewer 不可读，owner 可读
        assert check_action(db, restricted, viewer, TableAction.READ) is False
        assert check_action(db, restricted, owner, TableAction.READ) is True
        # 未配置权限行的表：不应被"别的表"的规则牵连
        assert check_action(db, open_table, viewer, TableAction.READ) is True

    def test_hidden_fields_do_not_leak_across_tables(self, db, env):
        assert get_hidden_field_names(db, env["restricted"], env["viewer"]) == {"secret"}
        # 关键回归：开放表没有权限行，绝不能拿到受限表的隐藏字段配置
        assert get_hidden_field_names(db, env["open"], env["viewer"]) == set()

    def test_row_filters_do_not_leak_across_tables(self, db, env):
        assert get_row_scope(db, env["restricted"]) != []
        assert get_row_scope(db, env["open"]) == []
        assert row_filter_conjunction(db, env["restricted"]) == "AND"
        assert row_filter_conjunction(db, env["open"]) == "AND"

    def test_owner_of_open_table_unaffected_by_other_rows(self, db, env):
        """两表的 owner 相同，但权限行只作用于配置的那张表."""
        assert check_action(db, env["open"], env["owner"], TableAction.EDIT_SCHEMA) is True
        assert check_action(db, env["restricted"], env["owner"], TableAction.EDIT_SCHEMA) is True

    def test_permission_row_count_matches_config(self, db, env):
        rows = db.query(TablePermission).all()
        assert len(rows) == 1
        assert rows[0].table_id == env["restricted"].id


class TestRoleStringCaseTolerance:
    """角色字符串大小写必须都能被识别：否则配置"看似生效"，实际全拒/全放."""

    def test_uppercase_read_role_is_honored(self, db, env):
        from cndb.plugins.tables.services.core.access import check_action

        env["restricted"].name = env["restricted"].name
        perm = db.query(TablePermission).filter(TablePermission.table_id == env["restricted"].id).first()
        perm.read_role = "OWNER"  # 大写枚举名（历史/手填数据里出现过）
        db.commit()
        assert check_action(db, env["restricted"], env["viewer"], TableAction.READ) is False
        assert check_action(db, env["restricted"], env["owner"], TableAction.READ) is True

    def test_uppercase_hidden_fields_key_is_honored(self, db, env):
        perm = db.query(TablePermission).filter(TablePermission.table_id == env["restricted"].id).first()
        perm.hidden_fields = {"VIEWER": ["secret"]}
        db.commit()
        assert get_hidden_field_names(db, env["restricted"], env["viewer"]) == {"secret"}

    def test_invalid_role_denies_but_open_table_stays_open(self, db, env):
        perm = db.query(TablePermission).filter(TablePermission.table_id == env["restricted"].id).first()
        perm.read_role = "not-a-role"
        db.commit()
        assert check_action(db, env["restricted"], env["viewer"], TableAction.READ) is False
        assert check_action(db, env["open"], env["viewer"], TableAction.READ) is True
