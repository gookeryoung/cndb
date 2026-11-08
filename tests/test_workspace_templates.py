"""工作区模板与生命周期（需求 0094）.

覆盖：规格校验 / 模板 CRUD / 按模板建工作区 / 门禁推进 / 更新 diff / 影响预览 /
破坏性变更 force 拦截 / 非破坏同步（不删存量表、字段、文档）。
"""

from __future__ import annotations

import pytest

from cndb.plugins.workspaces.services.templates.spec import TemplateSpecError, normalize_spec

SPEC = {
    "forms": [
        {
            "key": "apply",
            "name": "申报表",
            "fields": [
                {"name": "项目名称", "type": "text", "required": True},
                {"name": "负责人", "type": "text"},
            ],
        },
        {
            "key": "progress",
            "name": "进展表",
            "fields": [
                {"name": "所属项目", "type": "link", "config": {"target_form": "apply", "multiple": False}},
                {"name": "进展说明", "type": "longtext"},
            ],
        },
    ],
    "documents": [
        {"key": "proposal", "title": "立项申请书", "required": True, "content": "# 立项申请书\n"},
        {"key": "midterm", "title": "中期报告", "required": True},
    ],
    "stages": [
        {"key": "proposal", "name": "立项", "order": 1, "forms": ["apply"], "documents": ["proposal"]},
        {"key": "execution", "name": "实施", "order": 2, "forms": ["progress"], "documents": ["midterm"]},
    ],
}


def _create_template(client, headers, spec: dict | None = None, name: str = "科研测试模板") -> dict:
    r = client.post(
        "/api/v1/workspace-templates",
        json={"name": name, "description": "测试", "spec": spec or SPEC},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _create_workspace(client, headers, template_id: int) -> dict:
    r = client.post(
        "/api/v1/workspaces",
        json={"name": "模板工作区", "template_id": template_id},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_spec_validation_rejects_bad_references_and_orphans():
    bad_ref = {
        "forms": [{"key": "a", "name": "A", "fields": [{"name": "x", "type": "text"}]}],
        "documents": [],
        "stages": [{"key": "s", "name": "S", "forms": ["missing"], "documents": []}],
    }
    with pytest.raises(TemplateSpecError):
        normalize_spec(bad_ref)

    orphan = {
        "forms": [
            {"key": "a", "name": "A", "fields": [{"name": "x", "type": "text"}]},
            {"key": "b", "name": "B", "fields": [{"name": "y", "type": "text"}]},
        ],
        "documents": [],
        "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": []}],
    }
    with pytest.raises(TemplateSpecError):
        normalize_spec(orphan)


def test_template_crud_and_instantiation(client, auth_headers, db):
    template = _create_template(client, auth_headers)
    assert template["version"] == 1
    assert template["counts"] == {
        "stage_count": 2,
        "form_count": 2,
        "field_count": 4,
        "document_rule_count": 2,
        "flow_count": 0,
        "step_count": 0,
    }

    ws = _create_workspace(client, auth_headers, template["id"])
    assert ws["template_id"] == template["id"]
    assert ws["template_version"] == 1
    assert ws["template_stage"] == "proposal"

    detail = client.get(f"/api/v1/workspaces/{ws['id']}", headers=auth_headers).json()
    assert detail["template_stage"] == "proposal"
    assert detail["table_count"] == 2
    assert detail["document_count"] == 2  # 两份占位文档（阶段文件夹不计入文档数）

    lifecycle = client.get(f"/api/v1/workspaces/{ws['id']}/lifecycle", headers=auth_headers)
    assert lifecycle.status_code == 200, lifecycle.text
    state = lifecycle.json()
    assert state["current_stage"] == "proposal"
    assert state["can_advance"] is False
    gate_form = state["stages"][0]["forms"][0]
    assert gate_form["row_count"] == 0
    assert gate_form["satisfied"] is False
    assert state["stages"][0]["documents"][0]["satisfied"] is True

    # 门禁未过 → 409；强制推进成功并写入履历
    blocked = client.post(
        f"/api/v1/workspaces/{ws['id']}/lifecycle/advance",
        json={},
        headers=auth_headers,
    )
    assert blocked.status_code == 409
    forced = client.post(
        f"/api/v1/workspaces/{ws['id']}/lifecycle/advance",
        json={"force": True, "reason": "测试强制推进"},
        headers=auth_headers,
    )
    assert forced.status_code == 200, forced.text
    assert forced.json()["current_stage"] == "execution"
    assert forced.json()["history"][-1]["forced"] is True


def test_advance_after_gate_satisfied(client, auth_headers, db):
    template = _create_template(client, auth_headers)
    ws = _create_workspace(client, auth_headers, template["id"])

    from cndb.plugins.tables.models import DataTable

    table = db.query(DataTable).filter(DataTable.workspace_id == ws["id"], DataTable.name == "申报表").one()
    rec = client.post(
        f"/api/v1/workspaces/{ws['id']}/tables/{table.id}/records",
        json={"values": {"项目名称": "测试项目"}},
        headers=auth_headers,
    )
    assert rec.status_code == 201, rec.text

    state = client.get(f"/api/v1/workspaces/{ws['id']}/lifecycle", headers=auth_headers).json()
    assert state["can_advance"] is True
    advanced = client.post(
        f"/api/v1/workspaces/{ws['id']}/lifecycle/advance",
        json={},
        headers=auth_headers,
    )
    assert advanced.status_code == 200, advanced.text
    assert advanced.json()["current_stage"] == "execution"
    assert advanced.json()["stages"][0]["is_completed"] is True


