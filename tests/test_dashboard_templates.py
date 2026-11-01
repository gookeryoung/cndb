"""dashboard 模板 API 测试（ADR 0023 P3：另存为模板 / 模板列表 / 删除）.

模板复用 ``accounts_user.preferences`` JSON 存储（per-user，零迁移），
只存「结构 + 字段名/类型快照」，来源表 ``query.table_id`` 由后端统一剥离。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.accounts.models import User
from cndb.plugins.accounts.services.preferences import (
    MAX_DASHBOARD_TEMPLATES,
    save_dashboard_template,
)

URL = "/api/v1/accounts/preferences/dashboard-templates"


def _kpi_config(**query: Any) -> dict[str, Any]:
    """最小可用的 dashboard 配置（含一个 KPI 块）."""
    return {
        "schema_version": 1,
        "canvas": {"cols": 12, "row_height": 40},
        "settings": {},
        "widgets": [
            {
                "id": "w_kpi_1",
                "type": "kpi",
                "layout": {"x": 0, "y": 0, "w": 3, "h": 4},
                "query": {"filters": [], "filter_logic": "AND", "sortings": [], **query},
                "kpi": {"value": {"field": "金额", "agg": "sum"}},
            }
        ],
    }


def _template_payload(name: str = "经营概览", **query: Any) -> dict[str, Any]:
    return {
        "name": name,
        "config": _kpi_config(**query),
        "fields": {"金额": "number", "日期": "date"},
    }


class TestDashboardTemplateAPI:
    def test_list_empty(self, client, auth_headers):
        """首次查询返回空列表（不暴露 preferences 其它键）."""
        r = client.get(URL, headers=auth_headers)
        assert r.status_code == 200
        assert r.json() == []

    def test_requires_auth(self, client):
        """未认证的读 / 写 / 删一律 401."""
        assert client.get(URL).status_code == 401
        assert client.post(URL, json=_template_payload()).status_code == 401
        assert client.delete(f"{URL}/abc").status_code == 401

    def test_save_and_list(self, client, auth_headers):
        """另存后可在列表中读回，并带字段类型快照."""
        r = client.post(URL, json=_template_payload(), headers=auth_headers)
        assert r.status_code == 200, r.text
        saved = r.json()
        assert saved["name"] == "经营概览"
        assert saved["fields"] == {"金额": "number", "日期": "date"}
        assert saved["id"]
        assert saved["updated_at"]

        listed = client.get(URL, headers=auth_headers).json()
        assert [item["id"] for item in listed] == [saved["id"]]
        assert listed[0]["config"]["widgets"][0]["kpi"]["value"]["field"] == "金额"

    def test_source_table_id_is_stripped(self, client, auth_headers):
        """模板不硬编码来源表：保存时剥离 widgets[i].query.table_id."""
        r = client.post(URL, json=_template_payload(table_id=7), headers=auth_headers)
        assert r.status_code == 200, r.text
        query = r.json()["config"]["widgets"][0]["query"]
        assert "table_id" not in query
        assert query["filters"] == []

    def test_same_name_overwrites_in_place(self, client, auth_headers):
        """同名模板原地覆盖：保留 id、列表不新增，内容与时间刷新."""
        first = client.post(URL, json=_template_payload(), headers=auth_headers).json()
        second_body = _template_payload()
        second_body["config"]["widgets"][0]["kpi"]["value"]["agg"] = "count"
        second = client.post(URL, json=second_body, headers=auth_headers).json()
        assert second["id"] == first["id"]
        assert second["config"]["widgets"][0]["kpi"]["value"]["agg"] == "count"
        assert len(client.get(URL, headers=auth_headers).json()) == 1

    def test_new_template_precedes_older(self, client, auth_headers):
        """新保存的模板排在最前."""
        a = client.post(URL, json=_template_payload("A"), headers=auth_headers).json()
        b = client.post(URL, json=_template_payload("B"), headers=auth_headers).json()
        ids = [item["id"] for item in client.get(URL, headers=auth_headers).json()]
        assert ids == [b["id"], a["id"]]

    def test_rejects_blank_or_too_long_name(self, client, auth_headers):
        """名称为空 / 纯空白 / 超 60 字符一律 400."""
        for name in ("", "   ", "x" * 61):
            r = client.post(URL, json=_template_payload(name), headers=auth_headers)
            assert r.status_code == 400, name

    def test_rejects_config_without_widgets(self, client, auth_headers):
        """配置缺 widgets 数组或非对象 → 400."""
        assert client.post(URL, json={"name": "坏模板", "config": {}}, headers=auth_headers).status_code == 400
        assert (
            client.post(
                URL,
                json={"name": "坏模板", "config": {"widgets": "nope"}},
                headers=auth_headers,
            ).status_code
            == 400
        )

    def test_rejects_too_many_widgets(self, client, auth_headers):
        """单模板最多 32 个组件."""
        config = _kpi_config()
        config["widgets"] = config["widgets"] * 33
        r = client.post(URL, json={"name": "超量", "config": config}, headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_oversized_config(self, client, auth_headers):
        """序列化后超过 200KB → 400."""
        config = _kpi_config()
        config["widgets"][0]["text"] = {"content": "x" * 250_000}
        r = client.post(URL, json={"name": "超大", "config": config}, headers=auth_headers)
        assert r.status_code == 400

    def test_rejects_when_template_limit_reached(self, client, db, auth_headers):
        """超过每用户上限后新增模板 400（同名覆盖不受限）."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        for index in range(MAX_DASHBOARD_TEMPLATES):
            save_dashboard_template(db, user, name=f"T{index}", config=_kpi_config())
        r = client.post(URL, json=_template_payload("新模板"), headers=auth_headers)
        assert r.status_code == 400
        # 同名覆盖仍允许
        r = client.post(URL, json=_template_payload("T0"), headers=auth_headers)
        assert r.status_code == 200

    def test_delete_success_and_missing(self, client, auth_headers):
        """删除已存在模板 → 204；重复删除 / 不存在 → 404."""
        saved = client.post(URL, json=_template_payload(), headers=auth_headers).json()
        r = client.delete(f"{URL}/{saved['id']}", headers=auth_headers)
        assert r.status_code == 204
        assert client.get(URL, headers=auth_headers).json() == []
        assert client.delete(f"{URL}/{saved['id']}", headers=auth_headers).status_code == 404

    def test_isolated_per_user(self, client, db):
        """模板按用户隔离：他人列表不可见，删除他人模板 404."""
        client.post("/api/v1/accounts/auth/register", json={"username": "tmplA", "password": "passw0rd"})
        token_a = client.post("/api/v1/accounts/auth/login", json={"login": "tmplA", "password": "passw0rd"}).json()[
            "access_token"
        ]
        ha = {"Authorization": f"Bearer {token_a}"}
        saved = client.post(URL, json=_template_payload("A 的模板"), headers=ha).json()

        client.post("/api/v1/accounts/auth/register", json={"username": "tmplB", "password": "passw0rd"})
        token_b = client.post("/api/v1/accounts/auth/login", json={"login": "tmplB", "password": "passw0rd"}).json()[
            "access_token"
        ]
        hb = {"Authorization": f"Bearer {token_b}"}

        assert client.get(URL, headers=hb).json() == []
        assert client.delete(f"{URL}/{saved['id']}", headers=hb).status_code == 404

    def test_corrupted_entries_are_dropped(self, client, db, auth_headers):
        """偏好中结构损坏的模板项在读取时被丢弃，不影响正常项."""
        user: User = db.query(User).filter(User.username == "testuser").first()
        user.preferences["dashboard_templates"] = [
            {"id": "ok", "name": "正常", "config": _kpi_config(), "fields": {}},
            {"id": "", "name": "缺 id", "config": {}},
            {"id": "bad", "name": "", "config": {}},
            {"id": "bad2", "name": "config 非对象", "config": []},
            "garbage",
        ]
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(user, "preferences")
        db.commit()

        listed = client.get(URL, headers=auth_headers).json()
        assert [item["id"] for item in listed] == ["ok"]
