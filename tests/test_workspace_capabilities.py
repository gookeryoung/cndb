"""ADR 0153 P0：工作区能力位判定（`resolve_capabilities`）判定层单测.

覆盖三件事：

1. 能力位映射与升级前各入口的判定**逐条等价**（I3 存量不变的判定层锁定）；
2. 非成员 / 所有权边界与 404 / 403 语义（I2 天花板、I6 无泄露）；
3. 来源归因（I4）与载荷形状（前端 `useCapabilities` 唯一消费形态）。
"""

from __future__ import annotations

import pytest

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.permissions import (
    ROLE_CAPABILITIES,
    Capabilities,
    WorkspaceCapability,
    get_member_role,
    has_role,
    require_capability,
    resolve_capabilities,
)


@pytest.fixture()
def _user(db):
    def _make(username: str, nickname: str = "") -> User:
        u = User(username=username, nickname=nickname)
        u.set_password("pass")
        db.add(u)
        db.commit()
        return u

    return _make


@pytest.fixture()
def _ws(db):
    def _make(name: str, owner: User | None = None) -> Workspace:
        ws = Workspace(name=name, created_by_id=owner.id if owner else None)
        db.add(ws)
        db.flush()
        if owner is not None:
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
        db.commit()
        db.refresh(ws)
        return ws

    return _make


@pytest.fixture()
def _member(db):
    def _make(ws: Workspace, user: User, role: WorkspaceRole) -> WorkspaceMember:
        m = WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role)
        db.add(m)
        db.commit()
        db.refresh(m)
        return m

    return _make


class TestRoleCapabilityMapping:
    """能力位映射是唯一真相源（D10）：三档角色逐条断言，防止 P1 接入时静默放宽."""

    def test_owner_has_every_capability(self):
        assert ROLE_CAPABILITIES[WorkspaceRole.OWNER] == frozenset(WorkspaceCapability)

    def test_editor_can_read_write_export_only(self):
        assert ROLE_CAPABILITIES[WorkspaceRole.EDITOR] == frozenset(
            {WorkspaceCapability.READ, WorkspaceCapability.WRITE, WorkspaceCapability.EXPORT}
        )

    def test_viewer_can_read_only(self):
        assert ROLE_CAPABILITIES[WorkspaceRole.VIEWER] == frozenset({WorkspaceCapability.READ})

    def test_mapping_is_monotonic(self):
        """所有者 ⊇ 编辑者 ⊇ 查看者（权级单调，禁止出现「低档多一个能力」）."""
        assert ROLE_CAPABILITIES[WorkspaceRole.VIEWER] <= ROLE_CAPABILITIES[WorkspaceRole.EDITOR]
        assert ROLE_CAPABILITIES[WorkspaceRole.EDITOR] <= ROLE_CAPABILITIES[WorkspaceRole.OWNER]


class TestResolveCapabilities:
    """数据面角色 + 能力位 + 归因."""

    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            (WorkspaceRole.OWNER, WorkspaceCapability.EDIT_SETTINGS),
            (WorkspaceRole.EDITOR, WorkspaceCapability.WRITE),
            (WorkspaceRole.VIEWER, WorkspaceCapability.READ),
        ],
    )
    def test_role_gets_expected_capability(self, db, _user, _ws, _member, role, expected):
        user = _user(f"cap_{role.value}")
        ws = _ws(f"CapWS_{role.value}")
        _member(ws, user, role)
        caps = resolve_capabilities(user, ws, db)
        assert caps.data_role is role
        assert caps.allows(expected)

    def test_non_member_has_no_capability(self, db, _user, _ws):
        user = _user("cap_outsider")
        ws = _ws("CapWSOutsider")
        caps = resolve_capabilities(user, ws, db)
        assert caps == Capabilities(
            data_role=None,
            team_role=None,
            capabilities=frozenset(),
            sources={},
        )
        assert not caps.allows(WorkspaceCapability.READ)
        assert caps.to_payload()["data_role"] is None

    def test_editor_cannot_manage_members_or_restore(self, db, _user, _ws, _member):
        user = _user("cap_editor_guard")
        ws = _ws("CapWSEditorGuard")
        _member(ws, user, WorkspaceRole.EDITOR)
        caps = resolve_capabilities(user, ws, db)
        assert caps.allows(WorkspaceCapability.EXPORT)
        assert not caps.allows(WorkspaceCapability.MANAGE_MEMBERS)
        assert not caps.allows(WorkspaceCapability.RESTORE)
        assert not caps.allows(WorkspaceCapability.EDIT_SETTINGS)

    def test_sources_attribute_data_and_manage(self, db, _user, _ws, _member):
        owner = _user("cap_owner_src")
        ws = _ws("CapWSSources", owner=None)
        _member(ws, owner, WorkspaceRole.OWNER)
        caps = resolve_capabilities(owner, ws, db)
        assert caps.sources["data"] == "workspace_member:owner"
        assert caps.sources["manage"] == "workspace_member:owner"

    def test_editor_sources_have_no_manage_entry(self, db, _user, _ws, _member):
        user = _user("cap_editor_src")
        ws = _ws("CapWSEditorSrc")
        _member(ws, user, WorkspaceRole.EDITOR)
        caps = resolve_capabilities(user, ws, db)
        assert caps.sources == {"data": "workspace_member:editor"}

    def test_payload_shape(self, db, _user, _ws, _member):
        user = _user("cap_payload")
        ws = _ws("CapWSPayload")
        _member(ws, user, WorkspaceRole.VIEWER)
        payload = resolve_capabilities(user, ws, db).to_payload()
        assert payload == {
            "data_role": "viewer",
            "team_role": None,
            "capabilities": ["READ"],
            "sources": {"data": "workspace_member:viewer"},
        }

    def test_oner_returns_all_capabilities(self, db, _user, _ws):
        owner = _user("cap_owner_all")
        ws = _ws("CapWSOwnerAll", owner=owner)
        caps = resolve_capabilities(owner, ws, db)
        assert {c.value for c in caps.capabilities} == {c.value for c in WorkspaceCapability}


