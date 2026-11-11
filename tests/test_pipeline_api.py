"""流水线 REST API 测试：CRUD / 校验 / 触发 / 运行与发现物 / 权限（ADR 0076 D2 / D6 / D10）."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from cndb.plugins.pipeline.models import (
    CHANGE_TYPE_MANUAL,
    CHANGE_TYPE_ROLLBACK,
    PipelineFinding,
    PipelineRun,
    PipelineWorkflowVersion,
)
from cndb.plugins.pipeline.services.dsl.parse import compile_workflow
from cndb.plugins.workspaces.models import WorkspaceRole
from tests.pipeline_helpers import (
    add_member,
    add_rows,
    login,
    make_document,
    make_table,
    make_user,
    make_workspace,
)

BASE = "/api/v1/workspaces/{ws}/pipelines"

CLEAN_CONTENT = """
name: 文档巡检
jobs:
  文档:
    steps:
      - uses: document/links
"""

FINDING_CONTENT = """
name: 空值巡检
jobs:
  表:
    steps:
      - uses: table/null-rate
        with:
          table: 人员
          fields: [姓名, 城市]
"""

MIXED_CONTENT = """
name: 综合巡检
jobs:
  文档:
    steps:
      - uses: document/links
  表:
    steps:
      - uses: table/null-rate
        with:
          table: 人员
          fields: [姓名]
