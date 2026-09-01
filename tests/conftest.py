"""共享 fixture：测试用户与 API 客户端."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from cndb.accounts.models import User


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
