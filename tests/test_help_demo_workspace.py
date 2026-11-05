"""帮助页「创建示例工作区」接口（需求 0106）.

覆盖：
- 未登录 401 / 未知场景 404；
- 成功创建：在当前用户名下新建、既有工作区不受影响、导入内容非空；
- 重复创建自动加后缀，不覆盖前一个示例；
- 归档资产缺失时返回 404，不 500。
"""

from __future__ import annotations

from sqlalchemy import func, select

from cndb.plugins.help.services import demo_workspace
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

CREATE_URL = "/api/v1/help/examples/{scenario}/workspace"


def test_create_demo_workspace_requires_auth(client):
    assert client.post(CREATE_URL.format(scenario="sales")).status_code == 401


def test_create_demo_workspace_unknown_scenario(client, auth_headers):
    resp = client.post(CREATE_URL.format(scenario="nope"), headers=auth_headers)
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "示例工作区暂不可用"


def test_create_demo_workspace_creates_new_workspace(client, auth_headers, db):
    before = db.execute(select(func.count(Workspace.id))).scalar_one()

    resp = client.post(CREATE_URL.format(scenario="sales"), headers=auth_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()

    assert body["workspace_id"] > 0
    assert body["imported_tables"] > 0
    assert body["imported_rows"] > 0
    assert body["imported_views"] > 0
    assert body["imported_documents"] > 0
    assert body["name"].endswith("（示例）")
    assert body["errors"] == []

    # 只新增一个工作区，既有数据不受影响
    assert db.execute(select(func.count(Workspace.id))).scalar_one() == before + 1

    workspace = db.get(Workspace, body["workspace_id"])
    assert workspace is not None
    member = db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id)).scalar_one()
    assert member.role == WorkspaceRole.OWNER
    assert workspace.created_by_id == member.user_id


def test_create_demo_workspace_repeat_gets_unique_name(client, auth_headers, db):
    first = client.post(CREATE_URL.format(scenario="research"), headers=auth_headers)
    assert first.status_code == 201, first.text
    second = client.post(CREATE_URL.format(scenario="research"), headers=auth_headers)
    assert second.status_code == 201, second.text

    assert first.json()["name"] != second.json()["name"]
    assert second.json()["name"].endswith("（示例）（2）")
    assert first.json()["workspace_id"] != second.json()["workspace_id"]


def test_create_demo_workspace_missing_asset_returns_404(client, auth_headers, monkeypatch, db):
    monkeypatch.setattr(demo_workspace, "resolve_demo_pack", lambda _scenario: None)
    before = db.execute(select(func.count(Workspace.id))).scalar_one()

    resp = client.post(CREATE_URL.format(scenario="sales"), headers=auth_headers)

    assert resp.status_code == 404, resp.text
    assert db.execute(select(func.count(Workspace.id))).scalar_one() == before
