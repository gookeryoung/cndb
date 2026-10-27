"""ADR 0047：403 权限不足文案构造入口（permission_denied_detail）单测.

覆盖：成员各角色文案、非成员「申请加入」分支、拥有者缺失降级、
nickname→username 回退、scope / requirement 拼接边界。
"""

from __future__ import annotations

import pytest

from cndb.core.errors import PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole
from cndb.plugins.workspaces.permissions import (
    get_workspace_owner_display_name,
    permission_denied_detail,
    raise_permission_denied,
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
    def _make(ws: Workspace, user: User, role: WorkspaceRole) -> None:
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role))
        db.commit()

    return _make


class TestOwnerDisplayName:
    def test_nickname_preferred(self, db, _user, _ws):
        owner = _user("pdm_owner1", nickname="张三")
        ws = _ws("PdmWS1", owner=owner)
        assert get_workspace_owner_display_name(db, ws) == "张三"

    def test_username_fallback_on_empty_nickname(self, db, _user, _ws):
        owner = _user("pdm_owner2")
        ws = _ws("PdmWS2", owner=owner)
        assert get_workspace_owner_display_name(db, ws) == "pdm_owner2"

    def test_no_owner_member_returns_none(self, db, _user, _ws):
        _user("pdm_plain")
        ws = _ws("PdmWS3")  # created_by_id 为空且无 owner 成员
        assert get_workspace_owner_display_name(db, ws) is None


class TestPermissionDeniedDetail:
    def test_viewer_member_with_owner(self, db, _user, _ws, _member):
        owner = _user("pdm_o")
        viewer = _user("pdm_v")
        ws = _ws("PdmWS", owner=owner)
        _member(ws, viewer, WorkspaceRole.VIEWER)
        detail = permission_denied_detail(db, ws, viewer, scope="表级")
        assert detail == (
            "当前用户在此工作区的角色为【查看者】，表级权限不足；如需提升权限，请联系工作区拥有者【pdm_o】"
        )

    def test_editor_member_with_owner_nickname(self, db, _user, _ws, _member):
        owner = _user("pdm_o2", nickname="李四")
        editor = _user("pdm_e")
        ws = _ws("PdmWS2", owner=owner)
        _member(ws, editor, WorkspaceRole.EDITOR)
        detail = permission_denied_detail(db, ws, editor)
        assert detail == "当前用户在此工作区的角色为【编辑者】，权限不足；如需提升权限，请联系工作区拥有者【李四】"

    def test_non_member_prompts_join(self, db, _user, _ws):
        owner = _user("pdm_o3")
        outsider = _user("pdm_out")
        ws = _ws("PdmWS3", owner=owner)
        detail = permission_denied_detail(db, ws, outsider, scope="视图级")
        assert detail == "你不是该工作区成员，视图级权限不足；如需加入，请联系工作区拥有者【pdm_o3】"

    def test_owner_missing_drops_contact(self, db, _user, _ws, _member):
        viewer = _user("pdm_v2")
        ws = _ws("PdmWS4")  # 无 owner 成员
        _member(ws, viewer, WorkspaceRole.VIEWER)
        detail = permission_denied_detail(db, ws, viewer, scope="工作区级")
        assert detail == "当前用户在此工作区的角色为【查看者】，工作区级权限不足"

    def test_requirement_appended(self, db, _user, _ws, _member):
        owner = _user("pdm_o4")
        editor = _user("pdm_e2")
        ws = _ws("PdmWS5", owner=owner)
        _member(ws, editor, WorkspaceRole.EDITOR)
        detail = permission_denied_detail(db, ws, editor, requirement="仅 owner/editor 可合并修改申请")
        assert detail.endswith("（仅 owner/editor 可合并修改申请）")


class TestRaisePermissionDenied:
    def test_raises_permission_denied_error(self, db, _user, _ws, _member):
        owner = _user("pdm_o5")
        viewer = _user("pdm_v3")
        ws = _ws("PdmWS6", owner=owner)
        _member(ws, viewer, WorkspaceRole.VIEWER)
        with pytest.raises(PermissionDeniedError) as exc:
            raise_permission_denied(db, ws, viewer, scope="表级")
        assert exc.value.status_code == 403
        assert exc.value.code == "permission_denied"
        assert "角色为【查看者】" in exc.value.detail
        assert exc.value.to_payload()["code"] == "permission_denied"
