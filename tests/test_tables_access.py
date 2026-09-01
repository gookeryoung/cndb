"""表级访问策略链测试：动作角色矩阵、链式短路与便捷入口."""

from __future__ import annotations

from typing import Any

import pytest

from cndb.accounts.models import User
from cndb.tables import services
from cndb.tables.access import (
    AccessContext,
    AccessVerdict,
    TableAccessPolicy,
    TableAction,
    check_table_access,
    check_workspace_access,
)
from cndb.tables.models import DataTable
from cndb.workspaces.models import Workspace, WorkspaceMember

pytestmark = pytest.mark.django_db


@pytest.fixture
def table(workspace: Workspace) -> DataTable:
    """测试用数据表：单文本字段."""
    return services.create_table(
        workspace=workspace,
        name="权限表",
        field_defs=[{"name": "名称", "field_type": "text"}],
    )


def _member(workspace: Workspace, username: str, role: str) -> User:
    """创建指定角色的成员."""
    user = User.objects.create_user(username=username, password="Str0ng-Pass-42")
    WorkspaceMember.objects.create(workspace=workspace, user=user, role=role)
    return user


class TestRoleMatrix:
    """工作区角色策略矩阵：动作 × 角色."""

    @pytest.mark.parametrize(
        ("role", "action", "allowed"),
        [
            (WorkspaceMember.Role.VIEWER, TableAction.READ, True),
            (WorkspaceMember.Role.COMMENTER, TableAction.READ, True),
            (WorkspaceMember.Role.EDITOR, TableAction.READ, True),
            (WorkspaceMember.Role.VIEWER, TableAction.EDIT_RECORDS, False),
            (WorkspaceMember.Role.COMMENTER, TableAction.EDIT_RECORDS, False),
            (WorkspaceMember.Role.EDITOR, TableAction.EDIT_RECORDS, True),
            (WorkspaceMember.Role.ADMIN, TableAction.EDIT_RECORDS, True),
            (WorkspaceMember.Role.EDITOR, TableAction.EDIT_VIEWS, True),
            (WorkspaceMember.Role.VIEWER, TableAction.EDIT_VIEWS, False),
            (WorkspaceMember.Role.EDITOR, TableAction.EDIT_SCHEMA, True),
            (WorkspaceMember.Role.COMMENTER, TableAction.EDIT_SCHEMA, False),
        ],
    )
    def test_matrix(
        self, workspace: Workspace, table: DataTable, role: str, action: TableAction, allowed: bool
    ) -> None:
        """角色达到动作最低要求则允许，否则拒绝并给出原因."""
        # 用户名由角色/动作/结论组合派生，保证参数化用例间唯一
        member = _member(workspace, f"u-{role}-{action.name}-{allowed}", role)
        verdict = check_table_access(member, table, action)
        assert verdict.allowed is allowed
        if not allowed:
            assert verdict.reason

    def test_owner_passes_all_actions(self, workspace: Workspace, table: DataTable, user: User) -> None:
        """OWNER 对全部动作放行."""
        for action in TableAction:
            assert check_table_access(user, table, action).allowed

    def test_non_member_denied(self, workspace: Workspace, table: DataTable) -> None:
        """非成员对所有动作拒绝."""
        outsider = User.objects.create_user(username="outsider", password="Str0ng-Pass-42")
        for action in TableAction:
            verdict = check_table_access(outsider, table, action)
            assert not verdict.allowed

    def test_anonymous_denied(self, workspace: Workspace, table: DataTable) -> None:
        """未认证用户对所有动作拒绝."""
        for action in TableAction:
            assert not check_table_access(None, table, action).allowed


class TestWorkspaceEntry:
    """工作区级便捷入口：表不存在的动作（如建表）."""

    def test_editor_can_create_schema_action(self, workspace: Workspace) -> None:
        """EDITOR 的工作区级结构编辑动作放行."""
        editor = _member(workspace, "e1", WorkspaceMember.Role.EDITOR)
        assert check_workspace_access(editor, workspace, TableAction.EDIT_SCHEMA).allowed

    def test_viewer_denied_workspace_schema_action(self, workspace: Workspace) -> None:
        """VIEWER 的工作区级结构编辑动作拒绝."""
        viewer = _member(workspace, "v1", WorkspaceMember.Role.VIEWER)
        verdict = check_workspace_access(viewer, workspace, TableAction.EDIT_SCHEMA)
        assert not verdict.allowed
        assert verdict.reason


class _FakePolicy(TableAccessPolicy):
    """记录调用顺序并可指定裁决的假策略."""

    def __init__(self, name: str, verdict: AccessVerdict) -> None:
        self.name = name
        self.verdict = verdict
        self.calls: list[str] = []

    def check(self, user: object, context: AccessContext, action: TableAction) -> AccessVerdict:
        """记录调用并返回预设裁决."""
        self.calls.append(self.name)
        return self.verdict


class TestPolicyChain:
    """策略链：按序裁决、拒绝短路、全部通过才放行."""

    def test_short_circuits_on_first_deny(
        self, monkeypatch: pytest.MonkeyPatch, workspace: Workspace, table: DataTable, user: User
    ) -> None:
        """首环节拒绝即短路，后续环节不再执行."""
        deny = _FakePolicy("deny", AccessVerdict(False, "被拒"))
        allow = _FakePolicy("allow", AccessVerdict(True))
        monkeypatch.setattr("cndb.tables.access.POLICIES", [deny, allow])
        verdict = check_table_access(user, table, TableAction.READ)
        assert verdict.allowed is False
        assert verdict.reason == "被拒"
        assert deny.calls == ["deny"]
        assert allow.calls == []

    def test_all_pass_allows(
        self, monkeypatch: pytest.MonkeyPatch, workspace: Workspace, table: DataTable, user: User
    ) -> None:
        """全部环节通过则放行."""
        first = _FakePolicy("first", AccessVerdict(True))
        second = _FakePolicy("second", AccessVerdict(True))
        monkeypatch.setattr("cndb.tables.access.POLICIES", [first, second])
        assert check_table_access(user, table, TableAction.READ).allowed
        assert first.calls == ["first"]
        assert second.calls == ["second"]

    def test_context_carries_table(
        self, monkeypatch: pytest.MonkeyPatch, workspace: Workspace, table: DataTable, user: User
    ) -> None:
        """链上策略拿到携带表的上下文."""
        seen: dict[str, Any] = {}

        class Probe(TableAccessPolicy):
            """记录上下文的探针策略."""

            def check(self, user: object, context: AccessContext, action: TableAction) -> AccessVerdict:
                """记录上下文后放行."""
                seen["table"] = context.table
                seen["workspace"] = context.workspace
                return AccessVerdict(True)

        monkeypatch.setattr("cndb.tables.access.POLICIES", [Probe()])
        assert check_table_access(user, table, TableAction.READ).allowed
        assert seen["table"] == table
        assert seen["workspace"] == workspace
