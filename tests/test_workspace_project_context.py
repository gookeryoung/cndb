"""工作区项目上下文（ADR 0122）：spec 校验 / 项目级生命周期 / 接口 / 文档."""

from __future__ import annotations

import pytest

from cndb.plugins.workspaces.services.templates.spec import TemplateSpecError, normalize_spec

PROJECT_SPEC = {
    "project": {
        "root_form": "apply",
        "link_field": "所属项目",
        "title_field": "项目名称",
        "documents": "per_project",
    },
    "forms": [
        {
            "key": "apply",
            "name": "申报表",
            "scope": "project",
            "fields": [
                {"name": "项目名称", "type": "text", "required": True},
                {"name": "负责人", "type": "text"},
            ],
        },
        {
            "key": "progress",
            "name": "进展表",
            "scope": "project",
            "fields": [
                {"name": "所属项目", "type": "link", "config": {"target_form": "apply", "multiple": False}},
                {"name": "进展说明", "type": "longtext"},
            ],
        },
        {
            "key": "owner",
            "name": "负责人库",
            "scope": "workspace",
            "fields": [{"name": "姓名", "type": "text"}],
        },
    ],
    "documents": [
        {
            "key": "proposal",
            "title": "立项申请书",
            "naming": "{项目名称}-立项申请书",
            "required": True,
        },
        {
            "key": "midterm",
            "title": "中期报告",
            "naming": "{项目名称}-中期报告",
            "required": True,
        },
    ],
    "stages": [
        {
            "key": "proposal",
            "name": "立项",
            "order": 1,
            "forms": ["apply", "owner"],
            "documents": ["proposal"],
        },
        {
            "key": "execution",
            "name": "实施",
            "order": 2,
            "forms": ["progress", "owner"],
            "documents": ["midterm"],
        },
    ],
}


