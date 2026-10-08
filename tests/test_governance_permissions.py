"""数据治理权限与模型测试（MANAGE_DATA 动作 + GovernanceTask）."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataTable, GovernanceTask, TablePermission
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.access import (
    _ACTION_DEFAULT_ROLE,
    _ACTION_PERMISSION_FIELD,
    TableAction,
)
from cndb.plugins.workspaces.models import ACTION_KEYS, ACTION_LABELS, WorkspaceRole


class TestManageDataAction:
    """MANAGE_DATA 动作枚举与映射（plan 步骤 3）。"""

    def test_action_enum_contains_manage_data(self) -> None:
        assert TableAction.MANAGE_DATA == "MANAGE_DATA"

    def test_permission_field_mapping(self) -> None:
        assert _ACTION_PERMISSION_FIELD[TableAction.MANAGE_DATA] == "manage_data_role"

    def test_default_role_is_admin(self) -> None:
        assert _ACTION_DEFAULT_ROLE[TableAction.MANAGE_DATA] == WorkspaceRole.ADMIN

    def test_workspace_action_keys_contains_manage_data(self) -> None:
        assert "MANAGE_DATA" in ACTION_KEYS
        assert ACTION_LABELS["MANAGE_DATA"]


class TestTablePermissionColumn:
    """TablePermission.manage_data_role 列（plan 步骤 2）。"""

    def test_column_exists_with_default(self, db) -> None:
        perm = TablePermission(table_id=0)
        db.add(perm)
        db.flush()
        db.refresh(perm)
        assert perm.manage_data_role == ""


class TestGovernanceTaskModel:
    """GovernanceTask 模型持久化（plan 步骤 2）。"""

    @pytest.fixture
    def owner(self, db):
        u = User(username="gov_owner", nickname="GovOwner")
        u.set_password("passw0rd")
        db.add(u)
        db.commit()
        db.refresh(u)
        return u

    @pytest.fixture
    def table(self, db, owner, tmp_path):
        from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

        engine = create_engine(f"sqlite:///{tmp_path / 'govtable.db'}")
        w = Workspace(name="GovWS", created_by_id=owner.id)
        db.add(w)
        db.flush()
        db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
        dt = DataTable(workspace_id=w.id, name="GovTable")
        dt.ensure_db_name()
        db.add(dt)
        db.commit()
        db.refresh(dt)
        ddl.create_table(engine, dt)
        engine.dispose()
        return dt

    def test_create_detect_task(self, db, table) -> None:
        task = GovernanceTask(
            table_id=table.id,
            kind="detect",
            config={"match_fields": ["姓名"]},
        )
        db.add(task)
        db.flush()
        db.refresh(task)
        assert task.id is not None
        assert task.status == "pending"
        assert task.progress == 0
        assert task.config == {"match_fields": ["姓名"]}
        assert task.report == ""
        assert task.error_message == ""
        assert task.total_groups == 0
        assert task.done_groups == 0

    def test_status_transition_and_report(self, db, table) -> None:
        task = GovernanceTask(table_id=table.id, kind="merge", config={})
        db.add(task)
        db.flush()
        task.status = "running"
        task.total_groups = 3
        task.done_groups = 1
        task.report = '{"groups": []}'
        db.commit()
        db.refresh(task)
        assert task.status == "running"
        assert task.total_groups == 3
        assert task.report == '{"groups": []}'

    def test_kind_requires_valid_value(self) -> None:
        """kind 只允许 detect/merge/clean（应用层校验由服务层做，列长度 16）。"""
        assert GovernanceTask.__table__.c["kind"].type.length == 16


class TestCheckActionManageData:
    """check_action 对 MANAGE_DATA 的 403 矩阵 / 阈值覆盖 / 自定义 Role / 表拥有者（plan 步骤 15）。"""

    @pytest.fixture
    def ws_users(self, db):
        """工作区 + owner/admin/editor/viewer 四个成员."""
        from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

        owner = User(username="mx_owner", nickname="MxOwner")
        owner.set_password("passw0rd")
        db.add(owner)
        db.flush()
        w = Workspace(name="MxWS", created_by_id=owner.id)
        db.add(w)
        db.flush()
        role_map = {
            owner: WorkspaceRole.OWNER,
        }
        for uname, role in [
            ("mx_admin", WorkspaceRole.ADMIN),
            ("mx_editor", WorkspaceRole.EDITOR),
            ("mx_viewer", WorkspaceRole.VIEWER),
        ]:
            u = User(username=uname, nickname=uname)
            u.set_password("passw0rd")
            db.add(u)
            db.flush()
            role_map[u] = role
        for u, role in role_map.items():
            db.add(WorkspaceMember(workspace_id=w.id, user_id=u.id, role=role))
        db.commit()
        db.refresh(w)
        return {"ws": w, "users": role_map}

    @pytest.fixture
    def table(self, db, ws_users):
        from cndb.plugins.workspaces.models import WorkspaceRole

        owner = next(u for u, r in ws_users["users"].items() if r == WorkspaceRole.OWNER)
        dt = DataTable(workspace_id=ws_users["ws"].id, name="MxTable", owner_id=owner.id)
        dt.ensure_db_name()
        db.add(dt)
        db.commit()
        db.refresh(dt)
        return dt

    def _user_by_role(self, ws_users, role):
        return next(u for u, r in ws_users["users"].items() if r == role)

    def test_default_threshold_matrix(self, db, ws_users, table) -> None:
        """默认阈值 ADMIN：viewer/editor 拒绝，admin/owner 放行."""
        from cndb.plugins.tables.services.core.access import check_action
        from cndb.plugins.workspaces.models import WorkspaceRole

        assert (
            check_action(db, table, self._user_by_role(ws_users, WorkspaceRole.VIEWER), TableAction.MANAGE_DATA)
            is False
        )
        assert (
            check_action(db, table, self._user_by_role(ws_users, WorkspaceRole.EDITOR), TableAction.MANAGE_DATA)
            is False
        )
        assert (
            check_action(db, table, self._user_by_role(ws_users, WorkspaceRole.ADMIN), TableAction.MANAGE_DATA) is True
        )
        assert (
            check_action(db, table, self._user_by_role(ws_users, WorkspaceRole.OWNER), TableAction.MANAGE_DATA) is True
        )

    def test_table_owner_allowed_regardless_of_ws_role(self, db, ws_users, table) -> None:
        """表拥有者拥有全部动作（优先级 1），即使工作区角色为 viewer."""
        from cndb.plugins.tables.services.core.access import check_action
        from cndb.plugins.workspaces.models import WorkspaceRole

        owner = self._user_by_role(ws_users, WorkspaceRole.OWNER)
        # 把 owner 降为 viewer 成员，验证表拥有者分支仍放行
        from cndb.plugins.workspaces.models import WorkspaceMember

        m = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == ws_users["ws"].id, WorkspaceMember.user_id == owner.id)
            .first()
        )
        m.role = WorkspaceRole.VIEWER
        db.commit()
        assert check_action(db, table, owner, TableAction.MANAGE_DATA) is True

    def test_threshold_override(self, db, ws_users, table) -> None:
        """TablePermission.manage_data_role 非空时覆盖默认阈值."""
        from cndb.plugins.tables.services.core.access import check_action
        from cndb.plugins.workspaces.models import WorkspaceRole

        perm = TablePermission(table_id=table.id, manage_data_role="viewer")
        db.add(perm)
        db.commit()
        # 降到 viewer：viewer 也能治理
        assert (
            check_action(db, table, self._user_by_role(ws_users, WorkspaceRole.VIEWER), TableAction.MANAGE_DATA) is True
        )

        # 提到 owner：editor/viewer 被拒；工作区 ADMIN 走优先级 2 无条件放行，不受阈值约束
        perm.manage_data_role = "owner"
        db.commit()
        assert (
            check_action(db, table, self._user_by_role(ws_users, WorkspaceRole.EDITOR), TableAction.MANAGE_DATA)
            is False
        )
        assert (
            check_action(db, table, self._user_by_role(ws_users, WorkspaceRole.ADMIN), TableAction.MANAGE_DATA) is True
        )

    def test_custom_role_member(self, db, ws_users, table) -> None:
        """表成员绑定自定义 Role：按 Role.permissions 的 MANAGE_DATA 位判定."""
        from cndb.plugins.tables.models import TableMember
        from cndb.plugins.tables.services.core.access import check_action
        from cndb.plugins.workspaces.models import Role, WorkspaceRole

        editor = self._user_by_role(ws_users, WorkspaceRole.EDITOR)
        viewer = self._user_by_role(ws_users, WorkspaceRole.VIEWER)

        role_allow = Role(code="gov_operator", name="治理操作员", permissions={"MANAGE_DATA": True})
        role_deny = Role(code="gov_limited", name="受限角色", permissions={"MANAGE_DATA": False})
        db.add_all([role_allow, role_deny])
        db.commit()
        db.add(TableMember(table_id=table.id, user_id=editor.id, role="gov_operator"))
        db.add(TableMember(table_id=table.id, user_id=viewer.id, role="gov_limited"))
        db.commit()

        # 成员授权命中：editor 借自定义角色放行
        assert check_action(db, table, editor, TableAction.MANAGE_DATA) is True
        # 成员授权命中但权限位为 False：拒绝（不再回落到阈值）
        assert check_action(db, table, viewer, TableAction.MANAGE_DATA) is False


__all__ = []
