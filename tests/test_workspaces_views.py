"""workspaces 视图测试：工作区 CRUD 与成员管理."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.workspaces.models import Workspace, WorkspaceMember

pytestmark = pytest.mark.django_db

WORKSPACES_URL = "/api/workspaces/"


def _make_user(username: str) -> User:
    """创建辅助用户."""
    return User.objects.create_user(
        username=username,
        email=f"{username}@example.com",
        password="Str0ng-Pass-44",
    )


@pytest.fixture
def workspace(user: User) -> Workspace:
    """由 user 担任 OWNER 的工作区."""
    ws = Workspace.objects.create(name="测试工作区", created_by=user)
    WorkspaceMember.objects.create(workspace=ws, user=user, role=WorkspaceMember.Role.OWNER)
    return ws


def _add_member(workspace: Workspace, user: User, role: str) -> WorkspaceMember:
    """直接落库添加成员，绕过 API."""
    return WorkspaceMember.objects.create(workspace=workspace, user=user, role=role)


def test_create_workspace_registers_creator_as_owner(auth_client: APIClient, user: User) -> None:
    """创建工作区：创建者自动成为 OWNER 成员."""
    resp = auth_client.post(WORKSPACES_URL, {"name": "新工作区"}, format="json")
    assert resp.status_code == 201
    assert resp.data["role"] == "owner"
    member = WorkspaceMember.objects.get(workspace__name="新工作区", user=user)
    assert member.role == WorkspaceMember.Role.OWNER


def test_list_shows_only_own_workspaces(auth_client: APIClient, workspace: Workspace) -> None:
    """列表仅返回自己是成员的工作区."""
    Workspace.objects.create(name="别人的工作区")
    resp = auth_client.get(WORKSPACES_URL)
    assert resp.status_code == 200
    names = [item["name"] for item in resp.data["results"]]
    assert names == ["测试工作区"]


def test_retrieve_workspace_as_member(auth_client: APIClient, workspace: Workspace) -> None:
    """成员可读取工作区详情并看到自己的角色."""
    resp = auth_client.get(f"{WORKSPACES_URL}{workspace.id}/")
    assert resp.status_code == 200
    assert resp.data["role"] == "owner"


def test_non_member_gets_404(api: APIClient, user: User, workspace: Workspace) -> None:
    """非成员访问他人工作区：404."""
    api.force_authenticate(user=_make_user("mallory"))
    resp = api.get(f"{WORKSPACES_URL}{workspace.id}/")
    assert resp.status_code == 404


def test_rename_requires_admin(auth_client: APIClient, user: User, workspace: Workspace) -> None:
    """VIEWER 改名工作区：403."""
    _add_member(workspace, _make_user("bob"), WorkspaceMember.Role.VIEWER)
    workspace.members.filter(user=user).update(role=WorkspaceMember.Role.VIEWER)
    resp = auth_client.patch(f"{WORKSPACES_URL}{workspace.id}/", {"name": "改名"}, format="json")
    assert resp.status_code == 403


def test_member_list_visible_to_viewer(api: APIClient, workspace: Workspace) -> None:
    """VIEWER 可查看成员列表."""
    viewer = _make_user("viewer")
    _add_member(workspace, viewer, WorkspaceMember.Role.VIEWER)
    api.force_authenticate(user=viewer)
    resp = api.get(f"{WORKSPACES_URL}{workspace.id}/members/")
    assert resp.status_code == 200
    assert len(resp.data["results"]) == 2


def test_add_member_by_owner(auth_client: APIClient, workspace: Workspace) -> None:
    """OWNER 添加成员：201 且角色正确."""
    _make_user("bob")
    resp = auth_client.post(
        f"{WORKSPACES_URL}{workspace.id}/members/",
        {"username": "bob", "role": "editor"},
        format="json",
    )
    assert resp.status_code == 201
    assert resp.data["role"] == "editor"
    assert resp.data["user"]["username"] == "bob"


def test_add_member_requires_admin(api: APIClient, workspace: Workspace) -> None:
    """VIEWER 添加成员：403."""
    viewer = _make_user("viewer")
    _add_member(workspace, viewer, WorkspaceMember.Role.VIEWER)
    _make_user("bob")
    api.force_authenticate(user=viewer)
    resp = api.post(
        f"{WORKSPACES_URL}{workspace.id}/members/",
        {"username": "bob", "role": "editor"},
        format="json",
    )
    assert resp.status_code == 403


def test_add_member_unknown_username(auth_client: APIClient, workspace: Workspace) -> None:
    """添加不存在的用户：404."""
    resp = auth_client.post(
        f"{WORKSPACES_URL}{workspace.id}/members/",
        {"username": "nobody", "role": "editor"},
        format="json",
    )
    assert resp.status_code == 404


def test_add_duplicate_member_rejected(auth_client: APIClient, workspace: Workspace) -> None:
    """重复添加已有成员：400."""
    bob = _make_user("bob")
    _add_member(workspace, bob, WorkspaceMember.Role.VIEWER)
    resp = auth_client.post(
        f"{WORKSPACES_URL}{workspace.id}/members/",
        {"username": "bob", "role": "editor"},
        format="json",
    )
    assert resp.status_code == 400


def test_add_owner_role_rejected(auth_client: APIClient, workspace: Workspace) -> None:
    """直接添加 OWNER 角色：400."""
    _make_user("bob")
    resp = auth_client.post(
        f"{WORKSPACES_URL}{workspace.id}/members/",
        {"username": "bob", "role": "owner"},
        format="json",
    )
    assert resp.status_code == 400


def test_change_role_by_owner(auth_client: APIClient, workspace: Workspace) -> None:
    """OWNER 修改成员角色：200 且落库."""
    bob = _make_user("bob")
    member = _add_member(workspace, bob, WorkspaceMember.Role.VIEWER)
    resp = auth_client.patch(
        f"{WORKSPACES_URL}{workspace.id}/members/{member.id}/",
        {"role": "admin"},
        format="json",
    )
    assert resp.status_code == 200
    member.refresh_from_db()
    assert member.role == WorkspaceMember.Role.ADMIN


def test_last_owner_cannot_be_demoted(auth_client: APIClient, workspace: Workspace) -> None:
    """唯一 OWNER 降级自己：400."""
    member = workspace.members.get()
    resp = auth_client.patch(
        f"{WORKSPACES_URL}{workspace.id}/members/{member.id}/",
        {"role": "admin"},
        format="json",
    )
    assert resp.status_code == 400


def test_last_owner_cannot_be_removed(auth_client: APIClient, workspace: Workspace) -> None:
    """唯一 OWNER 被移除：400."""
    member = workspace.members.get()
    resp = auth_client.delete(f"{WORKSPACES_URL}{workspace.id}/members/{member.id}/")
    assert resp.status_code == 400


def test_admin_cannot_modify_owner(api: APIClient, user: User, workspace: Workspace) -> None:
    """ADMIN 修改 OWNER 角色：403."""
    admin = _make_user("admin")
    _add_member(workspace, admin, WorkspaceMember.Role.ADMIN)
    owner_member = workspace.members.get(user=user)
    api.force_authenticate(user=admin)
    resp = api.patch(
        f"{WORKSPACES_URL}{workspace.id}/members/{owner_member.id}/",
        {"role": "viewer"},
        format="json",
    )
    assert resp.status_code == 403


def test_remove_member_by_owner(auth_client: APIClient, workspace: Workspace) -> None:
    """OWNER 移除普通成员：204."""
    bob = _make_user("bob")
    member = _add_member(workspace, bob, WorkspaceMember.Role.EDITOR)
    resp = auth_client.delete(f"{WORKSPACES_URL}{workspace.id}/members/{member.id}/")
    assert resp.status_code == 204
    assert not WorkspaceMember.objects.filter(id=member.id).exists()


def test_member_role_permission_helpers(workspace: Workspace) -> None:
    """角色判定函数：成员与非成员、最低角色要求."""
    from cndb.workspaces.permissions import get_member_role, has_role

    bob = _make_user("bob")
    _add_member(workspace, bob, WorkspaceMember.Role.EDITOR)
    assert get_member_role(bob, workspace) == WorkspaceMember.Role.EDITOR
    assert has_role(bob, workspace, WorkspaceMember.Role.EDITOR)
    assert not has_role(bob, workspace, WorkspaceMember.Role.ADMIN)
    mallory = _make_user("mallory")
    assert get_member_role(mallory, workspace) is None
    assert not has_role(mallory, workspace, WorkspaceMember.Role.VIEWER)
    assert get_member_role(None, workspace) is None


def test_workspace_member_unique_constraint(workspace: Workspace) -> None:
    """同工作区同用户重复加入：IntegrityError."""
    from django.db import IntegrityError

    bob = _make_user("bob")
    _add_member(workspace, bob, WorkspaceMember.Role.VIEWER)
    with pytest.raises(IntegrityError):
        WorkspaceMember.objects.create(workspace=workspace, user=bob, role=WorkspaceMember.Role.EDITOR)


def test_model_str_methods(workspace: Workspace) -> None:
    """模型 __str__ 展示."""
    bob = _make_user("bob")
    member = _add_member(workspace, bob, WorkspaceMember.Role.VIEWER)
    assert str(workspace) == "测试工作区"
    assert str(member) == f"{workspace.id}/{bob.id}"


def test_non_member_cannot_list_members(api: APIClient, workspace: Workspace) -> None:
    """非成员访问成员列表：403."""
    api.force_authenticate(user=_make_user("mallory"))
    resp = api.get(f"{WORKSPACES_URL}{workspace.id}/members/")
    assert resp.status_code == 403


def test_update_member_role_via_put(auth_client: APIClient, workspace: Workspace) -> None:
    """PUT 全量更新成员角色同样受保护规则约束."""
    bob = _make_user("bob")
    member = _add_member(workspace, bob, WorkspaceMember.Role.VIEWER)
    resp = auth_client.put(
        f"{WORKSPACES_URL}{workspace.id}/members/{member.id}/",
        {"role": "editor", "user": bob.id, "created_on": "ignored"},
        format="json",
    )
    assert resp.status_code == 200
    member.refresh_from_db()
    assert member.role == WorkspaceMember.Role.EDITOR


def test_is_workspace_member_rejects_non_workspace() -> None:
    """权限类对非工作区对象直接拒绝."""
    from rest_framework.test import APIRequestFactory

    from cndb.workspaces.permissions import IsWorkspaceMember

    request = APIRequestFactory().get("/")
    assert IsWorkspaceMember().has_object_permission(request, None, object()) is False  # type: ignore[bad-argument-type]