def test_update_preview_diff_and_impact_force_gate(client, auth_headers, db):
    template = _create_template(client, auth_headers)
    ws = _create_workspace(client, auth_headers, template["id"])

    # 先造一条存量行：新增必填字段时不能因 NOT NULL 阻塞，且要计入待补值
    from cndb.plugins.tables.models import DataTable

    apply_table = db.query(DataTable).filter(DataTable.workspace_id == ws["id"], DataTable.name == "申报表").one()
    rec = client.post(
        f"/api/v1/workspaces/{ws['id']}/tables/{apply_table.id}/records",
        json={"values": {"项目名称": "存量项目", "负责人": "张三"}},
        headers=auth_headers,
    )
    assert rec.status_code == 201, rec.text

    # 新规格：删除阶段 execution（当前工作区仍在 proposal，不触发 stage fallback），
    # 新增必填字段、删除一个表单与一个文档规则
    new_spec = {
        "forms": [
            {
                "key": "apply",
                "name": "申报表",
                "fields": [
                    {"name": "项目名称", "type": "text", "required": True},
                    {"name": "负责人", "type": "text"},
                    {"name": "申报单位", "type": "text", "required": True},
                ],
            }
        ],
        "documents": [{"key": "proposal", "title": "立项申请书", "required": True}],
        "stages": [
            {"key": "proposal", "name": "立项", "order": 1, "forms": ["apply"], "documents": ["proposal"]},
        ],
    }
    preview = client.post(
        f"/api/v1/workspace-templates/{template['id']}/preview",
        json={"spec": new_spec},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    data = preview.json()
    kinds = {c["kind"] for c in data["diff"]["changes"]}
    assert {"field_added", "form_removed", "document_removed", "stage_removed"} <= kinds
    assert data["impact"]["summary"]["workspace_count"] == 1
    assert data["impact"]["summary"]["fields_to_add"] == 1
    assert data["impact"]["summary"]["orphan_forms"] == 1
    assert data["impact"]["summary"]["documents_to_create"] == 0
    # 新增必填字段不阻塞：存量行数计入 backfill 提示，但不需要 force
    assert data["impact"]["summary"]["rows_missing_required"] == 1
    assert data["impact"]["summary"]["required_fields_needing_backfill"] == 1
    assert data["requires_force"] is False

    updated = client.put(
        f"/api/v1/workspace-templates/{template['id']}",
        json={"spec": new_spec, "change_summary": "精简阶段", "force": False},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["template"]["version"] == 2
    assert body["applied"] is True
    assert body["sync"]["added_fields"] == 1

    # 非破坏：被移除的进展表、中期报告文档仍在；新字段已补上
    from cndb.plugins.documents.models import Document
    from cndb.plugins.tables.models import DataTable

    tables = db.query(DataTable).filter(DataTable.workspace_id == ws["id"]).all()
    assert {t.name for t in tables} == {"申报表", "进展表"}
    apply_table = next(t for t in tables if t.name == "申报表")
    new_field = next(f for f in apply_table.active_fields() if f.name == "申报单位")
    assert new_field.required is True
    # 物理列可空（存量行补值前不能 NOT NULL），但元数据必填保留
    from sqlalchemy import inspect as sa_inspect

    columns = {c["name"]: c for c in sa_inspect(db.get_bind()).get_columns(apply_table.db_table_name)}
    assert columns[new_field.db_column_name]["nullable"] is True
    titles = {
        d.title for d in db.query(Document).filter(Document.workspace_id == ws["id"], Document.is_deleted.is_(False))
    }
    assert {"立项申请书", "中期报告"} <= titles


def test_breaking_change_requires_force(client, auth_headers):
    template = _create_template(client, auth_headers)
    ws = _create_workspace(client, auth_headers, template["id"])

    # 删除当前阶段 proposal → 必须 force
    new_spec = {
        "forms": [{"key": "progress", "name": "进展表", "fields": [{"name": "进展说明", "type": "longtext"}]}],
        "documents": [{"key": "midterm", "title": "中期报告"}],
        "stages": [
            {"key": "execution", "name": "实施", "order": 1, "forms": ["progress"], "documents": ["midterm"]},
        ],
    }
    preview = client.post(
        f"/api/v1/workspace-templates/{template['id']}/preview",
        json={"spec": new_spec},
        headers=auth_headers,
    ).json()
    assert preview["requires_force"] is True
    assert preview["impact"]["summary"]["stages_fallback"] == 1

    blocked = client.put(
        f"/api/v1/workspace-templates/{template['id']}",
        json={"spec": new_spec, "force": False},
        headers=auth_headers,
    )
    assert blocked.status_code == 409
    detail = blocked.json()["detail"]
    assert detail["requires_force"] is True

    forced = client.put(
        f"/api/v1/workspace-templates/{template['id']}",
        json={"spec": new_spec, "force": True, "change_summary": "收口阶段"},
        headers=auth_headers,
    )
    assert forced.status_code == 200, forced.text
    state = client.get(f"/api/v1/workspaces/{ws['id']}/lifecycle", headers=auth_headers).json()
    assert state["current_stage"] == "execution"
    assert state["history"][-1]["reason"].startswith("模板同步")


def test_field_type_change_is_breaking(client, auth_headers, db):
    template = _create_template(client, auth_headers)
    ws = _create_workspace(client, auth_headers, template["id"])
    changed = {
        **SPEC,
        "forms": [
            {
                "key": "apply",
                "name": "申报表",
                "fields": [
                    {"name": "项目名称", "type": "text", "required": True},
                    {"name": "负责人", "type": "number"},
                ],
            },
            SPEC["forms"][1],
        ],
    }
    preview = client.post(
        f"/api/v1/workspace-templates/{template['id']}/preview",
        json={"spec": changed},
        headers=auth_headers,
    ).json()
    assert preview["requires_force"] is True
    assert preview["impact"]["summary"]["fields_type_conflict"] == 1
    assert any(c["kind"] == "field_type_changed" for c in preview["diff"]["changes"])

    # 物理字段类型不变（模板不改列类型）
    from cndb.plugins.tables.models import DataTable

    table = db.query(DataTable).filter(DataTable.workspace_id == ws["id"], DataTable.name == "申报表").one()
    field = next(f for f in table.active_fields() if f.name == "负责人")
    assert field.field_type == "text"


def test_builtin_research_template_spec_is_valid():
    """内置科研模板必须始终能通过 spec 校验（种子回归）."""
    from cndb.cli.seed.workspace_templates import RESEARCH_LIFECYCLE_SPEC

    spec = normalize_spec(RESEARCH_LIFECYCLE_SPEC)
    assert [s["key"] for s in spec["stages"]] == ["proposal", "execution", "completion"]
    assert {f["key"] for f in spec["forms"]} == {
        "project_application",
        "project_progress",
        "project_budget",
        "project_closure",
        "expense_claim",
        "achievement_registry",
        "project_change",
        "project_owner",
        "tech_system",
        "project_task",
        "project_todo",
        "resource_schedule",
        "funding_budget",
    }
    assert len(spec["documents"]) == 5
    assert {f["key"] for f in spec["flows"]} == {
        "project_lifecycle",
        "expense_reimbursement",
        "achievement_registration",
        "project_change",
        "owner_management",
        "tech_system_management",
        "task_breakdown_management",
        "todo_followup",
        "resource_schedule_management",
        "funding_management",
    }
    assert {f["key"]: f["stage"] for f in spec["flows"]} == {
        "project_lifecycle": "proposal",
        "expense_reimbursement": "execution",
        "achievement_registration": "completion",
        "project_change": "execution",
        "owner_management": "proposal",
        "tech_system_management": "proposal",
        "task_breakdown_management": "execution",
        "todo_followup": "execution",
        "resource_schedule_management": "execution",
        "funding_management": "execution",
    }
    assert spec["flows"][1]["steps"][1]["form"] is None


# ── 规格校验 / 路由分支覆盖 ──────────────────────────


def _bad_specs() -> list[dict]:
    base_form = {"key": "a", "name": "A", "fields": [{"name": "x", "type": "text"}]}
    base_stage = {"key": "s", "name": "S", "forms": ["a"], "documents": []}
    return [
        {"forms": "no", "documents": [], "stages": [base_stage]},
        {"forms": [{"key": "a", "name": "A", "fields": []}], "documents": [], "stages": [base_stage]},
        {"forms": [{**base_form, "extra": 1}], "documents": [], "stages": [base_stage]},
        {"forms": [{**base_form, "key": "bad key"}], "documents": [], "stages": [base_stage]},
        {
            "forms": [{**base_form, "fields": [{"name": "x", "type": "text"}, {"name": "x", "type": "text"}]}],
            "documents": [],
            "stages": [base_stage],
        },
        {"forms": [{**base_form, "fields": [{"name": "x", "type": "nope"}]}], "documents": [], "stages": [base_stage]},
        {
            "forms": [base_form],
            "documents": [{"key": "d", "title": "D"}, {"key": "d2", "title": "D"}],
            "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": ["d"]}],
        },
        {"forms": [base_form], "documents": [], "stages": []},
        {
            "forms": [base_form],
            "documents": [],
            "stages": [{"key": "s", "name": "S", "order": 0, "forms": ["a"], "documents": []}],
        },
        {
            "forms": [base_form],
            "documents": [],
            "stages": [
                {"key": "s", "name": "S", "forms": ["a"], "documents": []},
                {"key": "s2", "name": "S2", "order": 1, "forms": ["a"], "documents": []},
                {"key": "s3", "name": "S3", "order": 1, "forms": ["a"], "documents": []},
            ],
        },
        {"forms": [base_form], "documents": [], "stages": [{"key": "s", "name": "S", "forms": [], "documents": []}]},
        {
            "forms": [base_form],
            "documents": [],
            "stages": [{"key": "s", "name": "S", "forms": ["a", "a"], "documents": []}],
        },
        {
            "forms": [base_form],
            "documents": [{"key": "d", "title": "D"}],
            "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": ["missing"]}],
        },
        {
            "forms": [base_form],
            "documents": [{"key": "d", "title": "D"}],
            "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": ["d", "d"]}],
        },
        {
            "forms": [base_form],
            "documents": [{"key": "d", "title": "D"}],
            "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": []}],
        },
    ]


