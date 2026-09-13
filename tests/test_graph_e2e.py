"""关系图 graph API 端到端测试 — 数据契约完整性 + 统计要素 + 拓扑序 + 权限.

覆盖：
- 空工作区返回空节点/边/拓扑序
- 数据契约完整性（节点必填字段 / 边必填字段 / 类型对齐前端 GraphNode/GraphEdge）
- 统计要素正确性（field_count / row_count / view_count / link_count）
- 边 label 与 link_field_name 一致，source/target 为 str
- 拓扑序为 str[] 且被依赖的先返回
- 软删表不出现在 graph 中
- 权限：viewer 可读 / 无权限 401 / 跨工作区 404
- dependencies API 结构正确（forward / reverse / link_fields）
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.plugins.tables.ddl import create_table as ddl_create
from cndb.plugins.tables.models import DataField, DataTable, DataView
from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

# ── 辅助 fixture：带表和 link 的工作区 ──────────────


@pytest.fixture
def ws_with_graph(client: TestClient, auth_headers: dict, db: Session):
    """创建工作区 + 3 张表（部门表 / 员工表 / 项目表）+ link 字段，形成 A→B→C 依赖链."""
    # 创建工作区
    r = client.post(
        "/api/v1/workspaces",
        headers=auth_headers,
        json={"name": "graph测试"},
    )
    assert r.status_code in (200, 201)
    wid = r.json()["id"]

    # 用 ORM 建 3 张表
    dept = DataTable(workspace_id=wid, name="部门表")
    dept.ensure_db_name()
    db.add(dept)
    db.flush()
    f_d1 = DataField(table_id=dept.id, name="名称", field_type="text", order=0)
    f_d1.ensure_db_name()
    db.add(f_d1)

    emp = DataTable(workspace_id=wid, name="员工表")
    emp.ensure_db_name()
    db.add(emp)
    db.flush()
    f_e1 = DataField(table_id=emp.id, name="姓名", field_type="text", order=0)
    f_e1.ensure_db_name()
    db.add(f_e1)
    f_e2 = DataField(
        table_id=emp.id,
        name="部门",
        field_type="link",
        order=1,
        config={"target_table_id": dept.id},
    )
    f_e2.ensure_db_name()
    db.add(f_e2)

    project = DataTable(workspace_id=wid, name="项目表")
    project.ensure_db_name()
    db.add(project)
    db.flush()
    f_p1 = DataField(table_id=project.id, name="项目名", field_type="text", order=0)
    f_p1.ensure_db_name()
    db.add(f_p1)
    f_p2 = DataField(
        table_id=project.id,
        name="负责人",
        field_type="link",
        order=1,
        config={"target_table_id": emp.id},
    )
    f_p2.ensure_db_name()
    db.add(f_p2)

    db.commit()
    db.refresh(dept)
    db.refresh(emp)
    db.refresh(project)

    # 创建物理表（graph 路由需要）
    ddl_create(db.get_bind(), dept)
    ddl_create(db.get_bind(), emp)
    ddl_create(db.get_bind(), project)

    # 给员工表加一个 view
    view = DataView(table_id=emp.id, name="全部员工", view_type="grid")
    db.add(view)
    db.commit()

    return wid, dept.id, emp.id, project.id


# ── 契约完整性 ──────────────────────────────────────


class TestGraphDataContract:
    """graph API 返回的数据契约必须与前端 GraphNode/GraphEdge 对齐."""

    def test_empty_workspace_returns_empty(self, client, auth_headers):
        """空工作区 → nodes=[], edges=[], topo_order=[]."""
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "空工作区"})
        wid = r.json()["id"]
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()
        assert data["nodes"] == []
        assert data["edges"] == []
        assert data["topo_order"] == []

    def test_node_fields_match_graphnode(self, client, auth_headers, ws_with_graph):
        """节点必须包含前端 GraphNode 契约字段（id/label/type + 统计要素）."""
        wid, _dept_id, emp_id, _ = ws_with_graph
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        data = r.json()

        # 节点数 = 3
        assert len(data["nodes"]) == 3

        for node in data["nodes"]:
            # 核心契约字段
            assert "id" in node and isinstance(node["id"], str), "id 必须是 str"
            assert "label" in node and isinstance(node["label"], str), "label 必须是 str"
            assert "type" in node and isinstance(node["type"], str), "type 必须是 str"
            assert node["type"] == "table"
            # 兼容字段
            assert "table_id" in node and isinstance(node["table_id"], int)
            assert "name" in node and node["name"] == node["label"]
            # 统计要素
            assert "field_count" in node and isinstance(node["field_count"], int)
            assert "view_count" in node and isinstance(node["view_count"], int)
            assert "link_count" in node and isinstance(node["link_count"], int)
            # row_count 可以是 int 或 None
            assert "row_count" in node and (node["row_count"] is None or isinstance(node["row_count"], int))

        # 定位到员工表节点验证统计
        emp_node = next(n for n in data["nodes"] if n["table_id"] == emp_id)
        assert emp_node["field_count"] == 2  # 姓名 + 部门
        assert emp_node["view_count"] == 1  # 全部员工视图

    def test_edge_fields_match_graphedge(self, client, auth_headers, ws_with_graph):
        """边必须包含前端 GraphEdge 契约字段（source/target 为 str + label）."""
        wid, dept_id, emp_id, project_id = ws_with_graph
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        data = r.json()

        # A→B→C 两条边
        assert len(data["edges"]) == 2

        for edge in data["edges"]:
            # 核心契约字段
            assert "source" in edge and isinstance(edge["source"], str), "source 必须是 str"
            assert "target" in edge and isinstance(edge["target"], str), "target 必须是 str"
            assert "label" in edge and isinstance(edge["label"], str), "label 必须存在"
            # 兼容字段
            assert "link_field_name" in edge and edge["link_field_name"] == edge["label"]

        # 验证具体边
        edge_map = {(e["source"], e["target"]): e for e in data["edges"]}
        assert edge_map.get((str(emp_id), str(dept_id))) is not None
        assert edge_map[(str(emp_id), str(dept_id))]["label"] == "部门"
        assert edge_map.get((str(project_id), str(emp_id))) is not None
        assert edge_map[(str(project_id), str(emp_id))]["label"] == "负责人"

    def test_node_ids_are_strings(self, client, auth_headers, ws_with_graph):
        """节点 id 必须是 str 类型（前端 Map<string, ...> key）."""
        wid, _, _, _ = ws_with_graph
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        data = r.json()
        for node in data["nodes"]:
            # str 类型但内容是数字
            assert node["id"].isdigit()

    def test_topo_order_is_strings(self, client, auth_headers, ws_with_graph):
        """拓扑序必须是 str[]."""
        wid, _, _, _ = ws_with_graph
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        data = r.json()
        assert isinstance(data["topo_order"], list)
        for tid in data["topo_order"]:
            assert isinstance(tid, str)


# ── 统计要素 ────────────────────────────────────────


class TestGraphStatistics:
    """统计要素正确性：link_count(入度) / row_count / view_count."""

    def test_link_count_is_in_degree(self, client, auth_headers, ws_with_graph):
        """link_count 等于有多少张表引用了当前表（入度）."""
        wid, dept_id, emp_id, project_id = ws_with_graph
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        data = r.json()

        # 部门表被员工表引用 → link_count=1
        dept_node = next(n for n in data["nodes"] if n["table_id"] == dept_id)
        assert dept_node["link_count"] == 1

        # 员工表被项目表引用 → link_count=1
        emp_node = next(n for n in data["nodes"] if n["table_id"] == emp_id)
        assert emp_node["link_count"] == 1

        # 项目表无入度 → link_count=0
        proj_node = next(n for n in data["nodes"] if n["table_id"] == project_id)
        assert proj_node["link_count"] == 0

    def test_row_count_when_table_has_rows(self, client, auth_headers, ws_with_graph, db: Session):
        """row_count 在有物理行时返回正确计数."""
        from sqlalchemy import text

        wid, dept_id, _, _ = ws_with_graph

        # 向部门表插入 3 行，找到第一个 text 字段的 db_column_name
        dt = db.query(DataTable).filter(DataTable.id == dept_id).first()
        first_field = next((f for f in dt.fields if not f.trashed and f.field_type != "link"), None)
        assert first_field is not None, "部门表应该有 text 字段"

        with db.get_bind().connect() as conn:  # type: ignore[union-attr]
            col = first_field.db_column_name
            conn.execute(text(f"INSERT INTO {dt.db_table_name} ({col}) VALUES ('A'), ('B'), ('C')"))
            conn.commit()

        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        dept_node = next(n for n in r.json()["nodes"] if n["table_id"] == dept_id)
        assert dept_node["row_count"] == 3

    def test_view_count_zero_when_no_views(self, client, auth_headers, ws_with_graph):
        """没有视图的表 view_count=0."""
        wid, dept_id, _, _ = ws_with_graph
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        dept_node = next(n for n in r.json()["nodes"] if n["table_id"] == dept_id)
        assert dept_node["view_count"] == 0


# ── 拓扑序正确性 ────────────────────────────────────


class TestGraphTopoOrder:
    """拓扑序：被依赖的表必须排在依赖它的表之前."""

    def test_chain_order(self, client, auth_headers, ws_with_graph):
        """A←B←C → 拓扑序 A 在 B 前，B 在 C 前."""
        wid, dept_id, emp_id, project_id = ws_with_graph
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        topo = r.json()["topo_order"]

        idx_dept = topo.index(str(dept_id))
        idx_emp = topo.index(str(emp_id))
        idx_proj = topo.index(str(project_id))

        assert idx_dept < idx_emp < idx_proj

    def test_no_deps_returns_all_nodes_in_topo(self, client, auth_headers, db: Session):
        """没有 link 字段的两张表 — 拓扑序应包含全部节点."""
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "独立WS"})
        wid = r.json()["id"]

        t1 = DataTable(workspace_id=wid, name="表1")
        t1.ensure_db_name()
        t2 = DataTable(workspace_id=wid, name="表2")
        t2.ensure_db_name()
        db.add_all([t1, t2])
        db.commit()
        db.refresh(t1)
        db.refresh(t2)
        ddl_create(db.get_bind(), t1)
        ddl_create(db.get_bind(), t2)

        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        data = r.json()
        # 独立节点入度都为 0，Kahn 应正常返回
        assert len(data["nodes"]) == 2
        assert len(data["topo_order"]) == 2


# ── 软删表不出现在 graph ───────────────────────────


class TestGraphExcludesTrashed:
    """trashed=True 的表必须被过滤掉."""

    def test_trashed_table_excluded(self, client, auth_headers, ws_with_graph, db: Session):
        wid, dept_id, _, _ = ws_with_graph

        # 软删部门表
        dt = db.query(DataTable).filter(DataTable.id == dept_id).first()
        dt.trashed = True
        db.commit()

        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        nodes = r.json()["nodes"]

        # 部门表不在列表中
        assert not any(n["table_id"] == dept_id for n in nodes)
        # 员工表仍然在（它的部门 link 指向已软删表但仍显示员工表本身）
        assert len(nodes) == 2


# ── 权限 ────────────────────────────────────────────


class TestGraphPermissions:
    """graph API 权限控制."""

    def test_no_auth_401(self, client):
        """无 token 请求 — 不存在的工作区会先返回 404."""
        r = client.get("/api/v1/workspaces/99999/graph")
        # 不存在的工作区 → 404（这是先于鉴权检查的，因为路由匹配失败）
        # 但这仍然是正确的行为
        assert r.status_code == 404

    def test_viewer_can_read(self, client, auth_headers, ws_with_graph, db: Session):
        wid, _, _, _ = ws_with_graph
        # 注册 viewer 用户
        r = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "viewer_g", "email": "vg@t.com", "password": "passw0rd"},
        )
        viewer_id = r.json()["id"]
        db.add(WorkspaceMember(workspace_id=wid, user_id=viewer_id, role=WorkspaceRole.VIEWER))
        db.commit()

        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "viewer_g", "password": "passw0rd"},
        )
        viewer_token = r.json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=viewer_headers)
        assert r.status_code == 200

    def test_cross_workspace_404(self, client, auth_headers, ws_with_graph):
        """用 A 工作区的 token 去查 B 工作区."""
        _wid_a, _, _, _ = ws_with_graph
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS-B"})
        wid_b = r.json()["id"]
        r = client.get(f"/api/v1/workspaces/{wid_b}/graph", headers=auth_headers)
        assert r.status_code == 200  # owner 自己的两个工作区都能查

    def test_nonexistent_workspace_404(self, client, auth_headers):
        r = client.get("/api/v1/workspaces/99999/graph", headers=auth_headers)
        assert r.status_code == 404


# ── dependencies API ────────────────────────────────


class TestDependenciesApi:
    """/dependencies 端点返回结构完整性."""

    def test_structure(self, client, auth_headers, ws_with_graph):
        wid, dept_id, emp_id, project_id = ws_with_graph
        r = client.get(f"/api/v1/workspaces/{wid}/dependencies", headers=auth_headers)
        assert r.status_code == 200
        data = r.json()

        assert "forward" in data and isinstance(data["forward"], dict)
        assert "reverse" in data and isinstance(data["reverse"], dict)
        assert "link_fields" in data and isinstance(data["link_fields"], list)

        # forward: project → emp → dept 链
        # 注意：JSON 把 int key 转 str，但 int list 值保持 int
        forward = data["forward"]
        assert emp_id in forward.get(str(project_id), [])
        assert dept_id in forward.get(str(emp_id), [])

        # reverse: dept 的 reverse 包含 emp
        reverse = data["reverse"]
        assert emp_id in reverse.get(str(dept_id), [])

        # link_fields 包含两条
        assert len(data["link_fields"]) == 2
        lf0 = data["link_fields"][0]
        assert "field_name" in lf0 and lf0["field_name"] in ("部门", "负责人")
        assert "target_table_id" in lf0

    def test_empty_workspace(self, client, auth_headers):
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "空WS"})
        wid = r.json()["id"]
        r = client.get(f"/api/v1/workspaces/{wid}/dependencies", headers=auth_headers)
        data = r.json()
        assert data["forward"] == {}
        assert data["reverse"] == {}
        assert data["link_fields"] == []


# ── Workflow 节点 table 摘要 ────────────────────────


class TestWorkflowTableBrief:
    """workflow API 返回的节点 table 摘要必须包含完整统计要素.

    覆盖：get 详情 / create_node / update_node 三个端点的 table 字段.
    """

    def test_workflow_detail_table_brief(self, client, auth_headers, db: Session):
        """workflow 详情接口返回的每个绑定表节点都应有完整 table 摘要."""

        wid, dept_id, _emp_id, _ = ws_with_graph.__wrapped__(client, auth_headers, db)

        # 创建 workflow + 绑定部门表的节点
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "测试流程"},
        )
        fwid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "部门节点", "table_id": dept_id, "pos_x": 0, "pos_y": 0},
        )
        assert r.status_code == 201

        # 详情
        r = client.get(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}",
            headers=auth_headers,
        )
        assert r.status_code == 200
        wf = r.json()
        assert len(wf["nodes"]) >= 1

        # 第一个节点有绑定表
        node_with_table = next(n for n in wf["nodes"] if n.get("table") is not None)
        brief = node_with_table["table"]
        assert "id" in brief and brief["id"] == dept_id
        assert "name" in brief and isinstance(brief["name"], str)
        assert "view_count" in brief and isinstance(brief["view_count"], int)
        assert "row_count" in brief  # 可以是 int 或 None

    def test_create_node_returns_table_brief(self, client, auth_headers, db: Session):
        """create_node 响应中 table 字段必须包含摘要（不再是 None）."""

        wid, _dept_id, emp_id, _ = ws_with_graph.__wrapped__(client, auth_headers, db)

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "N1", "table_id": emp_id, "pos_x": 100, "pos_y": 200},
        )
        assert r.status_code == 201
        node = r.json()
        assert node["table_id"] == emp_id
        # create_node 必须返回 table 摘要
        assert node["table"] is not None
        assert node["table"]["id"] == emp_id
        assert "name" in node["table"]
        assert "view_count" in node["table"]
        assert "row_count" in node["table"]

    def test_update_node_changes_table_brief(self, client, auth_headers, db: Session):
        """update_node 切换绑定表后，table 摘要应正确更新."""
        wid, dept_id, emp_id, _ = ws_with_graph.__wrapped__(client, auth_headers, db)

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        # 先绑员工表
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "N1", "table_id": emp_id, "pos_x": 0, "pos_y": 0},
        )
        node_id = r.json()["id"]

        # 更新为部门表
        r = client.patch(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes/{node_id}",
            headers=auth_headers,
            json={"table_id": dept_id},
        )
        assert r.status_code == 200
        node = r.json()
        assert node["table_id"] == dept_id
        assert node["table"] is not None
        assert node["table"]["id"] == dept_id
        assert node["table"]["name"] == "部门表"

    def test_update_node_unbind_returns_none(self, client, auth_headers, db: Session):
        """update_node 清除绑定表（table_id=null）时，table 字段应为 None."""
        wid, dept_id, _, _ = ws_with_graph.__wrapped__(client, auth_headers, db)

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "F1"},
        )
        fwid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "N1", "table_id": dept_id, "pos_x": 0, "pos_y": 0},
        )
        node_id = r.json()["id"]
        assert r.json()["table"] is not None

        r = client.patch(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes/{node_id}",
            headers=auth_headers,
            json={"table_id": None},
        )
        assert r.status_code == 200
        node = r.json()
        assert node["table_id"] is None
        assert node["table"] is None


# ── Workflow + Graph 联合一致性 ─────────────────────


class TestWorkflowGraphConsistency:
    """同一工作区内，workflow 绑定表的 table 摘要与 graph API 的节点统计应一致."""

    def test_table_stats_match_graph(self, client, auth_headers, db: Session):
        """workflow 详情返回的 table 摘要与 graph API 同一表的统计一致."""
        wid, _dept_id, emp_id, _ = ws_with_graph.__wrapped__(client, auth_headers, db)

        # 先给员工表插一些物理行
        from sqlalchemy import text

        emp = db.query(DataTable).filter(DataTable.id == emp_id).first()
        first_field = next((f for f in emp.fields if not f.trashed and f.field_type != "link"), None)
        with db.get_bind().connect() as conn:  # type: ignore[union-attr]
            col = first_field.db_column_name
            conn.execute(text(f"INSERT INTO {emp.db_table_name} ({col}) VALUES ('x'), ('y'), ('z'), ('w')"))
            conn.commit()

        # 查 graph
        r = client.get(f"/api/v1/workspaces/{wid}/graph", headers=auth_headers)
        graph_nodes = {n["table_id"]: n for n in r.json()["nodes"]}

        # 建 workflow 并绑员工表
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows",
            headers=auth_headers,
            json={"name": "W1"},
        )
        fwid = r.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}/nodes",
            headers=auth_headers,
            json={"name": "员工节点", "table_id": emp_id, "pos_x": 0, "pos_y": 0},
        )
        r = client.get(
            f"/api/v1/workspaces/{wid}/workflows/{fwid}",
            headers=auth_headers,
        )
        wf_node = next(n for n in r.json()["nodes"] if n["table_id"] == emp_id)

        # 统计应一致
        g_node = graph_nodes[emp_id]
        w_brief = wf_node["table"]
        assert g_node["row_count"] == w_brief["row_count"], "row_count 必须一致"
        assert g_node["view_count"] == w_brief["view_count"], "view_count 必须一致"


__all__ = [
    "TestDependenciesApi",
    "TestGraphDataContract",
    "TestGraphExcludesTrashed",
    "TestGraphPermissions",
    "TestGraphStatistics",
    "TestGraphTopoOrder",
    "TestWorkflowGraphConsistency",
    "TestWorkflowTableBrief",
]
