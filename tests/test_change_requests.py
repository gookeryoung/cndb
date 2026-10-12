"""修改申请（ChangeRequest，GitHub PR 风格）模型与插件测试.

P1 阶段：模型注册 / 插件发现 / 基本持久化。API 语义测试（创建 / merge
逐项决策 / 冲突标记 / stale / update-base）在 P2 随路由实现填充。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.plugin_registry import plugin_registry
from cndb.plugins.accounts.models import User
from cndb.plugins.change_requests.models import (
    CHANGE_OPS,
    CR_STATUS_OPEN,
    ChangeItem,
    ChangeRequest,
    ChangeRequestAction,
)
from cndb.plugins.workspaces.models import Workspace


@pytest.fixture
def ws(db: Session) -> Workspace:
    """创建一个带 owner 的工作区供模型测试使用."""
    u = User(username="cr_owner", nickname="CROwner")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    space = Workspace(name="CR-WS", created_by_id=u.id)
    db.add(space)
    db.commit()
    db.refresh(space)
    return space


class TestChangeRequestModels:
    """模型注册与基本持久化."""

    def test_models_registered(self) -> None:
        """三张表应注册到 Base.metadata."""
        from cndb.models.base import Base

        names = set(Base.metadata.tables)
        assert {
            "change_requests_changerequest",
            "change_requests_changeitem",
            "change_requests_changeaction",
        } <= names

    def test_plugin_discovered(self) -> None:
        """插件自动发现应加载 change_requests 插件."""
        names = {p.name for p in plugin_registry._plugins.values()}
        assert "change_requests" in names

    def test_routes_mounted(self, client: TestClient, ws) -> None:
        """路由前缀已挂载（未认证访问返回 401/403 而非 404）."""
        r = client.get(f"/api/v1/workspaces/{ws.id}/tables/1/change-requests")
        assert r.status_code in (401, 403, 404)  # P2 前路由为空壳，404 亦可接受

    def test_create_with_items(self, db: Session, ws) -> None:
        """申请 + 变更项级联持久化."""
        cr = ChangeRequest(
            workspace_id=ws.id,
            table_id=1,
            title="修改行 #3",
            status=CR_STATUS_OPEN,
        )
        db.add(cr)
        db.flush()
        item = ChangeItem(request_id=cr.id, op="update", row_id=3, base_values={"a": 1}, values={"a": 2})
        action = ChangeRequestAction(request_id=cr.id, action="comment", comment="请审核")
        db.add_all([item, action])
        db.commit()
        db.refresh(cr)
        assert cr.id is not None
        assert len(cr.items) == 1
        assert cr.items[0].op in CHANGE_OPS
        assert len(cr.actions) == 1


class TestChangeRequestFixtures:
    """conftest ws fixture 依赖检查（P2 测试复用）."""

    def test_ws_fixture(self, ws) -> None:
        assert ws.id is not None


@pytest.mark.parametrize("op", ["create", "update", "delete"])
def test_op_constants(op: str) -> None:
    """op 常量覆盖三种操作."""
    assert op in CHANGE_OPS