def test_spec_validation_covers_error_paths():
    for raw in _bad_specs():
        with pytest.raises(TemplateSpecError):
            normalize_spec(raw)


def test_normalize_spec_optional_fields_and_defaults():
    spec = normalize_spec(
        {
            "forms": [
                {
                    "key": "表单A",
                    "name": "表单A",
                    "description": "说明",
                    "fields": [
                        {
                            "name": "文本",
                            "type": "text",
                            "required": True,
                            "is_unique": True,
                            "hidden": True,
                            "default_value": "x",
                        },
                        {"name": "数值", "type": "number", "config": {"min": 0}},
                    ],
                }
            ],
            "documents": [{"key": "doc", "title": "文档", "required": False, "naming": "", "content": ""}],
            "stages": [
                {
                    "key": "初始",
                    "name": "初始",
                    "description": "起始",
                    "order": 3,
                    "forms": ["表单A"],
                    "documents": ["doc"],
                }
            ],
        }
    )
    assert spec["forms"][0]["fields"][0]["required"] is True
    assert spec["forms"][0]["fields"][1]["required"] is False
    assert spec["documents"][0]["required"] is False
    assert spec["stages"][0]["order"] == 3


def _register_other_user(client) -> dict[str, str]:
    client.post(
        "/api/v1/accounts/auth/register",
        json={"username": "otheruser", "email": "other@example.com", "password": "passw0rd"},
    )
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "otheruser", "password": "passw0rd"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_template_read_update_delete_and_permissions(client, auth_headers):
    template = _create_template(client, auth_headers)

    listed = client.get("/api/v1/workspace-templates", headers=auth_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == template["name"]
    assert client.get("/api/v1/workspace-templates?q=科研", headers=auth_headers).json()
    assert client.get(f"/api/v1/workspace-templates/{template['id']}", headers=auth_headers).status_code == 200
    revisions = client.get(f"/api/v1/workspace-templates/{template['id']}/revisions", headers=auth_headers)
    assert [r["version"] for r in revisions.json()] == [1]

    # 非创建者不可写
    other = _register_other_user(client)
    assert (
        client.put(f"/api/v1/workspace-templates/{template['id']}", json={"name": "偷改"}, headers=other).status_code
        == 403
    )
    assert client.delete(f"/api/v1/workspace-templates/{template['id']}", headers=other).status_code == 403

    # 名称冲突
    assert (
        client.post(
            "/api/v1/workspace-templates",
            json={"name": template["name"], "spec": SPEC},
            headers=auth_headers,
        ).status_code
        == 409
    )

    # 只改元数据：不递增版本、不触发同步
    updated = client.put(
        f"/api/v1/workspace-templates/{template['id']}",
        json={"name": "科研测试模板改名", "description": "新说明", "category": "科研", "modules": ["tables"]},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["template"]["version"] == 1
    assert body["template"]["category"] == "科研"
    assert body["sync"]["created_tables"] == 0

    # 使用中不可删；工作区删除后可删
    ws = _create_workspace(client, auth_headers, template["id"])
    assert client.delete(f"/api/v1/workspace-templates/{template['id']}", headers=auth_headers).status_code == 409
    assert client.delete(f"/api/v1/workspaces/{ws['id']}", headers=auth_headers).status_code == 204
    assert client.delete(f"/api/v1/workspace-templates/{template['id']}", headers=auth_headers).status_code == 204


def test_preview_rejects_invalid_spec_and_missing_template(client, auth_headers):
    assert (
        client.post(
            "/api/v1/workspaces", json={"name": "无模板", "template_id": 9999}, headers=auth_headers
        ).status_code
        == 404
    )
    template = _create_template(client, auth_headers)
    assert (
        client.post(
            f"/api/v1/workspace-templates/{template['id']}/preview",
            json={"spec": {"forms": [], "documents": [], "stages": []}},
            headers=auth_headers,
        ).status_code
        == 422
    )
    assert client.get("/api/v1/workspace-templates/9999", headers=auth_headers).status_code == 404
    assert client.get("/api/v1/workspace-templates/9999/revisions", headers=auth_headers).status_code == 404


def test_apply_template_to_existing_workspace_and_switch(client, auth_headers):
    template = _create_template(client, auth_headers)
    other = _create_template(
        client,
        auth_headers,
        name="科研任务模板",
        spec={
            "forms": [{"key": "x", "name": "任务表", "fields": [{"name": "任务", "type": "text"}]}],
            "documents": [{"key": "xdoc", "title": "任务说明"}],
            "stages": [{"key": "only", "name": "唯一阶段", "forms": ["x"], "documents": ["xdoc"]}],
        },
    )
    # 自由工作区：先无模板生命周期 404
    free = client.post("/api/v1/workspaces", json={"name": "自由工作区"}, headers=auth_headers).json()
    assert client.get(f"/api/v1/workspaces/{free['id']}/lifecycle", headers=auth_headers).status_code == 404

    applied = client.post(
        f"/api/v1/workspaces/{free['id']}/lifecycle/apply",
        json={"template_id": template["id"]},
        headers=auth_headers,
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["template_stage"] == "proposal"

    # 先强制推进到第二阶段，再尝试回退 → 409 backward
    first_advance = client.post(
        f"/api/v1/workspaces/{free['id']}/lifecycle/advance",
        json={"force": True},
        headers=auth_headers,
    )
    assert first_advance.status_code == 200, first_advance.text
    back = client.post(
        f"/api/v1/workspaces/{free['id']}/lifecycle/advance",
        json={"target_stage": "proposal", "force": True},
        headers=auth_headers,
    )
    assert back.status_code == 409
    assert back.json()["detail"]["reason"] == "backward"

    switched_blocked = client.post(
        f"/api/v1/workspaces/{free['id']}/lifecycle/apply",
        json={"template_id": other["id"]},
        headers=auth_headers,
    )
    assert switched_blocked.status_code == 409
    switched = client.post(
        f"/api/v1/workspaces/{free['id']}/lifecycle/apply",
        json={"template_id": other["id"], "force": True},
        headers=auth_headers,
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["template_stage"] == "only"

    # 未知 / 回退 / 最后阶段推进
    unknown = client.post(
        f"/api/v1/workspaces/{free['id']}/lifecycle/advance",
        json={"target_stage": "nope", "force": True},
        headers=auth_headers,
    )
    assert unknown.status_code == 409
    backward = client.post(
        f"/api/v1/workspaces/{free['id']}/lifecycle/advance",
        json={"target_stage": "proposal", "force": True},
        headers=auth_headers,
    )
    assert backward.status_code == 409
    last = client.post(
        f"/api/v1/workspaces/{free['id']}/lifecycle/advance",
        json={},
        headers=auth_headers,
    )
    assert last.status_code == 409
    assert last.json()["detail"]["reason"] == "last_stage"


def test_diff_covers_field_and_stage_changes(client, auth_headers):
    template = _create_template(client, auth_headers)
    _create_workspace(client, auth_headers, template["id"])
    changed = {
        "forms": [
            {
                "key": "apply",
                "name": "申报表（新）",
                "fields": [
                    {"name": "项目名称", "type": "text", "required": False, "config": {"placeholder": "x"}},
                    {"name": "备注", "type": "text"},
                ],
            },
            {
                "key": "extra",
                "name": "新增表",
                "fields": [{"name": "字段", "type": "text"}],
            },
        ],
        "documents": [
            {"key": "proposal", "title": "立项申请书（改）", "naming": "{name}-申请书"},
            {"key": "newdoc", "title": "新文档"},
        ],
        "stages": [
            {"key": "proposal", "name": "立项（改）", "order": 1, "forms": ["apply"], "documents": ["proposal"]},
            {"key": "new_stage", "name": "新阶段", "order": 2, "forms": ["extra"], "documents": ["newdoc"]},
        ],
    }
    preview = client.post(
        f"/api/v1/workspace-templates/{template['id']}/preview",
        json={"spec": changed},
        headers=auth_headers,
    )
    assert preview.status_code == 200, preview.text
    kinds = {c["kind"] for c in preview.json()["diff"]["changes"]}
    assert "form_modified" in kinds
    assert "field_removed" in kinds
    assert "field_required_changed" in kinds
    assert "field_config_changed" in kinds
    assert "document_modified" in kinds
    assert "stage_modified" in kinds
    assert "stage_added" in kinds
    assert "stage_refs_changed" in kinds
    summary = preview.json()["impact"]["summary"]
    assert summary["tables_to_create"] == 1
    assert summary["documents_to_create"] == 1
    assert summary["fields_to_add"] == 1
    assert summary["orphan_documents"] == 1
    assert summary["orphan_forms"] == 1


def test_spec_validation_more_branches():
    base = {"key": "a", "name": "A", "fields": [{"name": "x", "type": "text"}]}
    stage = {"key": "s", "name": "S", "forms": ["a"], "documents": []}
    with pytest.raises(TemplateSpecError):
        normalize_spec([])
    more = [
        {"forms": ["bad"], "documents": [], "stages": [stage]},
        {"forms": [{"key": "a", "name": "A", "fields": ["bad"]}], "documents": [], "stages": [stage]},
        {"forms": [{**base, "fields": [{"name": "", "type": "text"}]}], "documents": [], "stages": [stage]},
        {"forms": [{**base, "fields": [{"name": "x" * 256, "type": "text"}]}], "documents": [], "stages": [stage]},
        {
            "forms": [{**base, "fields": [{"name": "x", "type": "text", "config": []}]}],
            "documents": [],
            "stages": [stage],
        },
        {"forms": [base, {**base, "key": "a", "name": "B"}], "documents": [], "stages": [stage]},
        {"forms": [base, {**base, "key": "b", "name": "A"}], "documents": [], "stages": [stage]},
        {
            "forms": [base],
            "documents": [{"key": "d", "title": "D"}, {"key": "d", "title": "E"}],
            "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": ["d"]}],
        },
        {
            "forms": [base],
            "documents": [],
            "stages": [
                {"key": "s", "name": "S", "forms": ["a"], "documents": []},
                {"key": "s", "name": "S2", "order": 2, "forms": ["a"], "documents": []},
            ],
        },
        {"forms": [base], "documents": [], "stages": [{"key": "s", "name": "S", "forms": "a", "documents": []}]},
        {"forms": [base], "documents": [], "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": "d"}]},
        {
            "forms": [base],
            "documents": [],
            "stages": [{"key": "s", "name": "S", "forms": ["a"], "documents": [], "x": 1}],
        },
    ]
    for raw in more:
        with pytest.raises(TemplateSpecError):
            normalize_spec(raw)