"""


@pytest.fixture
def owner(db):
    return make_user(db, "pipeline_api_owner")


@pytest.fixture
def ws(db, owner):
    return make_workspace(db, owner, "PipelineApiWS")


@pytest.fixture
def auth_owner(client, owner):
    return login(client, owner)


@pytest.fixture
def auth_viewer(client, db, ws):
    user = make_user(db, "pipeline_api_viewer")
    add_member(db, ws, user, WorkspaceRole.VIEWER)
    return login(client, user)


@pytest.fixture
def auth_outsider(client, db):
    return login(client, make_user(db, "pipeline_api_outsider"))


@pytest.fixture
def people(db, ws):
    return make_table(db, ws, "人员", [("姓名", "text"), ("城市", "text")])


def _create(client, ws, headers, content: str = CLEAN_CONTENT, name: str | None = None):
    payload: dict = {"content": content}
    if name is not None:
        payload["name"] = name
    return client.post(BASE.format(ws=ws.id), json=payload, headers=headers)


def _trigger(client, ws, headers, workflow_id: int):
    return client.post(f"{BASE.format(ws=ws.id)}/{workflow_id}/run", headers=headers)


def _versions_url(ws, workflow_id: int) -> str:
    return f"{BASE.format(ws=ws.id)}/{workflow_id}/versions"


def _expire(db):
    db.expire_all()


def _add_run(db, ws, workflow_id: int, status: str = "success") -> PipelineRun:
    """直接落一条运行记录，避开后台线程，便于构造活跃 / 历史状态."""
    run = PipelineRun(
        workflow_id=workflow_id,
        workspace_id=ws.id,
        trigger="manual",
        trigger_payload={},
        status=status,
        stats={},
        error_message="",
    )
    db.add(run)
    db.commit()
    return run


def _add_finding(db, run_id: int) -> PipelineFinding:
    finding = PipelineFinding(
        run_id=run_id,
        check="document/links",
        severity="warn",
        target_type="document",
        target_id=1,
        locator={},
        message="链接失效",
        detail={},
    )
    db.add(finding)
    db.commit()
    return finding


class TestCatalog:
    def test_checks_catalog(self, client, ws, auth_viewer):
        resp = client.get(f"{BASE.format(ws=ws.id)}/checks", headers=auth_viewer)
        assert resp.status_code == 200
        uses = {item["uses"] for item in resp.json()}
        assert {"table/null-rate", "table/duplicates", "table/value-range", "table/stale"} <= uses
        assert {"document/broken-refs", "document/chart-blocks", "document/links"} <= uses
        null_rate = next(item for item in resp.json() if item["uses"] == "table/null-rate")
        assert any(input_item["name"] == "max_rate" for input_item in null_rate["inputs"])

    def test_checks_catalog_filters_by_domain(self, client, ws, auth_viewer):
        """数据表 / 文档质量检查页各自只取本域动作（domain 查询参数）."""
        for domain in ("table", "document"):
            resp = client.get(f"{BASE.format(ws=ws.id)}/checks", params={"domain": domain}, headers=auth_viewer)
            assert resp.status_code == 200
            uses = [item["uses"] for item in resp.json()]
            assert uses and all(u.startswith(f"{domain}/") for u in uses)

    def test_checks_catalog_rejects_unknown_domain(self, client, ws, auth_viewer):
        resp = client.get(f"{BASE.format(ws=ws.id)}/checks", params={"domain": "bogus"}, headers=auth_viewer)
        assert resp.status_code == 400
        assert resp.json()["code"] == "bad_request"

    def test_checks_route_not_shadowed(self, client, ws, auth_owner):
        """``/checks`` 声明在动态 ``/{workflow_id}`` 之前."""
        resp = client.get(f"{BASE.format(ws=ws.id)}/checks", headers=auth_owner)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_validate_ok(self, client, ws, auth_owner):
        resp = client.post(
            f"{BASE.format(ws=ws.id)}/validate",
            json={"content": CLEAN_CONTENT},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["job_count"] == 1
        assert body["step_count"] == 1

    def test_validate_invalid(self, client, ws, auth_owner):
        resp = client.post(
            f"{BASE.format(ws=ws.id)}/validate",
            json={"content": "name: 坏\njobs: {}\n"},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is False
        assert "jobs" in body["error"]


class TestCrud:
    def test_create_and_get(self, client, ws, auth_owner, db):
        resp = _create(client, ws, auth_owner)
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "文档巡检"
        assert body["compiled"]["jobs"][0]["id"] == "文档"
        assert body["last_run"] is None

        detail = client.get(f"{BASE.format(ws=ws.id)}/{body['id']}", headers=auth_owner)
        assert detail.status_code == 200
        assert detail.json()["content"] == CLEAN_CONTENT

    def test_create_name_fallback_and_precedence(self, client, ws, auth_owner):
        content = "jobs:\n  a:\n    steps:\n      - uses: document/links\n"
        resp = _create(client, ws, auth_owner, content=content, name="记录名")
        assert resp.status_code == 201
        assert resp.json()["name"] == "记录名"

        ir = compile_workflow(CLEAN_CONTENT)
        resp = _create(client, ws, auth_owner, name="记录名2")
        assert resp.status_code == 201
        assert resp.json()["name"] == ir.name

    def test_create_missing_name(self, client, ws, auth_owner):
        resp = _create(client, ws, auth_owner, content="jobs:\n  a:\n    steps:\n      - uses: document/links\n")
        assert resp.status_code == 400
        assert resp.json()["code"] == "pipeline_dsl_invalid"

    def test_create_unknown_check_action(self, client, ws, auth_owner):
        resp = _create(client, ws, auth_owner, content="name: 坏\njobs:\n  a:\n    steps:\n      - uses: nope\n")
        assert resp.status_code == 400
        assert resp.json()["code"] == "pipeline_check_error"

    def test_create_invalid_dsl(self, client, ws, auth_owner):
        resp = _create(client, ws, auth_owner, content="name: 坏\njobs: {}\n")
        assert resp.status_code == 400
        assert resp.json()["code"] == "pipeline_dsl_invalid"

    def test_duplicate_name_conflict(self, client, ws, auth_owner):
        assert _create(client, ws, auth_owner).status_code == 201
        resp = _create(client, ws, auth_owner)
        assert resp.status_code == 409
        assert resp.json()["code"] == "pipeline_conflict"

    def test_list_ordered_and_last_run(self, client, ws, auth_owner, db):
        first = _create(client, ws, auth_owner).json()
        second = _create(client, ws, auth_owner, content=CLEAN_CONTENT.replace("文档巡检", "文档巡检二")).json()
        resp = client.get(BASE.format(ws=ws.id), headers=auth_owner)
        assert resp.status_code == 200
        ids = [item["id"] for item in resp.json()]
        assert set(ids) == {first["id"], second["id"]}

        assert _trigger(client, ws, auth_owner, second["id"]).status_code == 202
        _expire(db)
        detail = client.get(f"{BASE.format(ws=ws.id)}/{second['id']}", headers=auth_owner)
        assert detail.json()["last_run"]["id"] >= 1

    def test_list_filters_by_domain(self, client, ws, auth_owner):
        """规则清单按域过滤：数据表页不含文档规则，反之亦然."""
        doc_flow = _create(client, ws, auth_owner).json()
        table_flow = _create(client, ws, auth_owner, content=FINDING_CONTENT).json()

        doc_ids = [
            item["id"]
            for item in client.get(BASE.format(ws=ws.id), params={"domain": "document"}, headers=auth_owner).json()
        ]
        table_ids = [
            item["id"]
            for item in client.get(BASE.format(ws=ws.id), params={"domain": "table"}, headers=auth_owner).json()
        ]

        assert doc_ids == [doc_flow["id"]]
        assert table_ids == [table_flow["id"]]

    def test_list_mixed_workflow_visible_in_both_domains(self, client, ws, auth_owner):
        """跨域编排的流水线同时属于两个域（两边都可见，不丢规则）."""
        mixed = _create(client, ws, auth_owner, content=MIXED_CONTENT).json()

        for domain in ("table", "document"):
            ids = [
                item["id"]
                for item in client.get(BASE.format(ws=ws.id), params={"domain": domain}, headers=auth_owner).json()
            ]
            assert ids == [mixed["id"]]

    def test_list_rejects_unknown_domain(self, client, ws, auth_owner):
        resp = client.get(BASE.format(ws=ws.id), params={"domain": "bogus"}, headers=auth_owner)
        assert resp.status_code == 400

    def test_list_domain_disabled_module_is_empty(self, client, ws, auth_owner):
        """模块未启用时该域视图为空（历史规则仍可由无 domain 的集中列表管理）."""
        _create(client, ws, auth_owner)  # 文档巡检
        assert (
            client.patch(f"/api/v1/workspaces/{ws.id}", json={"modules": ["tables"]}, headers=auth_owner).status_code
            == 200
        )

        assert client.get(BASE.format(ws=ws.id), headers=auth_owner).json() != []
        assert client.get(BASE.format(ws=ws.id), params={"domain": "document"}, headers=auth_owner).json() == []

    def test_update_content_and_enabled(self, client, ws, auth_owner):
        workflow = _create(client, ws, auth_owner).json()
        new_content = CLEAN_CONTENT.replace("文档巡检", "文档巡检改")
        resp = client.put(
            f"{BASE.format(ws=ws.id)}/{workflow['id']}",
            json={"content": new_content, "enabled": False},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["name"] == "文档巡检改"
        assert body["enabled"] is False
        assert body["compiled"]["name"] == "文档巡检改"

    def test_update_name_only(self, client, ws, auth_owner):
        workflow = _create(client, ws, auth_owner).json()
        resp = client.put(
            f"{BASE.format(ws=ws.id)}/{workflow['id']}",
            json={"name": "改名"},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "改名"

    def test_update_invalid_content(self, client, ws, auth_owner):
        workflow = _create(client, ws, auth_owner).json()
        resp = client.put(
            f"{BASE.format(ws=ws.id)}/{workflow['id']}",
            json={"content": "name: 坏\njobs: []\n"},
            headers=auth_owner,
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "pipeline_dsl_invalid"

    def test_update_name_conflict(self, client, ws, auth_owner):
        first = _create(client, ws, auth_owner).json()
        second = _create(client, ws, auth_owner, content=CLEAN_CONTENT.replace("文档巡检", "文档巡检二")).json()
        resp = client.put(f"{BASE.format(ws=ws.id)}/{second['id']}", json={"name": first["name"]}, headers=auth_owner)
        assert resp.status_code == 409

    def test_get_missing(self, client, ws, auth_owner):
        resp = client.get(f"{BASE.format(ws=ws.id)}/999999", headers=auth_owner)
        assert resp.status_code == 404
        assert resp.json()["code"] == "pipeline_not_found"

    def test_delete_cascades_runs_and_findings(self, client, ws, auth_owner, people, db):
        add_rows(db, people, [{"姓名": None, "城市": None}])
        workflow = _create(client, ws, auth_owner, content=FINDING_CONTENT).json()
        assert _trigger(client, ws, auth_owner, workflow["id"]).status_code == 202
        _expire(db)
        resp = client.delete(f"{BASE.format(ws=ws.id)}/{workflow['id']}", headers=auth_owner)
        assert resp.status_code == 204
        assert db.execute(select(PipelineRun)).scalars().all() == []
        assert db.execute(select(PipelineFinding)).scalars().all() == []
        assert db.execute(select(PipelineWorkflowVersion)).scalars().all() == []


class TestVersions:
    """版本历史：新建落 v1 / 保存落版 / 列表 / 详情 / diff / 恢复（ADR 0114）."""

    def test_create_writes_first_manual_version(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        rows = db.execute(select(PipelineWorkflowVersion)).scalars().all()
        assert len(rows) == 1
        assert rows[0].workflow_id == workflow["id"]
        assert rows[0].version_number == 1
        assert rows[0].change_type == CHANGE_TYPE_MANUAL
        assert rows[0].content == CLEAN_CONTENT
        assert rows[0].comment == ""

    def test_update_content_writes_new_version(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        new_content = CLEAN_CONTENT.replace("文档巡检", "文档巡检改")
        assert (
            client.put(
                f"{BASE.format(ws=ws.id)}/{workflow['id']}",
                json={"content": new_content},
                headers=auth_owner,
            ).status_code
            == 200
        )
        rows = (
            db.execute(select(PipelineWorkflowVersion).order_by(PipelineWorkflowVersion.version_number)).scalars().all()
        )
        assert [row.version_number for row in rows] == [1, 2]
        assert rows[1].content == new_content
        assert rows[1].change_type == CHANGE_TYPE_MANUAL

    def test_update_same_content_or_enabled_only_keeps_version(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        url = f"{BASE.format(ws=ws.id)}/{workflow['id']}"
        assert client.put(url, json={"content": CLEAN_CONTENT}, headers=auth_owner).status_code == 200
        assert client.put(url, json={"enabled": False}, headers=auth_owner).status_code == 200
        assert len(db.execute(select(PipelineWorkflowVersion)).scalars().all()) == 1

    def test_list_versions_desc_without_content(self, client, ws, auth_owner):
        workflow = _create(client, ws, auth_owner).json()
        client.put(
            f"{BASE.format(ws=ws.id)}/{workflow['id']}",
            json={"content": CLEAN_CONTENT.replace("文档巡检", "文档巡检改")},
            headers=auth_owner,
        )
        resp = client.get(_versions_url(ws, workflow["id"]), headers=auth_owner)
        assert resp.status_code == 200
        items = resp.json()
        assert [item["version_number"] for item in items] == [2, 1]
        assert all("content" not in item for item in items)
        assert items[0]["change_type"] == CHANGE_TYPE_MANUAL

    def test_version_detail_and_not_found(self, client, ws, auth_owner):
        workflow = _create(client, ws, auth_owner).json()
        resp = client.get(f"{_versions_url(ws, workflow['id'])}/1", headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json()["content"] == CLEAN_CONTENT

        missing = client.get(f"{_versions_url(ws, workflow['id'])}/99", headers=auth_owner)
        assert missing.status_code == 404
        assert missing.json()["code"] == "pipeline_version_not_found"

    def test_diff_between_versions(self, client, ws, auth_owner):
        workflow = _create(client, ws, auth_owner).json()
        client.put(
            f"{BASE.format(ws=ws.id)}/{workflow['id']}",
            json={"content": CLEAN_CONTENT.replace("文档巡检", "文档巡检改")},
            headers=auth_owner,
        )
        resp = client.get(
            f"{BASE.format(ws=ws.id)}/{workflow['id']}/diff",
            params={"base": 1, "head": 2},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["base_version"] == 1
        assert body["head_version"] == 2
        assert "文档巡检改" in body["diff"]
        assert body["added"] >= 1
        assert body["removed"] >= 1

    def test_diff_missing_version(self, client, ws, auth_owner):
        workflow = _create(client, ws, auth_owner).json()
        resp = client.get(
            f"{BASE.format(ws=ws.id)}/{workflow['id']}/diff",
            params={"base": 1, "head": 2},
            headers=auth_owner,
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "pipeline_version_not_found"

    def test_restore_writes_rollback_version_and_preserves_enabled(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        url = f"{BASE.format(ws=ws.id)}/{workflow['id']}"
        client.put(
            url,
            json={"content": CLEAN_CONTENT.replace("文档巡检", "文档巡检改"), "enabled": False},
            headers=auth_owner,
        )
        resp = client.post(f"{_versions_url(ws, workflow['id'])}/1/restore", headers=auth_owner)
        assert resp.status_code == 200
        body = resp.json()
        assert body["content"] == CLEAN_CONTENT
        assert body["name"] == "文档巡检"
        assert body["enabled"] is False

        _expire(db)
        rows = (
            db.execute(select(PipelineWorkflowVersion).order_by(PipelineWorkflowVersion.version_number)).scalars().all()
        )
        assert [row.version_number for row in rows] == [1, 2, 3]
        assert rows[2].change_type == CHANGE_TYPE_ROLLBACK
        assert rows[2].comment == "恢复自 v1"
        assert rows[2].content == CLEAN_CONTENT

    def test_restore_invalid_historical_content_writes_nothing(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        db.add(
            PipelineWorkflowVersion(
                workspace_id=ws.id,
                workflow_id=workflow["id"],
                version_number=2,
                change_type=CHANGE_TYPE_MANUAL,
                content="name: 坏\njobs: []\n",
                comment="",
            )
        )
        db.commit()

        resp = client.post(f"{_versions_url(ws, workflow['id'])}/2/restore", headers=auth_owner)
        assert resp.status_code == 400
        assert resp.json()["code"] == "pipeline_dsl_invalid"

        _expire(db)
        current = client.get(f"{BASE.format(ws=ws.id)}/{workflow['id']}", headers=auth_owner).json()
        assert current["content"] == CLEAN_CONTENT
        assert len(db.execute(select(PipelineWorkflowVersion)).scalars().all()) == 2

    def test_restore_name_conflict_writes_nothing(self, client, ws, auth_owner, db):
        first = _create(client, ws, auth_owner).json()
        second = _create(client, ws, auth_owner, content=CLEAN_CONTENT.replace("文档巡检", "文档巡检二")).json()
        # 人为让 first 的历史版本名称与 second 当前名称冲突
        db.add(
            PipelineWorkflowVersion(
                workspace_id=ws.id,
                workflow_id=first["id"],
                version_number=2,
                change_type=CHANGE_TYPE_MANUAL,
                content=CLEAN_CONTENT.replace("文档巡检", "文档巡检二"),
                comment="",
            )
        )
        db.commit()

        resp = client.post(f"{_versions_url(ws, first['id'])}/2/restore", headers=auth_owner)
        assert resp.status_code == 409
        _expire(db)
        current = client.get(f"{BASE.format(ws=ws.id)}/{first['id']}", headers=auth_owner).json()
        assert current["name"] == first["name"]
        assert second["name"] == "文档巡检二"

    def test_viewer_can_read_but_not_restore(self, client, ws, auth_owner, auth_viewer):
        workflow = _create(client, ws, auth_owner).json()
        assert client.get(_versions_url(ws, workflow["id"]), headers=auth_viewer).status_code == 200
        assert client.get(f"{_versions_url(ws, workflow['id'])}/1", headers=auth_viewer).status_code == 200
        assert (
            client.get(
                f"{BASE.format(ws=ws.id)}/{workflow['id']}/diff",
                params={"base": 1, "head": 1},
                headers=auth_viewer,
            ).status_code
            == 200
        )
        assert client.post(f"{_versions_url(ws, workflow['id'])}/1/restore", headers=auth_viewer).status_code == 403

    def test_versions_isolated_by_workspace(self, client, db, auth_owner, ws, owner, auth_outsider):
        workflow = _create(client, ws, auth_owner).json()
        other = make_workspace(db, owner, "PipelineVersionOtherWS")
        # owner 同时是 other 的 OWNER，但定义属于 ws：按工作区 + ID 定位应 404
        resp = client.get(_versions_url(other, workflow["id"]), headers=auth_owner)
        assert resp.status_code == 404
        assert resp.json()["code"] == "pipeline_not_found"

        assert client.get(_versions_url(ws, workflow["id"]), headers=auth_outsider).status_code == 403


class TestRuns:
    def test_trigger_and_run_detail(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        resp = _trigger(client, ws, auth_owner, workflow["id"])
        assert resp.status_code == 202
        assert resp.json()["trigger"] == "manual"
        run_id = resp.json()["id"]

        _expire(db)
        detail = client.get(f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}", headers=auth_owner)
        assert detail.status_code == 200
        body = detail.json()
        assert body["status"] == "success"
        assert body["workflow_name"] == workflow["name"]
        assert body["stats"]["jobs"][0]["conclusion"] == "success"

    def test_trigger_single_flight_conflict(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        db.add(
            PipelineRun(
                workflow_id=workflow["id"],
                workspace_id=ws.id,
                trigger="manual",
                trigger_payload={},
                status="pending",
                stats={},
                error_message="",
            )
        )
        db.commit()
        resp = _trigger(client, ws, auth_owner, workflow["id"])
        assert resp.status_code == 409
        assert resp.json()["code"] == "pipeline_conflict"

    def test_list_runs_pagination(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        for _ in range(2):
            assert _trigger(client, ws, auth_owner, workflow["id"]).status_code == 202
        _expire(db)
        resp = client.get(
            f"{BASE.format(ws=ws.id)}/{workflow['id']}/runs", params={"limit": 1, "offset": 1}, headers=auth_owner
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["items"]) == 1

    def test_run_not_found(self, client, ws, auth_owner):
        resp = client.get(f"/api/v1/workspaces/{ws.id}/pipeline-runs/999999", headers=auth_owner)
        assert resp.status_code == 404
        assert resp.json()["code"] == "pipeline_run_not_found"

    def test_list_workspace_runs_defaults_to_all_workflows(self, client, ws, auth_owner, db):
        """工作区历史默认覆盖全部规则（前端右栏未选中规则时的取数口径）."""
        first = _create(client, ws, auth_owner).json()
        second = _create(client, ws, auth_owner, content=CLEAN_CONTENT.replace("文档巡检", "文档巡检二")).json()
        assert _trigger(client, ws, auth_owner, first["id"]).status_code == 202
        assert _trigger(client, ws, auth_owner, second["id"]).status_code == 202
        _expire(db)

        resp = client.get(f"/api/v1/workspaces/{ws.id}/pipeline-runs", headers=auth_owner)
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert {item["workflow_id"] for item in body["items"]} == {first["id"], second["id"]}
        names = {item["workflow_id"]: item["workflow_name"] for item in body["items"]}
        assert names == {first["id"]: first["name"], second["id"]: second["name"]}

    def test_list_workspace_runs_filter_by_workflow(self, client, ws, auth_owner, db):
        first = _create(client, ws, auth_owner).json()
        second = _create(client, ws, auth_owner, content=CLEAN_CONTENT.replace("文档巡检", "文档巡检二")).json()
        assert _trigger(client, ws, auth_owner, first["id"]).status_code == 202
        assert _trigger(client, ws, auth_owner, second["id"]).status_code == 202
        _expire(db)

        resp = client.get(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs",
            params={"workflow_id": first["id"]},
            headers=auth_owner,
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert [item["workflow_id"] for item in body["items"]] == [first["id"]]

    def test_list_workspace_runs_filter_by_domain(self, client, ws, auth_owner, db):
        """运行历史按域过滤：数据表页只看数据表规则的运行."""
        doc_flow = _create(client, ws, auth_owner).json()
        table_flow = _create(client, ws, auth_owner, content=FINDING_CONTENT).json()
        assert _trigger(client, ws, auth_owner, doc_flow["id"]).status_code == 202
        assert _trigger(client, ws, auth_owner, table_flow["id"]).status_code == 202
        _expire(db)

        doc_runs = client.get(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs",
            params={"domain": "document"},
            headers=auth_owner,
        ).json()
        table_runs = client.get(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs",
            params={"domain": "table"},
            headers=auth_owner,
        ).json()

        assert doc_runs["total"] == 1
        assert [item["workflow_id"] for item in doc_runs["items"]] == [doc_flow["id"]]
        assert table_runs["total"] == 1
        assert [item["workflow_id"] for item in table_runs["items"]] == [table_flow["id"]]

    def test_list_workspace_runs_rejects_unknown_domain(self, client, ws, auth_owner):
        resp = client.get(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs",
            params={"domain": "bogus"},
            headers=auth_owner,
        )
        assert resp.status_code == 400

    def test_list_workspace_runs_isolated_by_workspace(self, client, db, owner, auth_owner, ws):
        workflow = _create(client, ws, auth_owner).json()
        assert _trigger(client, ws, auth_owner, workflow["id"]).status_code == 202
        other = make_workspace(db, owner, "RunsListOtherWs")
        assert client.get(f"/api/v1/workspaces/{other.id}/pipeline-runs", headers=auth_owner).json()["total"] == 0
        _expire(db)
        assert client.get(f"/api/v1/workspaces/{ws.id}/pipeline-runs", headers=auth_owner).json()["total"] == 1

    def test_list_workspace_runs_permissions(self, client, ws, auth_owner, auth_viewer, auth_outsider, db):
        workflow = _create(client, ws, auth_owner).json()
        assert _trigger(client, ws, auth_owner, workflow["id"]).status_code == 202
        _expire(db)

        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs"
        assert client.get(url, headers=auth_viewer).status_code == 200
        assert client.get(url, headers=auth_outsider).status_code == 403

    def test_run_isolated_by_workspace(self, client, db, owner, auth_owner, ws):
        workflow = _create(client, ws, auth_owner).json()
        assert _trigger(client, ws, auth_owner, workflow["id"]).status_code == 202
        other = make_workspace(db, owner, "OtherWs")
        run_id = db.execute(select(PipelineRun.id)).scalars().first()
        resp = client.get(f"/api/v1/workspaces/{other.id}/pipeline-runs/{run_id}", headers=auth_owner)
        assert resp.status_code == 404

    def test_findings_filters_and_pagination(self, client, ws, auth_owner, people, db):
        add_rows(db, people, [{"姓名": None, "城市": None}])
        workflow = _create(client, ws, auth_owner, content=FINDING_CONTENT).json()
        assert _trigger(client, ws, auth_owner, workflow["id"]).status_code == 202
        run_id = db.execute(select(PipelineRun.id)).scalars().first()
        _expire(db)
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}/findings"

        resp = client.get(url, headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

        resp = client.get(url, params={"severity": "warn", "target_type": "table"}, headers=auth_owner)
        assert resp.json()["total"] == 2

        resp = client.get(url, params={"check": "table/null-rate"}, headers=auth_owner)
        assert resp.json()["total"] == 2

        resp = client.get(url, params={"severity": "error"}, headers=auth_owner)
        assert resp.json()["total"] == 0

        resp = client.get(url, params={"limit": 1, "offset": 1}, headers=auth_owner)
        assert resp.json()["total"] == 2
        assert len(resp.json()["items"]) == 1


class TestRunHistoryMaintenance:
    """运行历史删除 / 清空（需求卡片 0133）."""

    def test_delete_run_cascades_findings(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        run = _add_run(db, ws, workflow["id"])
        finding = _add_finding(db, run.id)
        run_id, finding_id = run.id, finding.id
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}"

        assert client.delete(url, headers=auth_owner).status_code == 204
        _expire(db)
        assert db.get(PipelineRun, run_id) is None
        assert db.get(PipelineFinding, finding_id) is None

    def test_delete_active_run_rejected(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        run = _add_run(db, ws, workflow["id"], status="running")
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run.id}"

        resp = client.delete(url, headers=auth_owner)
        assert resp.status_code == 409
        assert resp.json()["code"] == "pipeline_conflict"
        _expire(db)
        assert db.get(PipelineRun, run.id) is not None

    def test_delete_run_permissions_and_workspace_scope(
        self, client, ws, owner, auth_owner, auth_viewer, auth_outsider, db
    ):
        workflow = _create(client, ws, auth_owner).json()
        run = _add_run(db, ws, workflow["id"])
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run.id}"

        assert client.delete(url, headers=auth_viewer).status_code == 403
        assert client.delete(url, headers=auth_outsider).status_code == 403
        other = make_workspace(db, owner, "RunDeleteOtherWs")
        assert (
            client.delete(f"/api/v1/workspaces/{other.id}/pipeline-runs/{run.id}", headers=auth_owner).status_code
            == 404
        )
        _expire(db)
        assert db.get(PipelineRun, run.id) is not None

    def test_clear_runs_by_workflow(self, client, ws, auth_owner, db):
        first = _create(client, ws, auth_owner, content=CLEAN_CONTENT.replace("name: 文档巡检", "name: 巡检A")).json()
        second = _create(client, ws, auth_owner, content=CLEAN_CONTENT.replace("name: 文档巡检", "name: 巡检B")).json()
        kept_run = _add_run(db, ws, second["id"])
        removed_run = _add_run(db, ws, first["id"])
        finding = _add_finding(db, removed_run.id)
        removed_id, finding_id, kept_id = removed_run.id, finding.id, kept_run.id
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs"

        resp = client.delete(url, params={"workflow_id": first["id"]}, headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json() == {"deleted": 1}
        _expire(db)
        assert db.get(PipelineRun, removed_id) is None
        assert db.get(PipelineFinding, finding_id) is None
        assert db.get(PipelineRun, kept_id) is not None

    def test_clear_runs_by_domain(self, client, ws, auth_owner, db):
        document = _create(client, ws, auth_owner, content=CLEAN_CONTENT).json()
        table = _create(client, ws, auth_owner, content=FINDING_CONTENT).json()
        document_run = _add_run(db, ws, document["id"])
        table_run = _add_run(db, ws, table["id"])
        document_id, table_id = document_run.id, table_run.id
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs"

        resp = client.delete(url, params={"domain": "table"}, headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json() == {"deleted": 1}
        _expire(db)
        assert db.get(PipelineRun, table_id) is None
        assert db.get(PipelineRun, document_id) is not None

    def test_clear_runs_rejects_active_in_scope(self, client, ws, auth_owner, db):
        active_workflow = _create(
            client, ws, auth_owner, content=CLEAN_CONTENT.replace("name: 文档巡检", "name: 活跃巡检")
        ).json()
        done_workflow = _create(
            client, ws, auth_owner, content=CLEAN_CONTENT.replace("name: 文档巡检", "name: 完成巡检")
        ).json()
        active_run = _add_run(db, ws, active_workflow["id"], status="pending")
        done_run = _add_run(db, ws, done_workflow["id"])
        active_id, done_id = active_run.id, done_run.id
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs"

        resp = client.delete(url, headers=auth_owner)
        assert resp.status_code == 409
        assert resp.json()["code"] == "pipeline_conflict"
        _expire(db)
        assert db.get(PipelineRun, active_id) is not None
        assert db.get(PipelineRun, done_id) is not None

    def test_clear_runs_all_and_permissions(self, client, ws, auth_owner, auth_viewer, auth_outsider, db):
        workflow = _create(client, ws, auth_owner).json()
        first_run = _add_run(db, ws, workflow["id"])
        second_run = _add_run(db, ws, workflow["id"])
        first_id, second_id = first_run.id, second_run.id
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs"

        assert client.delete(url, headers=auth_viewer).status_code == 403
        assert client.delete(url, headers=auth_outsider).status_code == 403

        resp = client.delete(url, headers=auth_owner)
        assert resp.status_code == 200
        assert resp.json() == {"deleted": 2}
        _expire(db)
        assert db.get(PipelineRun, first_id) is None
        assert db.get(PipelineRun, second_id) is None

    def test_clear_runs_rejects_unknown_domain(self, client, ws, auth_owner):
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs"
        resp = client.delete(url, params={"domain": "bogus"}, headers=auth_owner)
        assert resp.status_code == 400
        assert resp.json()["code"] == "bad_request"


class TestFindingContextVisibility:
    """document/sensitive 的命中上下文按文档可见性裁剪（草稿不对普通成员暴露）."""

    def _finding(self, client, db, ws, headers, target_id: int) -> tuple[int, int]:
        workflow = _create(
            client,
            ws,
            headers,
            content="""
