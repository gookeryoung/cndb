"""共享 fixture：测试用户、API 客户端与工作区."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User
from cndb.workspaces.models import Workspace, WorkspaceMember


@pytest.fixture
def user(db: object) -> User:
    """标准测试用户."""
    return User.objects.create_user(
        username="alice",
        email="alice@example.com",
        password="Str0ng-Pass-42",
        nickname="爱丽丝",
    )


@pytest.fixture
def api() -> APIClient:
    """未认证 API 客户端."""
    return APIClient()


@pytest.fixture
def auth_client(api: APIClient, user: User) -> APIClient:
    """以 user 身份认证的 API 客户端."""
    api.force_authenticate(user=user)
    return api


@pytest.fixture
def workspace(db: object, user: User) -> Workspace:
    """测试工作区，user 为所有者."""
    ws = Workspace.objects.create(name="测试工作区", created_by=user)
    WorkspaceMember.objects.create(workspace=ws, user=user, role=WorkspaceMember.Role.OWNER)
    return ws


@pytest.fixture
def viewer(user: User, workspace: Workspace) -> User:
    """只读成员."""
    other = User.objects.create_user(username="bob", email="bob@example.com", password="Str0ng-Pass-42")
    WorkspaceMember.objects.create(workspace=workspace, user=other, role=WorkspaceMember.Role.VIEWER)
    return other