def test_sync_recreates_deleted_document_and_adds_unique_lookup_fields(client, auth_headers, db):
    """覆盖：文档被删后重建、lookup 字段跳过 DDL、link target_form 解析、唯一索引、表被回收后重建."""
    spec = {
        "forms": [
            {
                "key": "base",
                "name": "主表",
                "fields": [
                    {"name": "名称", "type": "text", "required": True},
                    {"name": "编号", "type": "text", "is_unique": True},
                ],
            },
            {
                "key": "sub",
                "name": "子表",
                "fields": [
                    {"name": "主表引用", "type": "link", "config": {"target_form": "base"}},
                    {"name": "引用值", "type": "lookup", "config": {"target_form": "base"}},
                ],
            },
        ],
        "documents": [{"key": "doc", "title": "说明文档", "content": "# 说明\n"}],
        "stages": [
            {"key": "s1", "name": "阶段一", "order": 1, "forms": ["base", "sub"], "documents": ["doc"]},
        ],
    }
    template = _create_template(client, auth_headers, spec=spec, name="结构覆盖模板")
    ws = _create_workspace(client, auth_headers, template["id"])

    from cndb.plugins.documents.models import Document
    from cndb.plugins.tables.models import DataTable

    # link / lookup 的 target_form 已解析
    sub = db.query(DataTable).filter(DataTable.workspace_id == ws["id"], DataTable.name == "子表").one()
    link_field = next(f for f in sub.active_fields() if f.name == "主表引用")
    assert link_field.config.get("target_table_id")
    lookup_field = next(f for f in sub.active_fields() if f.name == "引用值")
    assert lookup_field.field_type == "lookup"

    # 文档被用户删除后再次同步 → 重建占位（复用阶段文件夹）
    doc = db.query(Document).filter(Document.workspace_id == ws["id"], Document.title == "说明文档").one()
    assert client.delete(f"/api/v1/workspaces/{ws['id']}/documents/{doc.id}", headers=auth_headers).status_code in (
        200,
        204,
    )
    resynced = client.post(
        f"/api/v1/workspaces/{ws['id']}/lifecycle/apply",
        json={"template_id": template["id"]},
        headers=auth_headers,
    )
    assert resynced.status_code == 200, resynced.text
    assert resynced.json()["sync"]["created_documents"] == 1

    # 表被回收（trashed）后再次同步 → 重建表
    base = db.query(DataTable).filter(DataTable.workspace_id == ws["id"], DataTable.name == "主表").one()
    base.trashed = True
    base.trashed_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
    db.commit()
    rebuilt = client.post(
        f"/api/v1/workspaces/{ws['id']}/lifecycle/apply",
        json={"template_id": template["id"]},
        headers=auth_headers,
    )
    assert rebuilt.json()["sync"]["created_tables"] == 1


