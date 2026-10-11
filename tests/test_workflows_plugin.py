"""workflows 插件测试：模型注册 / 插件发现 / 路由挂载 / 图校验 / 审批流 CRUD."""

from __future__ import annotations

import itertools

import pytest

from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.workflows.schemas.models import WorkflowEdgeSave, WorkflowNodeSave
from cndb.plugins.workflows.services.graph import validate_graph_payload
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

BASE = "/api/v1/workspaces/{wid}"


def _nodes(*specs: tuple[str, str, str]) -> list[WorkflowNodeSave]:
    """按 (key, node_type, approver_role) 快速构造节点列表."""
    return [WorkflowNodeSave(key=k, name=k, node_type=t, approver_role=r) for k, t, r in specs]


def _chain(specs: list[WorkflowNodeSave]) -> list[WorkflowEdgeSave]:
    """按列表顺序串成线性链."""
    return [WorkflowEdgeSave(source=a.key, target=b.key) for a, b in itertools.pairwise(specs)]


@pytest.fixture
def owner(db) -> User:
    u = User(username="wf_owner", nickname="审批管理员")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner) -> Workspace:
    w = Workspace(name="WfWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


@pytest.fixture
def viewer(db, ws) -> User:
    u = User(username="wf_viewer", nickname="只读成员")
    u.set_password("passw0rd")
    db.add(u)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=u.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(u)
    return u


def _auth(client, user) -> dict[str, str]:
    r = client.post("/api/v1/accounts/auth/login", json={"login": user.username, "password": "passw0rd"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── 模型与插件装配 ──────────────────────────────────────


def test_workflow_models_in_metadata() -> None:
    """workflows 全部模型应注册到 Base.metadata."""
    for name in (
        "workflows_workflow",
        "workflows_workflownode",
        "workflows_workflowedge",
        "workflows_approvalinstance",
        "workflows_approvalaction",
    ):
        assert name in Base.metadata.tables


def test_workflows_plugin_discovered() -> None:
    """插件自动发现应加载 workflows 插件."""
    from cndb.core.plugin_registry import PluginRegistry

    r = PluginRegistry()
    r.discover_and_load()
    names = {p["name"] for p in r.get_plugin_info_list()}
    assert "workflows" in names


def test_workflows_routes_mounted(client, ws) -> None:
    """workflows 路由应挂载（未认证访问返回 401/403 而非 404）."""
    assert client.get(f"{BASE.format(wid=ws.id)}/workflows").status_code in (401, 403)
    assert client.get(f"{BASE.format(wid=ws.id)}/approvals").status_code in (401, 403)


# ── 图校验（服务层单元）─────────────────────────────────


def test_validate_chain_ok() -> None:
    """合法线性链（start→approval→end）通过."""
    nodes = _nodes(("s", "start", ""), ("a", "approval", "editor"), ("e", "end", ""))
    assert validate_graph_payload(nodes, _chain(nodes)) == []


def test_validate_missing_approval() -> None:
    """缺少审批节点时报错."""
    nodes = _nodes(("s", "start", ""), ("e", "end", ""))
    errs = validate_graph_payload(nodes, _chain(nodes))
    assert any("审批节点" in e for e in errs)


def test_validate_branch_rejected() -> None:
    """分叉（一个节点多个出边）被拒绝."""
    nodes = _nodes(("s", "start", ""), ("a", "approval", "editor"), ("b", "approval", "admin"), ("e", "end", ""))
    edges = [
        WorkflowEdgeSave(source="s", target="a"),
        WorkflowEdgeSave(source="a", target="b"),
        WorkflowEdgeSave(source="a", target="e"),
        WorkflowEdgeSave(source="b", target="e"),
    ]
    errs = validate_graph_payload(nodes, edges)
    assert any("分叉" in e for e in errs)


def test_validate_bad_role() -> None:
    """审批角色非法时报错."""
    nodes = _nodes(("s", "start", ""), ("a", "approval", "boss"), ("e", "end", ""))
    errs = validate_graph_payload(nodes, _chain(nodes))
    assert any("角色" in e for e in errs)


def test_validate_stray_node() -> None:
    """游离节点（不在链上）被拒绝."""
    nodes = _nodes(("s", "start", ""), ("a", "approval", "editor"), ("e", "end", ""), ("x", "approval", "admin"))
    edges = _chain(nodes[:3])
    errs = validate_graph_payload(nodes, edges)
    assert any("游离" in e for e in errs)


def test_validate_missing_end_reachable() -> None:
    """start 无法到达 end 时报错."""
    nodes = _nodes(("s", "start", ""), ("a", "approval", "editor"), ("e", "end", ""))
    edges = [WorkflowEdgeSave(source="a", target="e")]  # start 无出边
    errs = validate_graph_payload(nodes, edges)
    assert errs


# ── 审批流 CRUD（API）──────────────────────────────────


def test_workflow_crud_roundtrip(client, ws, owner) -> None:
    """创建→详情→更新→列表→删除 全链路."""
    headers = _auth(client, owner)
    url = BASE.format(wid=ws.id) + "/workflows"
    body = {
        "name": "请假审批",
        "description": "两级审批",
        "nodes": [
            {"key": "s", "name": "提交", "node_type": "start"},
            {"key": "a1", "name": "主管审批", "node_type": "approval", "approver_role": "editor"},
            {"key": "a2", "name": "经理审批", "node_type": "approval", "approver_role": "admin"},
            {"key": "e", "name": "结束", "node_type": "end"},
        ],
        "edges": [
            {"source": "s", "target": "a1"},
            {"source": "a1", "target": "a2"},
            {"source": "a2", "target": "e"},
        ],
    }
    r = client.post(url, json=body, headers=headers)
    assert r.status_code == 201, r.text
    wf = r.json()
    assert [n["node_type"] for n in wf["nodes"]] == ["start", "approval", "approval", "end"]

    r = client.get(f"{url}/{wf['id']}", headers=headers)
    assert r.status_code == 200
    assert len(r.json()["edges"]) == 3

    # 整图覆盖更新：去掉二级审批
    body2 = {
        "name": "请假审批",
        "description": "一级审批",
        "nodes": [
            {"key": "s", "name": "提交", "node_type": "start"},
            {"key": "a1", "name": "主管审批", "node_type": "approval", "approver_role": "editor"},
            {"key": "e", "name": "结束", "node_type": "end"},
        ],
        "edges": [{"source": "s", "target": "a1"}, {"source": "a1", "target": "e"}],
    }
    r = client.patch(f"{url}/{wf['id']}", json=body2, headers=headers)
    assert r.status_code == 200
    assert len(r.json()["nodes"]) == 3

    r = client.get(url, headers=headers)
    assert r.status_code == 200 and len(r.json()) == 1

    r = client.delete(f"{url}/{wf['id']}", headers=headers)
    assert r.status_code == 204


def test_workflow_create_invalid_graph_400(client, ws, owner) -> None:
    """非法图保存返回 400 带中文明细."""
    headers = _auth(client, owner)
    url = BASE.format(wid=ws.id) + "/workflows"
    r = client.post(
        url,
        json={"name": "坏图", "nodes": [{"key": "s", "node_type": "start"}], "edges": []},
        headers=headers,
    )
    assert r.status_code == 400
    assert "审批节点" in r.json()["detail"]


def test_workflow_permission_matrix(client, ws, owner, viewer) -> None:
    """viewer 可查看但不可创建；非成员 403."""
    owner_headers = _auth(client, owner)
    viewer_headers = _auth(client, viewer)
    url = BASE.format(wid=ws.id) + "/workflows"
    body = {
        "name": "审批流",
        "nodes": [
            {"key": "s", "node_type": "start"},
            {"key": "a", "node_type": "approval", "approver_role": "editor"},
            {"key": "e", "node_type": "end"},
        ],
        "edges": [{"source": "s", "target": "a"}, {"source": "a", "target": "e"}],
    }
    r = client.post(url, json=body, headers=viewer_headers)
    assert r.status_code == 403
    r = client.post(url, json=body, headers=owner_headers)
    assert r.status_code == 201
    r = client.get(url, headers=viewer_headers)
    assert r.status_code == 200


__all__ = []