name: 敏感内容巡检
jobs:
  文档:
    steps:
      - uses: document/sensitive
        with:
          keywords: [身份]
""",
        ).json()
        run = PipelineRun(
            workflow_id=workflow["id"],
            workspace_id=ws.id,
            trigger="manual",
            trigger_payload={},
            status="partial",
            stats={},
            error_message="",
        )
        db.add(run)
        db.flush()
        finding = PipelineFinding(
            run_id=run.id,
            check="document/sensitive",
            severity="warn",
            target_type="document",
            target_id=target_id,
            locator={
                "rule": "身份",
                "kind": "keyword",
                "keyword": "身份",
                "field": "content",
                "line": 1,
            },
            message="敏感内容命中：「身份」关键词「身份」",
            detail={
                "rule": "身份",
                "kind": "keyword",
                "field": "content",
                "document_title": "他人草稿",
                "line": 1,
                "snippet": "身份证号 110101199001011234",
                "match": "身份",
                "match_start": 0,
                "match_end": 2,
            },
        )
        db.add(finding)
        db.commit()
        return run.id, finding.id

    def test_hidden_draft_context_is_redacted_for_member(self, client, db, ws, auth_owner, auth_viewer):
        author = make_user(db, "sensitive_draft_author")
        draft = make_document(db, ws, "他人草稿", "身份证号 110101199001011234", user=author)
        run_id, _ = self._finding(client, db, ws, auth_owner, draft.id)
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}/findings"

        viewer_item = client.get(url, headers=auth_viewer).json()["items"][0]
        assert viewer_item["detail"]["redacted"] is True
        for key in ("document_title", "snippet", "match", "match_start", "match_end"):
            assert key not in viewer_item["detail"]
        # 规则与定位口径仍保留（不返回草稿正文）
        assert viewer_item["locator"]["rule"] == "身份"
        assert viewer_item["locator"]["keyword"] == "身份"

        owner_item = client.get(url, headers=auth_owner).json()["items"][0]
        assert owner_item["detail"]["document_title"] == "他人草稿"
        assert owner_item["detail"]["snippet"].startswith("身份证号")
        assert "redacted" not in owner_item["detail"]


class TestFindingToIssue:
    """发现物一键转 Issue（ADR 0076 P2 / D15）."""

    def _table_finding(self, client, ws, headers, people, db) -> tuple[int, int]:
        add_rows(db, people, [{"姓名": None, "城市": None}])
        workflow = _create(client, ws, headers, content=FINDING_CONTENT).json()
        assert _trigger(client, ws, headers, workflow["id"]).status_code == 202
        run_id = db.execute(select(PipelineRun.id)).scalars().first()
        _expire(db)
        url = f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}/findings"
        finding_id = client.get(url, headers=headers).json()["items"][0]["id"]
        return run_id, finding_id

    def test_table_finding_converts_to_issue(self, client, ws, auth_owner, people, db):
        run_id, finding_id = self._table_finding(client, ws, auth_owner, people, db)
        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}/findings/{finding_id}/issue",
            headers=auth_owner,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["table_id"] == people.id
        assert body["title"].startswith("[warn]")
        assert body["category"] == "data_error"
        assert "流水线检查：table/null-rate" in body["description"]
        assert "定位：" in body["description"]
        assert body["status"] == "open"

        from cndb.plugins.issues.models import Issue

        issue = db.get(Issue, body["id"])
        assert issue is not None and issue.table_id == people.id

    def test_viewer_can_convert(self, client, ws, auth_owner, auth_viewer, people, db):
        run_id, finding_id = self._table_finding(client, ws, auth_owner, people, db)
        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}/findings/{finding_id}/issue",
            headers=auth_viewer,
        )
        assert resp.status_code == 201, resp.text

    def test_non_table_target_rejected(self, client, ws, auth_owner, db):
        workflow = _create(client, ws, auth_owner).json()
        run = PipelineRun(
            workflow_id=workflow["id"],
            workspace_id=ws.id,
            trigger="manual",
            trigger_payload={},
            status="success",
            stats={},
            error_message="",
        )
        db.add(run)
        db.flush()
        finding = PipelineFinding(
            run_id=run.id,
            check="document/links",
            severity="warn",
            target_type="document",
            target_id=1,
            locator={},
            message="链接失效",
            detail={},
        )
        db.add(finding)
        db.commit()
        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run.id}/findings/{finding.id}/issue",
            headers=auth_owner,
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "pipeline_finding_not_table"

    def test_finding_or_run_not_found(self, client, ws, auth_owner, people, db):
        run_id, _ = self._table_finding(client, ws, auth_owner, people, db)
        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}/findings/999999/issue",
            headers=auth_owner,
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "pipeline_finding_not_found"

        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs/999999/findings/1/issue",
            headers=auth_owner,
        )
        assert resp.status_code == 404
        assert resp.json()["code"] == "pipeline_run_not_found"

    def test_run_isolated_by_workspace(self, client, db, owner, ws, auth_owner, people):
        run_id, finding_id = self._table_finding(client, ws, auth_owner, people, db)
        other = make_workspace(db, owner, "IssueOtherWs")
        resp = client.post(
            f"/api/v1/workspaces/{other.id}/pipeline-runs/{run_id}/findings/{finding_id}/issue",
            headers=auth_owner,
        )
        assert resp.status_code == 404

    def test_outsider_denied(self, client, ws, auth_outsider, people, db, auth_owner):
        run_id, finding_id = self._table_finding(client, ws, auth_owner, people, db)
        resp = client.post(
            f"/api/v1/workspaces/{ws.id}/pipeline-runs/{run_id}/findings/{finding_id}/issue",
            headers=auth_outsider,
        )
        assert resp.status_code == 403


class TestPermissions:
    def test_viewer_can_read_only(self, client, ws, auth_owner, auth_viewer):
        workflow = _create(client, ws, auth_owner).json()
        assert client.get(BASE.format(ws=ws.id), headers=auth_viewer).status_code == 200
        assert client.get(f"{BASE.format(ws=ws.id)}/{workflow['id']}", headers=auth_viewer).status_code == 200
        assert client.get(f"{BASE.format(ws=ws.id)}/checks", headers=auth_viewer).status_code == 200
        assert _create(client, ws, auth_viewer).status_code == 403
        assert (
            client.put(
                f"{BASE.format(ws=ws.id)}/{workflow['id']}", json={"enabled": False}, headers=auth_viewer
            ).status_code
            == 403
        )
        assert _trigger(client, ws, auth_viewer, workflow["id"]).status_code == 403
        assert client.delete(f"{BASE.format(ws=ws.id)}/{workflow['id']}", headers=auth_viewer).status_code == 403

    def test_outsider_denied(self, client, ws, auth_outsider):
        assert client.get(BASE.format(ws=ws.id), headers=auth_outsider).status_code == 403
        assert client.get(f"{BASE.format(ws=ws.id)}/checks", headers=auth_outsider).status_code == 403

    def test_missing_workspace(self, client, auth_owner):
        resp = client.get(BASE.format(ws=999999), headers=auth_owner)
        assert resp.status_code == 404