def test_add_unique_field_to_non_empty_table(client, auth_headers, db):
    template = _create_template(client, auth_headers)
    ws = _create_workspace(client, auth_headers, template["id"])
    from cndb.plugins.tables.models import DataTable

    table = db.query(DataTable).filter(DataTable.workspace_id == ws["id"], DataTable.name == "申报表").one()
    assert (
        client.post(
            f"/api/v1/workspaces/{ws['id']}/tables/{table.id}/records",
            json={"values": {"项目名称": "项目一"}},
            headers=auth_headers,
        ).status_code
        == 201
    )

    new_spec = {
        "forms": [
            {
                "key": "apply",
                "name": "申报表",
                "fields": [
                    {"name": "项目名称", "type": "text", "required": True},
                    {"name": "负责人", "type": "text"},
                    {"name": "唯一编号", "type": "text", "is_unique": True},
                    {"name": "引用字段", "type": "lookup", "config": {"target_form": "apply"}},
                ],
            },
            SPEC["forms"][1],
        ],
        "documents": SPEC["documents"],
        "stages": SPEC["stages"],
    }
    updated = client.put(
        f"/api/v1/workspace-templates/{template['id']}",
        json={"spec": new_spec, "change_summary": "加唯一字段"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["sync"]["added_fields"] == 2
    # 唯一索引已建
    from sqlalchemy import inspect as sa_inspect

    unique_fields = {f.name: f for f in table.active_fields()}
    indexes = sa_inspect(db.get_bind()).get_indexes(table.db_table_name)
    unique_cols = {col for idx in indexes if idx.get("unique") for col in idx.get("column_names") or []}
    assert unique_fields["唯一编号"].db_column_name in unique_cols


# ── 数据流程（需求 0095）────────────────────────────


def test_flow_defaults_and_validation():
    spec = normalize_spec(SPEC)
    flow = spec["forms"][0]["flow"]
    assert flow["enabled"] is True
    assert flow["list_fields"] == ["项目名称", "负责人"]
    assert flow["allow_create"] is True

    raw = {
        **SPEC,
        "forms": [
            {
                **SPEC["forms"][0],
                "flow": {
                    "list_fields": ["项目名称"],
                    "search_fields": ["负责人"],
                    "form_groups": [{"title": "主信息", "fields": ["项目名称"]}],
                    "hints": {"负责人": "填写项目负责人"},
                    "default_values": {"负责人": "待定"},
                    "allow_delete": False,
                    "default_sort": {"field": "项目名称", "order": "asc"},
                    "empty_text": "还没有项目",
                },
            },
            SPEC["forms"][1],
        ],
    }
    normalized = normalize_spec(raw)
    flow = normalized["forms"][0]["flow"]
    assert flow["allow_delete"] is False
    assert flow["default_sort"] == {"field": "项目名称", "order": "asc"}
    # 未纳入分组的字段自动补进「其他信息」，不丢字段
    assert flow["form_groups"][-1] == {"title": "其他信息", "fields": ["负责人"]}

    # 空列表按默认派生（不报错）
    fallback = normalize_spec(
        {
            **SPEC,
            "forms": [
                {**SPEC["forms"][0], "flow": {"list_fields": [], "form_groups": []}},
                SPEC["forms"][1],
            ],
        }
    )
    assert fallback["forms"][0]["flow"]["list_fields"] == ["项目名称", "负责人"]
    assert fallback["forms"][0]["flow"]["form_groups"][0]["title"] == "基本信息"

    bad_flows = [
        {"list_fields": ["不存在"]},
        {"search_fields": ["不存在"]},
        {"form_groups": [{"title": "G", "fields": ["不存在"]}]},
        {"form_groups": [{"title": "G", "fields": ["项目名称"]}, {"title": "G2", "fields": ["项目名称"]}]},
        {"hints": {"不存在": "x"}},
        {"default_values": {"不存在": 1}},
        {"default_sort": {"field": "不存在"}},
        {"default_sort": {"field": "项目名称", "order": "up"}},
        {"unknown": True},
        {"list_fields": [1]},
        {"form_groups": [{"title": "G", "fields": []}]},
        {"hints": []},
        {"default_values": []},
    ]
    for bad in bad_flows:
        with pytest.raises(TemplateSpecError):
            normalize_spec(
                {
                    **SPEC,
                    "forms": [{**SPEC["forms"][0], "flow": bad}, SPEC["forms"][1]],
                }
            )


def test_data_flow_endpoint_returns_stages_forms_and_permissions(client, auth_headers):
    template = _create_template(client, auth_headers)
    ws = _create_workspace(client, auth_headers, template["id"])

    # 无模板工作区 404
    free = client.post("/api/v1/workspaces", json={"name": "自由流程区"}, headers=auth_headers).json()
    assert client.get(f"/api/v1/workspaces/{free['id']}/data-flow", headers=auth_headers).status_code == 404

    resp = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["template_id"] == template["id"]
    assert data["current_stage"] == "proposal"
    assert [s["key"] for s in data["stages"]] == ["proposal", "execution"]
    # 旧模板没有显式 flows：按阶段派生，保证前端多流程视图
    assert [f["key"] for f in data["flows"]] == ["stage-proposal", "stage-execution"]
    assert data["flows"][0]["steps"][0]["form"]["key"] == "apply"
    proposal = data["stages"][0]
    assert proposal["is_current"] is True
    form = proposal["forms"][0]
    assert form["key"] == "apply"
    assert form["table_id"]
    assert form["can_create"] is True
    assert form["flow"]["list_fields"] == ["项目名称", "负责人"]
    assert [f["name"] for f in form["fields"]] == ["项目名称", "负责人"]
    assert form["record_count"] == 0

    rec = client.post(
        f"/api/v1/workspaces/{ws['id']}/tables/{form['table_id']}/records",
        json={"values": {"项目名称": "流程项目"}},
        headers=auth_headers,
    )
    assert rec.status_code == 201, rec.text
    data = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers).json()
    assert data["stages"][0]["forms"][0]["record_count"] == 1


def test_data_flow_handles_missing_template_and_broken_mapping(client, auth_headers, db):
    from cndb.plugins.workspaces.models import Workspace

    template = _create_template(client, auth_headers)
    ws = _create_workspace(client, auth_headers, template["id"])
    # 引用一个不存在的模板 id（模拟模板被外部删除）
    row = db.get(Workspace, ws["id"])
    row.template_id = 999999
    db.commit()
    assert client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers).status_code == 404

    # 恢复有效模板，但映射里放入非整数 / 已失效表 id → 该表单被安全跳过
    row.template_id = template["id"]
    row.template_state = {"form_tables": {"apply": "bad", "progress": 999999}, "documents": {}, "history": []}
    db.commit()
    resp = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert all(stage["forms"] == [] for stage in resp.json()["stages"])