class TestEquivalenceWithLegacyJudgement:
    """I3 存量不变：P0 判定必须与旧入口（get_member_role / has_role）逐条一致."""

    @pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.EDITOR, WorkspaceRole.VIEWER])
    def test_data_role_matches_legacy_member_role(self, db, _user, _ws, _member, role):
        user = _user(f"eq_{role.value}")
        ws = _ws(f"EqWS_{role.value}")
        _member(ws, user, role)
        assert resolve_capabilities(user, ws, db).data_role is get_member_role(user, ws, db) is role

    def test_non_member_matches_legacy(self, db, _user, _ws):
        user = _user("eq_outsider")
        ws = _ws("EqWSOutsider")
        assert resolve_capabilities(user, ws, db).data_role is None
        assert get_member_role(user, ws, db) is None

    @pytest.mark.parametrize("role", [WorkspaceRole.OWNER, WorkspaceRole.EDITOR, WorkspaceRole.VIEWER])
    @pytest.mark.parametrize("minimum", [WorkspaceRole.OWNER, WorkspaceRole.EDITOR, WorkspaceRole.VIEWER])
    def test_capability_matches_legacy_has_role(self, db, _user, _ws, _member, role, minimum):
        """`has_role(minimum)` 等价于「拥有 minimum 对应的最小能力位」."""
        user = _user(f"eq2_{role.value}_{minimum.value}")
        ws = _ws(f"EqWS2_{role.value}_{minimum.value}")
        _member(ws, user, role)
        caps = resolve_capabilities(user, ws, db)
        minimum_capability = {
            WorkspaceRole.VIEWER: WorkspaceCapability.READ,
            WorkspaceRole.EDITOR: WorkspaceCapability.WRITE,
            WorkspaceRole.OWNER: WorkspaceCapability.EDIT_SETTINGS,
        }[minimum]
        assert caps.allows(minimum_capability) is has_role(user, ws, minimum, db)


class TestRequireCapability:
    """`require_capability` 是 403 唯一出口（ADR 0047 文案 + 能力位门控）."""

    def test_returns_capabilities_when_allowed(self, db, _user, _ws, _member):
        user = _user("req_owner")
        ws = _ws("ReqWSOwner")
        _member(ws, user, WorkspaceRole.OWNER)
        caps = require_capability(WorkspaceCapability.RESTORE, db, ws, user, requirement="恢复")
        assert caps.allows(WorkspaceCapability.RESTORE)

    def test_raises_permission_denied_for_member_with_low_role(self, db, _user, _ws, _member):
        user = _user("req_viewer", nickname="李四")
        ws = _ws("ReqWSViewer")
        _member(ws, user, WorkspaceRole.VIEWER)
        with pytest.raises(PermissionDeniedError) as exc:
            require_capability(WorkspaceCapability.EXPORT, db, ws, user, requirement="仅编辑者及以上")
        assert exc.value.status_code == 403
        assert "查看者" in exc.value.detail
        assert "仅编辑者及以上" in exc.value.detail

    def test_raises_for_non_member(self, db, _user, _ws):
        user = _user("req_outsider")
        ws = _ws("ReqWSOutsider")
        with pytest.raises(PermissionDeniedError) as exc:
            require_capability(WorkspaceCapability.READ, db, ws, user)
        assert exc.value.status_code == 403
        assert "不是该工作区成员" in exc.value.detail