def _create_template(client, headers, spec: dict, name: str = "项目模板") -> dict:
    r = client.post(
        "/api/v1/workspace-templates",
        json={"name": name, "description": "项目上下文测试", "spec": spec},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_workspace(client, headers, template_id: int, name: str = "项目工作区") -> dict:
    r = client.post("/api/v1/workspaces", json={"name": name, "template_id": template_id}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def _forms_by_name(payload: dict) -> dict[str, dict]:
    """从数据流程响应（flows → steps → form）提取按表单名索引的表单元数据."""
    result: dict[str, dict] = {}
    for flow in payload.get("flows", []):
        for step in flow.get("steps", []):
            form = step.get("form")
            if form:
                result[form["name"]] = form
    return result


def _records(client, headers, workspace_id: int, table_id: int, values: dict) -> dict:
    r = client.post(
        f"/api/v1/workspaces/{workspace_id}/tables/{table_id}/records",
        json={"values": values},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_project_spec_normalization():
    spec = normalize_spec(PROJECT_SPEC)
    assert spec["project"]["root_form"] == "apply"
    assert spec["project"]["documents"] == "per_project"
    scopes = {f["key"]: f["scope"] for f in spec["forms"]}
    assert scopes == {"apply": "project", "progress": "project", "owner": "workspace"}

    # 有 project 块时非根表单必须显式声明 scope
    missing_scope = {
        **PROJECT_SPEC,
        "forms": [
            PROJECT_SPEC["forms"][0],
            {
                "key": "progress",
                "name": "进展表",
                "fields": [{"name": "所属项目", "type": "link", "config": {"target_form": "apply", "multiple": False}}],
            },
        ],
    }
    with pytest.raises(TemplateSpecError):
        normalize_spec(missing_scope)

    # link_field 必须指向根表单
    bad_link = {
        **PROJECT_SPEC,
        "forms": [
            PROJECT_SPEC["forms"][0],
            {
                "key": "progress",
                "name": "进展表",
                "scope": "project",
                "fields": [{"name": "所属项目", "type": "link", "config": {"target_form": "apply", "multiple": True}}],
            },
            PROJECT_SPEC["forms"][2],
        ],
    }
    with pytest.raises(TemplateSpecError):
        normalize_spec(bad_link)

    # 无 project 块的旧模板保持工作区级
    legacy = normalize_spec(
        {
            "forms": [{"key": "a", "name": "A", "fields": [{"name": "x", "type": "text"}]}],
            "documents": [],
            "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": []}],
        }
    )
    assert "project" not in legacy
    assert legacy["forms"][0]["scope"] == "workspace"


def test_project_list_response_accepts_link_field_mapping():
    """link_field 支持按表单映射（科研模板「所属项目」/「所属课题」并存）."""
    from cndb.plugins.workspaces.schemas.projects import ProjectListResponse

    resp = ProjectListResponse(
        project_mode="project",
        root_form="project_application",
        link_field={"project_progress": "所属项目", "project_budget": "所属课题"},
        title_field="项目名称",
        items=[],
        total=0,
    )
    assert resp.link_field == {"project_progress": "所属项目", "project_budget": "所属课题"}


def test_project_lifecycle_isolation_data_flow_and_documents(client, auth_headers):
    template = _create_template(client, auth_headers, PROJECT_SPEC)
    ws = _create_workspace(client, auth_headers, template["id"])
    assert ws["project_mode"] == "project"

    flow = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers)
    assert flow.status_code == 409
    assert flow.json()["detail"]["code"] == "project_empty"

    # 通过数据表接口直接建两个项目（先取表 id）
    tables = client.get(f"/api/v1/workspaces/{ws['id']}/tables", headers=auth_headers)
    assert tables.status_code == 200, tables.text
    table_map = {t["name"]: t["id"] for t in tables.json()}
    apply_id = table_map["申报表"]
    progress_id = table_map["进展表"]
    owner_id = table_map["负责人库"]

    p1 = _records(client, auth_headers, ws["id"], apply_id, {"项目名称": "项目A"})
    p2 = _records(client, auth_headers, ws["id"], apply_id, {"项目名称": "项目B"})
    _records(client, auth_headers, ws["id"], progress_id, {"所属项目": [p1["id"]], "进展说明": "A 进展"})
    # 工作区级表单：两行共享，不应计入任何项目门禁
    _records(client, auth_headers, ws["id"], owner_id, {"姓名": "张三"})
    _records(client, auth_headers, ws["id"], owner_id, {"姓名": "李四"})

    # 多项目未选择 → 422
    required = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers)
    assert required.status_code == 422
    assert required.json()["detail"]["code"] == "project_required"
    lifecycle_required = client.get(f"/api/v1/workspaces/{ws['id']}/lifecycle", headers=auth_headers)
    assert lifecycle_required.status_code == 422

    # 项目清单：两行，均未初始化
    projects = client.get(f"/api/v1/workspaces/{ws['id']}/projects", headers=auth_headers)
    assert projects.status_code == 200, projects.text
    listing = projects.json()
    assert listing["total"] == 2
    assert {item["title"] for item in listing["items"]} == {"项目A", "项目B"}
    assert all(item["initialized"] is False for item in listing["items"])

    # 项目文档：每项目一套，标题按 naming 渲染
    for pid in (p1["id"], p2["id"]):
        docs = client.post(f"/api/v1/workspaces/{ws['id']}/projects/{pid}/documents", headers=auth_headers)
        assert docs.status_code == 200, docs.text
        assert docs.json()["created"] == 2

    titles = client.get(f"/api/v1/workspaces/{ws['id']}/documents?project_id={p1['id']}", headers=auth_headers)
    assert titles.status_code == 200, titles.text
    names = {item["title"] for item in titles.json()["items"]}
    assert "项目A-立项申请书" in names
    assert "项目A-中期报告" in names
    assert "项目B-立项申请书" not in names

    # 项目级门禁：A 的进展行只计入 A
    flow_a = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow?project_id={p1['id']}", headers=auth_headers)
    assert flow_a.status_code == 200, flow_a.text
    a_progress = _forms_by_name(flow_a.json())["进展表"]
    assert a_progress["record_count"] == 1
    assert a_progress["scope"] == "project"

    flow_b = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow?project_id={p2['id']}", headers=auth_headers)
    b_progress = _forms_by_name(flow_b.json())["进展表"]
    assert b_progress["record_count"] == 0

    # 推进 A：立项门禁已满足；B 仍停留在立项
    advanced = client.post(
        f"/api/v1/workspaces/{ws['id']}/lifecycle/advance",
        json={"project_id": p1["id"]},
        headers=auth_headers,
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["current_stage"] == "execution"
    assert advanced.json()["project_id"] == p1["id"]

    state_b = client.get(f"/api/v1/workspaces/{ws['id']}/lifecycle?project_id={p2['id']}", headers=auth_headers)
    assert state_b.status_code == 200
    assert state_b.json()["current_stage"] == "proposal"

    # 工作区级表单行不参与项目门禁：B 的阶段仅因进展缺失而失败，与负责人库无关
    execution_b = next(s for s in state_b.json()["stages"] if s["key"] == "execution")
    owner_check = next(c for c in execution_b["forms"] if c["key"] == "owner")
    assert owner_check["scope"] == "workspace"
    assert owner_check["row_count"] == 2

    # 启用项目模式补齐未初始化项目（A 已推进有状态，只为 B 建一条），再次调用幂等
    enabled = client.post(f"/api/v1/workspaces/{ws['id']}/project-mode/enable", json={}, headers=auth_headers)
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["projects"] == 2
    assert enabled.json()["initialized"] == 1
    again = client.post(f"/api/v1/workspaces/{ws['id']}/project-mode/enable", json={}, headers=auth_headers)
    assert again.status_code == 200
    assert again.json()["initialized"] == 0

    # 根表单中不存在的项目行 → 404（动态表行 ID 按表自增，跨表同号无法区分，按本表查无处理）
    missing = client.get(f"/api/v1/workspaces/{ws['id']}/lifecycle?project_id=999999", headers=auth_headers)
    assert missing.status_code == 404


def test_enable_project_mode_rejects_legacy_template(client, auth_headers):
    legacy_spec = {
        "forms": [{"key": "a", "name": "A", "fields": [{"name": "x", "type": "text"}]}],
        "documents": [],
        "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": []}],
    }
    template = _create_template(client, auth_headers, legacy_spec, name="旧模板")
    ws = _create_workspace(client, auth_headers, template["id"])
    assert ws["project_mode"] == "workspace"

    projects = client.get(f"/api/v1/workspaces/{ws['id']}/projects", headers=auth_headers)
    assert projects.status_code == 200
    assert projects.json()["project_mode"] == "workspace"
    assert projects.json()["total"] == 0

    enabled = client.post(f"/api/v1/workspaces/{ws['id']}/project-mode/enable", json={}, headers=auth_headers)
    assert enabled.status_code == 409
