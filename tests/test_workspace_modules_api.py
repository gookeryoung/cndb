"""工作区模块 API 层测试（ADR 0080：创建/更新校验、目录过滤、保存期域拒绝）."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

WS = "/api/v1/workspaces"

DOC_DSL = """jobs:
  文档体检:
    steps:
      - uses: document/links
"""


def _new_workspace(
    client: TestClient, headers: dict[str, str], name: str, modules: list[str] | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {"name": name}
    if modules is not None:
        payload["modules"] = modules
    r = client.post(WS, json=payload, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


class TestWorkspaceModulesCrud:
    def test_create_with_modules_normalized(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "乱序模块", ["design", "tables", "design"])
        assert ws["modules"] == ["tables", "design"]

    def test_create_default_all_modules(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "默认全选")
        assert ws["modules"] == ["tables", "documents", "design"]

    def test_create_empty_modules_422(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        r = client.post(WS, json={"name": "空集", "modules": []}, headers=auth_headers)
        assert r.status_code == 422, r.text

    def test_create_unknown_module_422(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        r = client.post(WS, json={"name": "非法", "modules": ["tables", "data"]}, headers=auth_headers)
        assert r.status_code == 422, r.text

    def test_update_modules(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "待更新")
        r = client.patch(f"{WS}/{ws['id']}", json={"modules": ["design"]}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["modules"] == ["design"]

    def test_update_empty_modules_422(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "更新空集")
        r = client.patch(f"{WS}/{ws['id']}", json={"modules": []}, headers=auth_headers)
        assert r.status_code == 422, r.text


class TestChecksCatalogFilter:
    def test_tables_only_workspace_gets_table_checks(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "仅数据表", ["tables"])
        r = client.get(f"{WS}/{ws['id']}/pipelines/checks", headers=auth_headers)
        assert r.status_code == 200, r.text
        uses = [item["uses"] for item in r.json()]
        assert uses, "目录不应为空"
        assert all(u.startswith("table/") for u in uses)

    def test_documents_only_workspace_gets_document_checks(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        ws = _new_workspace(client, auth_headers, "仅文档", ["documents"])
        r = client.get(f"{WS}/{ws['id']}/pipelines/checks", headers=auth_headers)
        assert r.status_code == 200, r.text
        uses = [item["uses"] for item in r.json()]
        assert uses
        assert all(u.startswith("document/") for u in uses)

    def test_design_only_workspace_gets_empty_catalog(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "仅设计", ["design"])
        r = client.get(f"{WS}/{ws['id']}/pipelines/checks", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json() == []


class TestDslDomainGate:
    def test_create_rejects_disabled_domain(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "域拒绝", ["tables"])
        r = client.post(
            f"{WS}/{ws['id']}/pipelines",
            json={"name": "文档巡检", "content": DOC_DSL},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text
        assert "documents" in r.json()["detail"]

    def test_validate_rejects_disabled_domain(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "校验拒绝", ["tables"])
        r = client.post(
            f"{WS}/{ws['id']}/pipelines/validate",
            json={"name": "文档巡检", "content": DOC_DSL},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text

    def test_update_rejects_disabled_domain(self, client: TestClient, auth_headers: dict[str, str]) -> None:
        ws = _new_workspace(client, auth_headers, "更新拒绝", ["tables", "documents"])
        created = client.post(
            f"{WS}/{ws['id']}/pipelines",
            json={"name": "巡检", "content": DOC_DSL},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        # 收窄模块后再次编辑内容：禁用域动作被拒
        narrowed = client.patch(f"{WS}/{ws['id']}", json={"modules": ["tables"]}, headers=auth_headers)
        assert narrowed.status_code == 200, narrowed.text
        r = client.put(
            f"{WS}/{ws['id']}/pipelines/{created.json()['id']}",
            json={"content": DOC_DSL},
            headers=auth_headers,
        )
        assert r.status_code == 400, r.text

    def test_existing_pipeline_still_runs_after_module_narrowed(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """边界 #3：存量流水线不受目录过滤影响，模块收窄后仍可运行."""
        ws = _new_workspace(client, auth_headers, "存量可跑", ["tables", "documents"])
        created = client.post(
            f"{WS}/{ws['id']}/pipelines",
            json={"name": "存量巡检", "content": DOC_DSL},
            headers=auth_headers,
        )
        assert created.status_code == 201, created.text
        narrowed = client.patch(f"{WS}/{ws['id']}", json={"modules": ["tables"]}, headers=auth_headers)
        assert narrowed.status_code == 200, narrowed.text
        r = client.post(f"{WS}/{ws['id']}/pipelines/{created.json()['id']}/run", headers=auth_headers)
        assert r.status_code == 202, r.text