def test_seed_research_template_has_flow_and_example_workspace(db):
    from cndb.cli.seed.workspace_templates import (
        EXAMPLE_WORKSPACE_NAME,
        _seed_workspace_templates,
    )
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.workspaces.models import Workspace

    owner = User(username="seedowner", email="seed@example.com", nickname="seed")
    owner.set_password("passw0rd")
    db.add(owner)
    db.commit()
    db.refresh(owner)
    created = _seed_workspace_templates(db, owner=owner)
    assert created >= 2

    ws = db.query(Workspace).filter(Workspace.name == EXAMPLE_WORKSPACE_NAME).one()
    assert ws.template_id
    assert ws.template_stage == "proposal"
    applications = db.query(DataTable).filter(DataTable.workspace_id == ws.id, DataTable.name == "项目申报").one()
    from sqlalchemy import text

    count = db.execute(text(f'SELECT COUNT(*) FROM "{applications.db_table_name}"')).scalar()
    assert count == 46
    # 多流程专用表单（未出现在 stages）同样实例化并写入示例数据
    from cndb.plugins.workspaces.models import WorkspaceTemplate

    template = db.query(WorkspaceTemplate).filter(WorkspaceTemplate.name == "科研项目全生命周期管理").one()
    data = normalize_spec(template.spec)
    assert {f["key"] for f in data["flows"]} == {
        "project_lifecycle",
        "expense_reimbursement",
        "achievement_registration",
        "project_change",
        "owner_management",
        "tech_system_management",
        "task_breakdown_management",
        "todo_followup",
        "resource_schedule_management",
        "funding_management",
    }
    for form_key, expected in (
        ("project_progress", 358),
        ("expense_claim", 6),
        ("achievement_registry", 6),
        ("project_change", 5),
        ("project_owner", 89),
        ("tech_system", 43),
        ("project_task", 31),
        ("project_todo", 16),
        ("resource_schedule", 26),
        ("funding_budget", 220),
    ):
        table = (
            db.query(DataTable)
            .filter(
                DataTable.workspace_id == ws.id,
                DataTable.name == next(f["name"] for f in data["forms"] if f["key"] == form_key),
            )
            .one()
        )
        rows = db.execute(text(f'SELECT COUNT(*) FROM "{table.db_table_name}"')).scalar()
        assert rows == expected, (form_key, rows)
    # 项目级文档（ADR 0122）：第一个项目生成五份阶段文档，并写入示例正文
    from cndb.plugins.documents.models import Document, DocumentVersion
    from cndb.plugins.workspaces.models import WorkspaceProjectDocument

    project_row_id = db.execute(text(f'SELECT id FROM "{applications.db_table_name}" ORDER BY id LIMIT 1')).scalar()
    mappings = (
        db.query(WorkspaceProjectDocument)
        .filter(
            WorkspaceProjectDocument.workspace_id == ws.id,
            WorkspaceProjectDocument.project_row_id == project_row_id,
        )
        .all()
    )
    documents = {m.doc_key: m.document_id for m in mappings}
    assert set(documents) == {"proposal_doc", "midterm_doc", "budget_doc", "closure_doc", "archive_doc"}
    assert ws.project_mode == "project"
    closure_doc = db.get(Document, documents["closure_doc"])
    assert closure_doc is not None
    latest = (
        db.query(DocumentVersion)
        .filter(DocumentVersion.document_id == closure_doc.id)
        .order_by(DocumentVersion.version_number.desc())
        .first()
    )
    assert latest is not None and "结题报告" in latest.content
    # 技术体系「技术脉络」树视图随示例一并合并进模板示例工作区
    from cndb.plugins.tables.models import DataView

    tech_table = (
        db.query(DataTable)
        .filter(
            DataTable.workspace_id == ws.id,
            DataTable.name == next(f["name"] for f in data["forms"] if f["key"] == "tech_system"),
        )
        .one()
    )
    tree_view = db.query(DataView).filter(DataView.table_id == tech_table.id, DataView.name == "技术脉络").one()
    assert tree_view.view_type == "tree"
    assert tree_view.view_options.get("parent_field") == "父技术编号"
    # 再执行一次幂等跳过
    assert _seed_workspace_templates(db, owner=owner) == 0


