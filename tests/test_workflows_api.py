"""workflows 插件 API 集成测试.

覆盖：CRUD / 节点 / 边 / 权限 / 级联删除 / 自环 / 跨工作区绑表.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workflows.models import Workflow, WorkflowEdge, WorkflowNode
from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

# ── 辅助 fixture ─────────────────────────────────────


@pytest.fixture
def ws_with_table(client: TestClient, auth_headers: dict, db: Session):
    """创建一个工作区 + 一张带 name 字段的数据表."""
    # 创建工作区
    r = client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "测试工作区"},
    )
    assert r.status_code in (200, 201), f"创建工作区失败: {r.text}"
    ws_data = r.json()
    wid = ws_data["id"]

    # 直接用 ORM 建表（API 建表会触发动态 DDL，测试里麻烦）
    import secrets

    dt = DataTable(
        workspace_id=wid,
        name="需求表",
        db_table_name=f"table_{secrets.token_hex(6)}",
    )
    db.add(dt)
    db.commit()
    db.refresh(dt)

    # 添加一个字段
    field = DataField(
        table_id=dt.id,
        name="标题",
        field_type="text",
        db_column_name="field_title",
        order=0,
    )
    db.add(field)
    db.commit()

    return wid, dt.id


@pytest.fixture
def second_ws(client: TestClient, auth_headers: dict):
    """创建第二个工作区（测试跨工作区绑表）."""
    r = client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "其他工作区"},
    )
    assert r.status_code in (200, 201)
    return r.json()["id"]


# ── Workflow CRUD ────────────────────────────────────


class TestWorkflowCRUD:
    """工作流 CRUD 基本测试."""

    def test_list_empty(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.get(f"/api/v1/workspaces/{wid}/workflows", headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_create_workflow(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "采购流程", "description": "示例流程"},
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "采购流程"
        assert data["node_count"] == 0
        assert data["id"] is not None

    def test_create_empty_name_rejected(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "   "},
        )
        assert r.status_code == 400

    def test_get_detail(self, client, auth_headers, ws_with_table, db):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        r = client.get(f"/api/v1/workspaces/{wid}/workflows/{fwid}", headers=auth_headers)
        assert r.status_code == 200
        assert r.json()["id"] == fwid
        assert r.json()["nodes"] == []
        assert r.json()["edges"] == []

    def test_get_404_wrong_workspace(self, client, auth_headers, ws_with_table, second_ws):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]
        # 用 second_ws 的 id 去查 wid 下的 workflow，应该 404
        r = client.get(f"/api/v1/workspaces/{second_ws}/workflows/{fwid}", headers=auth_headers)
        assert r.status_code == 404

    def test_update_workflow(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "旧名称"},
        )
        fwid = r.json()["id"]

        r = client.patch(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}",
            headers=auth_headers,
            json={"name": "新名称", "order": 10},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "新名称"
        assert r.json()["order"] == 10

    def test_delete_workflow(self, client, auth_headers, ws_with_table, db):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        r = client.delete(f"/api/v1/workspaces/{wid}/workflows/{fwid}", headers=auth_headers)
        assert r.status_code == 204
        assert db.query(Workflow).filter(Workflow.id == fwid).count() == 0


# ── Node 管理 ────────────────────────────────────────


class TestWorkflowNodes:
    """节点 CRUD 测试."""

    def test_add_node_with_binding(self, client, auth_headers, ws_with_table):
        wid, tid = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={
                "name": "需求审核",
                "table_id": tid,
                "pos_x": 100,
                "pos_y": 200,
                "config": {"default_view_id": None},
            },
        )
        assert r.status_code == 201
        node = r.json()
        assert node["name"] == "需求审核"
        assert node["table_id"] == tid
        assert node["pos_x"] == 100
        # table 摘要暂为 None（create 端点不查）
        assert node["table"] is None

    def test_add_node_no_binding(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "待办", "table_id": None},
        )
        assert r.status_code == 201
        assert r.json()["table_id"] is None

    def test_add_node_cross_workspace_table_rejected(self, client, auth_headers, ws_with_table, second_ws, db):
        wid, _ = ws_with_table
        # 在 second_ws 里建表
        import secrets as _secrets

        dt = DataTable(
            workspace_id=second_ws,
            name="外部表",
            db_table_name=f"table_{_secrets.token_hex(6)}",
        )
        db.add(dt)
        db.commit()

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        # 尝试绑定其他工作区的表
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "跨区节点", "table_id": dt.id},
        )
        assert r.status_code == 400
        assert "不能绑定其他工作区的表" in r.json()["detail"]

    def test_add_node_nonexistent_table_rejected(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "坏节点", "table_id": 99999},
        )
        assert r.status_code == 400

    def test_update_node(self, client, auth_headers, ws_with_table):
        wid, tid = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        ).json()["id"]

        nid = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "旧名", "table_id": tid},
        ).json()["id"]

        r = client.patch(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes/{nid}",
            headers=auth_headers,
            json={"name": "新名", "pos_x": 999},
        )
        assert r.status_code == 200
        assert r.json()["name"] == "新名"
        assert r.json()["pos_x"] == 999

    def test_delete_node_cascades_edges(self, client, auth_headers, ws_with_table, db):
        wid, tid = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        ).json()["id"]

        n1 = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "A", "table_id": tid},
        ).json()["id"]
        n2 = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "B", "table_id": tid},
        ).json()["id"]

        client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges",
            headers=auth_headers,
            json={"source_node_id": n1, "target_node_id": n2},
        )

        # 删除 n1，相关边应级联删除
        client.delete(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes/{n1}",
            headers=auth_headers,
        )

        node = db.query(WorkflowNode).filter(WorkflowNode.id == n1).first()
        assert node is None
        edge = db.query(WorkflowEdge).filter(
            WorkflowEdge.workflow_id == fwid, WorkflowEdge.target_node_id == n2
        ).first()
        # n2 作为 target 的那条边也应被级联（因为 source n1 被删）
        assert edge is None


# ── Edge 管理 ────────────────────────────────────────


class TestWorkflowEdges:
    """边 CRUD + 校验测试."""

    def _setup(self, client, auth_headers, ws_with_table):
        wid, tid = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        ).json()["id"]
        n1 = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "A", "table_id": tid},
        ).json()["id"]
        n2 = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "B", "table_id": tid},
        ).json()["id"]
        return wid, fwid, n1, n2

    def test_add_edge(self, client, auth_headers, ws_with_table):
        wid, fwid, n1, n2 = self._setup(client, auth_headers, ws_with_table)
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges",
            headers=auth_headers,
            json={"source_node_id": n1, "target_node_id": n2, "label": "同意"},
        )
        assert r.status_code == 201
        assert r.json()["label"] == "同意"

    def test_self_loop_rejected(self, client, auth_headers, ws_with_table):
        wid, fwid, n1, _ = self._setup(client, auth_headers, ws_with_table)
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges",
            headers=auth_headers,
            json={"source_node_id": n1, "target_node_id": n1},
        )
        assert r.status_code == 400
        assert "自环" in r.json()["detail"]

    def test_duplicate_edge_rejected(self, client, auth_headers, ws_with_table):
        wid, fwid, n1, n2 = self._setup(client, auth_headers, ws_with_table)
        url = f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges"
        client.post(url, headers=auth_headers, json={"source_node_id": n1, "target_node_id": n2})
        r = client.post(url, headers=auth_headers, json={"source_node_id": n1, "target_node_id": n2})
        assert r.status_code == 400
        assert "已存在" in r.json()["detail"]

    def test_edge_endpoint_out_of_workflow_rejected(self, client, auth_headers, ws_with_table):
        wid, fwid, n1, _ = self._setup(client, auth_headers, ws_with_table)
        # 创建另一个 workflow 的节点
        fwid2 = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F2"},
        ).json()["id"]
        n_other = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid2}/nodes",
            headers=auth_headers,
            json={"name": "C"},
        ).json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges",
            headers=auth_headers,
            json={"source_node_id": n1, "target_node_id": n_other},
        )
        assert r.status_code == 400
        assert "端点必须属于该工作流" in r.json()["detail"]

    def test_update_edge_label(self, client, auth_headers, ws_with_table):
        wid, fwid, n1, n2 = self._setup(client, auth_headers, ws_with_table)
        eid = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges",
            headers=auth_headers,
            json={"source_node_id": n1, "target_node_id": n2, "label": "旧"},
        ).json()["id"]

        r = client.patch(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges/{eid}",
            headers=auth_headers,
            json={"label": "新"},
        )
        assert r.status_code == 200
        assert r.json()["label"] == "新"

    def test_delete_edge(self, client, auth_headers, ws_with_table, db):
        wid, fwid, n1, n2 = self._setup(client, auth_headers, ws_with_table)
        eid = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges",
            headers=auth_headers,
            json={"source_node_id": n1, "target_node_id": n2},
        ).json()["id"]

        r = client.delete(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges/{eid}",
            headers=auth_headers,
        )
        assert r.status_code == 204
        assert db.query(WorkflowEdge).filter(WorkflowEdge.id == eid).count() == 0


# ── 权限 ──────────────────────────────────────────────


class TestWorkflowPermissions:
    """角色权限测试."""

    def test_viewer_can_read(self, client, auth_headers, ws_with_table, db):
        wid, _ = ws_with_table
        # 注册另一个用户并设为 viewer

        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "viewer", "email": "v@t.com", "password": "passw0rd"},
        )
        viewer_id = r.json()["id"]
        # 直接 ORM 加为 viewer
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer_id, role=WorkspaceRole.VIEWER))
        db.commit()

        # 用 owner 创建工作流
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        ).json()["id"]

        # viewer 登录
        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "viewer", "password": "passw0rd"},
        )
        viewer_token = r.json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        # viewer 可以读
        r = client.get(f"/api/v1/workspaces/{wid}/workflows", headers=viewer_headers)
        assert r.status_code == 200
        r = client.get(f"/api/v1/workspaces/{wid}/workflows/{fwid}", headers=viewer_headers)
        assert r.status_code == 200

        # viewer 不能写
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=viewer_headers,
            json={"name": "F2"},
        )
        assert r.status_code == 403

    def test_editor_can_crud_nodes(self, client, auth_headers, ws_with_table, db):
        wid, tid = ws_with_table

        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "editor", "email": "e@t.com", "password": "passw0rd"},
        )
        editor_id = r.json()["id"]
        db.add(WorkspaceMember(workspace_id=wid, user_id=editor_id, role=WorkspaceRole.EDITOR))
        db.commit()

        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        ).json()["id"]

        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "editor", "password": "passw0rd"},
        )
        editor_token = r.json()["access_token"]
        ed = {"Authorization": f"Bearer {editor_token}"}

        # editor 可以加节点
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=ed,
            json={"name": "E1", "table_id": tid},
        )
        assert r.status_code == 201

        # editor 不能删工作流（ADMIN 以上才行）
        r = client.delete(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}",
            headers=ed,
        )
        assert r.status_code == 403

    def test_no_auth_401(self, client, ws_with_table):
        wid, _ = ws_with_table
        r = client.get(f"/api/v1/workspaces/{wid}/workflows")
        assert r.status_code in (401, 403)


# ── 详情序列化 ────────────────────────────────────────


class TestWorkflowDetail:
    """详情接口返回的节点是否携带 table 摘要."""

    def test_detail_includes_node_table_brief(self, client, auth_headers, ws_with_table):
        wid, tid = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        ).json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "审核", "table_id": tid},
        )

        r = client.get(f"/api/v1/workspaces/{wid}/workflows/{fwid}", headers=auth_headers)
        data = r.json()
        assert len(data["nodes"]) == 1
        node = data["nodes"][0]
        assert node["table_id"] == tid
        assert node["table"] is not None
        assert node["table"]["id"] == tid
        assert node["table"]["name"] == "需求表"
        assert "view_count" in node["table"]

    def test_detail_unbound_when_table_trashed(self, client, auth_headers, ws_with_table, db):
        """表被软删时节点应显示未绑定（table=None）."""
        wid, tid = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        ).json()["id"]
        client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "审核", "table_id": tid},
        )

        # 软删表
        dt = db.query(DataTable).filter(DataTable.id == tid).first()
        dt.trashed = True
        db.commit()

        r = client.get(f"/api/v1/workspaces/{wid}/workflows/{fwid}", headers=auth_headers)
        node = r.json()["nodes"][0]
        assert node["table_id"] == tid  # FK 仍指向
        assert node["table"] is None  # 但摘要为 None


# ── 边界 404 覆盖 ─────────────────────────────────────


class TestWorkflowNotFound:
    """各种 404 边界：工作区不存在、工作流不存在、节点不存在、边不存在."""

    def test_workspace_404_on_get(self, client, auth_headers):
        r = client.get("/api/v1/workspaces/99999/workflows", headers=auth_headers)
        assert r.status_code == 404

    def test_workspace_404_on_create(self, client, auth_headers):
        r = client.post(
            "/api/v1/workspaces/99999/workflows",
            headers=auth_headers,
            json={"name": "X"},
        )
        assert r.status_code == 404

    def test_workflow_404_on_get(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.get(f"/api/v1/workspaces/{wid}/workflows/99999", headers=auth_headers)
        assert r.status_code == 404

    def test_workflow_404_on_patch(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.patch(
            f"/api/v1/workspaces/{wid}/workflows/99999",
            headers=auth_headers,
            json={"name": "X"},
        )
        assert r.status_code == 404

    def test_workflow_404_on_delete(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.delete(f"/api/v1/workspaces/{wid}/workflows/99999", headers=auth_headers)
        assert r.status_code == 404

    def test_workflow_404_on_add_node(self, client, auth_headers, ws_with_table):
        wid, tid = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/99999/nodes",
            headers=auth_headers,
            json={"name": "X", "table_id": tid},
        )
        assert r.status_code == 404

    def test_node_404_on_patch(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F"},
        ).json()["id"]
        r = client.patch(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes/99999",
            headers=auth_headers,
            json={"name": "X"},
        )
        assert r.status_code == 404

    def test_node_404_on_delete(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F"},
        ).json()["id"]
        r = client.delete(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes/99999",
            headers=auth_headers,
        )
        assert r.status_code == 404

    def test_workflow_404_on_add_edge(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/99999/edges",
            headers=auth_headers,
            json={"source_node_id": 1, "target_node_id": 2},
        )
        assert r.status_code == 404

    def test_edge_404_on_patch(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F"},
        ).json()["id"]
        r = client.patch(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges/99999",
            headers=auth_headers,
            json={"label": "X"},
        )
        assert r.status_code == 404

    def test_edge_404_on_delete(self, client, auth_headers, ws_with_table):
        wid, _ = ws_with_table
        fwid = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F"},
        ).json()["id"]
        r = client.delete(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/edges/99999",
            headers=auth_headers,
        )
        assert r.status_code == 404


__all__ = [
    "TestWorkflowCRUD",
    "TestWorkflowDetail",
    "TestWorkflowEdges",
    "TestWorkflowNodes",
    "TestWorkflowNotFound",
    "TestWorkflowPermissions",
]
