"""文档图表的工作区备份 / 恢复往返（ADR 0048，v8 备份格式）.

覆盖：export 携带 ``charts`` 键（title / template_key / config）、import 到新工作区
与已存在工作区两条路径、旧版备份（无 charts 键）兼容、模板下线实例跳过不阻断。
往返语义为「实例存在且可渲染」——正文 ``{{chart:旧id}}`` 引用不重写 id（与
``{{table:id}}`` 同口径）。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

WS = "/api/v1/workspaces"
DOCS = "/api/v1/workspaces/{wid}/documents"
CHARTS = "/api/v1/workspaces/{wid}/charts"


def _new_workspace(client: TestClient, headers: dict[str, str], name: str = "图表备份源") -> int:
    r = client.post(WS, json={"name": name}, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_chart(client: TestClient, headers: dict[str, str], wid: int, template_key: str, config: dict) -> dict:
    r = client.post(
        CHARTS.format(wid=wid),
        json={"title": f"图表·{template_key}", "template_key": template_key, "config": config},
        headers=headers,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _seed_source(client: TestClient, headers: dict[str, str], default_config_of) -> tuple[int, list[dict]]:
    """建图表 + 引用它的文档，导出备份；返回 (wid, charts 载荷)."""
    wid = _new_workspace(client, headers)
    chart = _create_chart(
        client,
        headers,
        wid,
        "bar-line-dual-axis",
        default_config_of("bar-line-dual-axis"),
    )
    r = client.post(
        DOCS.format(wid=wid),
        json={"title": "产业规划", "content": f"见 {{chart:{chart['id']}}}。\n"},
        headers=headers,
    )
    assert r.status_code == 201, r.text

    backup = client.get(f"{WS}/{wid}/export", headers=headers).json()
    assert backup["version"] == "8"
    return wid, backup["charts"]


class TestExportCharts:
    def test_export_carries_charts(self, client, auth_headers):
        from cndb.plugins.documents.services.charts.registry import CHART_TEMPLATES

        _wid, charts = _seed_source(client, auth_headers, lambda k: CHART_TEMPLATES[k].default_config)
        assert len(charts) == 1
        entry = charts[0]
        assert entry["template_key"] == "bar-line-dual-axis"
        assert entry["title"] == "图表·bar-line-dual-axis"
        assert entry["config"]["caption"]["title"] == "产业营业收入与增速（2020—2030年）"

    def test_export_empty_workspace_has_no_charts(self, client, auth_headers):
        wid = _new_workspace(client, auth_headers)
        backup = client.get(f"{WS}/{wid}/export", headers=auth_headers).json()
        assert backup["charts"] == []


class TestImportCharts:
    def test_roundtrip_via_new_workspace(self, client, auth_headers):
        """建 → 备 → 还 → 实例存在且可渲染（D12 往返口径）."""
        from cndb.plugins.documents.services.charts.registry import CHART_TEMPLATES

        src_wid, _charts = _seed_source(client, auth_headers, lambda k: CHART_TEMPLATES[k].default_config)

        backup = client.get(f"{WS}/{src_wid}/export", headers=auth_headers).json()
        r = client.post(f"{WS}/import", json={"json_data": backup}, headers=auth_headers)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["errors"] == []
        assert body["imported_charts"] == 1
        new_wid = body["workspace"]["id"]

        listing = client.get(CHARTS.format(wid=new_wid), headers=auth_headers).json()
        assert len(listing["items"]) == 1
        restored = listing["items"][0]
        assert restored["template_key"] == "bar-line-dual-axis"

        # 可渲染（往返语义：实例存在且可渲染，正文引用不重写）
        render = client.get(CHARTS.format(wid=new_wid) + f"/{restored['id']}/render", headers=auth_headers)
        assert render.status_code == 200
        assert "<svg" in render.text

    def test_import_into_existing_workspace(self, client, auth_headers):
        from cndb.plugins.documents.services.charts.registry import CHART_TEMPLATES

        src_wid, _charts = _seed_source(client, auth_headers, lambda k: CHART_TEMPLATES[k].default_config)
        backup = client.get(f"{WS}/{src_wid}/export", headers=auth_headers).json()
        target = _new_workspace(client, auth_headers, "图表目标")

        r = client.post(f"{WS}/{target}/import", json={"json_data": backup}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["imported_charts"] == 1
        listing = client.get(CHARTS.format(wid=target), headers=auth_headers).json()
        assert len(listing["items"]) == 1

    def test_legacy_backup_without_charts_key(self, client, auth_headers):
        """旧版备份（v7 及以前，无 charts 键）导入不受影响."""
        src_wid, _charts = _seed_source(client, auth_headers, _minimal_dual_config)
        backup = client.get(f"{WS}/{src_wid}/export", headers=auth_headers).json()
        assert backup["charts"], "前置：源工作区含图表"
        legacy = {k: v for k, v in backup.items() if k != "charts"}
        legacy["version"] = "7"

        target = _new_workspace(client, auth_headers, "旧版目标")
        r = client.post(f"{WS}/{target}/import", json={"json_data": legacy}, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported_charts"] == 0
        assert body["errors"] == []

    def test_offline_template_skipped_with_error(self, client, auth_headers):
        """模板已下线的实例跳过并记错误，不阻断其余内容导入."""
        src_wid, _charts = _seed_source(client, auth_headers, _minimal_dual_config)
        backup = client.get(f"{WS}/{src_wid}/export", headers=auth_headers).json()
        backup["charts"][0]["template_key"] = "retired-template"

        target = _new_workspace(client, auth_headers, "下线目标")
        r = client.post(f"{WS}/{target}/import", json={"json_data": backup}, headers=auth_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["imported_charts"] == 0
        assert any("模板下线或配置非法" in e for e in body["errors"])

    def test_invalid_config_skipped_with_error(self, client, auth_headers):
        src_wid, _charts = _seed_source(client, auth_headers, _minimal_dual_config)
        backup = client.get(f"{WS}/{src_wid}/export", headers=auth_headers).json()
        backup["charts"][0]["config"] = {"data": {"rows": "bad"}}

        target = _new_workspace(client, auth_headers, "坏配置目标")
        r = client.post(f"{WS}/{target}/import", json={"json_data": backup}, headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["imported_charts"] == 0
        assert r.json()["errors"]


def _minimal_dual_config(_key: str | None = None) -> dict:
    return {
        "caption": {"no": "图 1", "title": "最小图", "note": ""},
        "labels": {},
        "theme": {},
        "data": {
            "actualCount": 1,
            "rows": [
                {"label": "2025", "value": 100, "growth": None},
                {"label": "2026", "value": 110, "growth": None},
            ],
        },
    }