def test_explicit_multi_flows_validation_and_crud(client, auth_headers, db):
    spec = {
        "forms": [
            {"key": "apply", "name": "申请单", "fields": [{"name": "事项", "type": "text", "required": True}]},
            {"key": "archive", "name": "归档单", "fields": [{"name": "归档号", "type": "text"}]},
        ],
        "documents": [],
        "stages": [{"key": "only", "name": "主阶段", "forms": ["apply"], "documents": []}],
        "flows": [
            {
                "key": "main",
                "name": "主业务流程",
                "description": "申请 → 审批",
                "stage": "only",
                "steps": [
                    {"key": "apply", "name": "提交申请", "form": "apply"},
                    {"key": "approve", "name": "人工审批", "description": "审批节点无表单"},
                ],
            },
            {
                "key": "archive",
                "name": "归档流程",
                "description": "归档登记",
                "stage": "only",
                "steps": [{"key": "archive", "name": "登记归档", "form": "archive"}],
            },
        ],
    }
    template = _create_template(client, auth_headers, spec=spec, name="多流程模板")
    ws = _create_workspace(client, auth_headers, template["id"])
    data = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers).json()
    assert [f["key"] for f in data["flows"]] == ["main", "archive"]
    main = data["flows"][0]
    assert main["stage"] == "only" and main["stage_name"] == "主阶段"
    assert data["flows"][1]["stage_name"] == "主阶段"
    assert main["step_count"] == 2 and main["form_count"] == 1
    assert main["steps"][1]["form"] is None
    assert main["steps"][1]["description"] == "审批节点无表单"
    archive_form = data["flows"][1]["steps"][0]["form"]
    assert archive_form["key"] == "archive"
    assert archive_form["table_id"]

    # 流程专用表单（未出现在 stages）同样已建表，可 CRUD
    rec = client.post(
        f"/api/v1/workspaces/{ws['id']}/tables/{archive_form['table_id']}/records",
        json={"values": {"归档号": "A-001"}},
        headers=auth_headers,
    )
    assert rec.status_code == 201, rec.text
    data = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers).json()
    assert data["flows"][1]["record_count"] == 1
    assert data["flows"][1]["steps"][0]["form"]["record_count"] == 1

    bad = {**spec, "flows": [{"key": "bad", "name": "坏流程", "steps": [{"key": "x", "name": "X", "form": "missing"}]}]}
    with pytest.raises(TemplateSpecError):
        normalize_spec(bad)
    bad_stage = {
        **spec,
        "flows": [{"key": "bad", "name": "坏阶段", "stage": "missing", "steps": [{"key": "x", "name": "X"}]}],
    }
    with pytest.raises(TemplateSpecError):
        normalize_spec(bad_stage)


def test_data_flow_infers_flow_stage_from_step_form(client, auth_headers):
    spec = {
        "forms": [
            {"key": "apply", "name": "申请单", "fields": [{"name": "事项", "type": "text"}]},
            {"key": "archive", "name": "归档单", "fields": [{"name": "归档号", "type": "text"}]},
        ],
        "documents": [],
        "stages": [{"key": "only", "name": "唯一阶段", "forms": ["apply"], "documents": []}],
        "flows": [
            {"key": "main", "name": "主流程", "steps": [{"key": "a", "name": "申请", "form": "apply"}]},
            {"key": "archive", "name": "归档流程", "steps": [{"key": "b", "name": "归档", "form": "archive"}]},
        ],
    }
    template = _create_template(client, auth_headers, spec=spec, name="阶段推断模板")
    ws = _create_workspace(client, auth_headers, template["id"])
    data = client.get(f"/api/v1/workspaces/{ws['id']}/data-flow", headers=auth_headers).json()
    assert data["flows"][0]["stage"] == "only"
    assert data["flows"][0]["stage_name"] == "唯一阶段"
    # flow-only 表单不在任何阶段 → 不强行归属阶段
    assert data["flows"][1]["stage"] is None
    assert data["flows"][1]["stage_name"] is None


# ── 模板导入导出（需求 0120）────────────────────────


def test_export_template_returns_json_file(client, auth_headers):
    template = _create_template(client, auth_headers, name="导出模板")

    resp = client.get(f"/api/v1/workspace-templates/{template['id']}/export", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    disposition = resp.headers["content-disposition"]
    assert "attachment" in disposition
    assert "filename*=UTF-8''" in disposition
    assert ".workspace-template.json" in disposition

    body = resp.json()
    assert body["format"] == "cndb.workspace-template"
    assert body["schema_version"] == 1
    assert body["name"] == "导出模板"
    assert body["category"] == ""
    assert body["version"] == 1
    assert body["modules"]
    assert [form["key"] for form in body["spec"]["forms"]] == ["apply", "progress"]

    # 未登录 401；不存在 404
    assert client.get(f"/api/v1/workspace-templates/{template['id']}/export").status_code == 401
    assert client.get("/api/v1/workspace-templates/9999/export", headers=auth_headers).status_code == 404


def test_import_preview_and_create_with_auto_rename(client, auth_headers):
    template = _create_template(client, auth_headers, name="导入模板")
    exported = client.get(f"/api/v1/workspace-templates/{template['id']}/export", headers=auth_headers).json()

    # 任意登录用户都能预览 / 导入；同名自动重命名
    other = _register_other_user(client)
    preview = client.post("/api/v1/workspace-templates/import/preview", json=exported, headers=other)
    assert preview.status_code == 200, preview.text
    data = preview.json()
    assert data["renamed"] is True
    assert data["name"] == "导入模板（导入）"
    assert data["source_version"] == 1
    assert data["counts"]["stage_count"] == 2
    assert data["counts"]["form_count"] == 2
    assert data["counts"]["document_rule_count"] == 2
    # 预览不落库
    assert all(t["name"] != "导入模板（导入）" for t in client.get("/api/v1/workspace-templates", headers=other).json())

    created = client.post("/api/v1/workspace-templates/import", json=exported, headers=other)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "导入模板（导入）"
    assert body["is_builtin"] is False
    assert body["version"] == 1
    assert body["counts"]["stage_count"] == 2
    revisions = client.get(f"/api/v1/workspace-templates/{body['id']}/revisions", headers=other).json()
    assert [(r["version"], r["change_summary"]) for r in revisions] == [(1, "从文件导入")]

    # 再次导入：名称继续递增
    again = client.post("/api/v1/workspace-templates/import", json=exported, headers=other)
    assert again.status_code == 201, again.text
    assert again.json()["name"] == "导入模板（导入 2）"

    # 第三方导出文件里的大版本号不沿用：导入模板版本恒为 1
    assert exported["version"] == 1


def test_import_rejects_invalid_files(client, auth_headers):
    spec_bad = {"forms": [], "documents": [], "stages": []}
    base = {
        "format": "cndb.workspace-template",
        "schema_version": 1,
        "name": "坏模板",
        "spec": spec_bad,
    }
    assert client.post("/api/v1/workspace-templates/import/preview", json=base, headers=auth_headers).status_code == 422

    wrong_format = {**base, "format": "other"}
    assert (
        client.post("/api/v1/workspace-templates/import/preview", json=wrong_format, headers=auth_headers).status_code
        == 422
    )

    wrong_version = {**base, "schema_version": 2}
    assert (
        client.post("/api/v1/workspace-templates/import/preview", json=wrong_version, headers=auth_headers).status_code
        == 422
    )

    bad_modules = {**base, "spec": SPEC, "modules": ["nope"]}
    assert client.post("/api/v1/workspace-templates/import", json=bad_modules, headers=auth_headers).status_code == 422

    # 未登录不可导入
    valid = {**base, "spec": SPEC}
    assert client.post("/api/v1/workspace-templates/import", json=valid).status_code == 401


def test_validate_spec_is_stateless(client, auth_headers):
    """结构化编辑器预检：只归一化与统计，不落库（需求 0121）."""
    before = client.get("/api/v1/workspace-templates", headers=auth_headers).json()
    r = client.post("/api/v1/workspace-templates/validate", json={"spec": SPEC}, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["spec"]["forms"][0]["fields"][0]["name"] == "项目名称"
    assert body["counts"] == {
        "stage_count": 2,
        "form_count": 2,
        "field_count": 4,
        "document_rule_count": 2,
        "flow_count": 0,
        "step_count": 0,
    }
    after = client.get("/api/v1/workspace-templates", headers=auth_headers).json()
    assert [t["id"] for t in after] == [t["id"] for t in before]

    # 非法规格返回可定位的 422：path + message
    bad = client.post(
        "/api/v1/workspace-templates/validate",
        json={"spec": {"forms": [], "documents": [], "stages": []}},
        headers=auth_headers,
    )
    assert bad.status_code == 422
    detail = bad.json()["detail"]
    assert detail == {"path": "spec", "message": "至少定义一个表单或文档规则"}

    assert client.post("/api/v1/workspace-templates/validate", json={"spec": SPEC}).status_code == 401
