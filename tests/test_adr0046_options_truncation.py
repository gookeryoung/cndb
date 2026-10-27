"""ADR 0046 P1：options 截断（展示链路瘦身）.

覆盖 ADR 0046 测试清单：
- ``truncate_field_config``：>500 截断 + 标志位；≤500 原样；``full=True`` 不截断；非 dict 原样丢回；
- 表详情 / 字段列表默认截断、``fields?full=1`` 返回全量；
- 截断只影响序列化：库内 config 与字段更新链路保留全量选项。
"""

from __future__ import annotations

import pytest

from cndb.plugins.tables.services.core.field_serialization import (
    OPTIONS_DISPLAY_LIMIT,
    truncate_field_config,
)


def _big_options(n: int) -> list[dict[str, str]]:
    return [{"label": f"代码{i:05d}", "value": f"代码{i:05d}"} for i in range(n)]


class TestTruncateFieldConfig:
    def test_truncates_over_limit(self):
        cfg = {"options": _big_options(OPTIONS_DISPLAY_LIMIT + 1)}
        out = truncate_field_config(cfg)
        assert len(out["options"]) == OPTIONS_DISPLAY_LIMIT
        assert out["options_truncated"] is True
        assert out["options_total"] == OPTIONS_DISPLAY_LIMIT + 1
        # 不改原对象
        assert len(cfg["options"]) == OPTIONS_DISPLAY_LIMIT + 1

    def test_keeps_small_options(self):
        cfg = {"options": _big_options(3)}
        out = truncate_field_config(cfg)
        assert out is cfg
        assert "options_truncated" not in out

    def test_full_flag_not_truncated(self):
        cfg = {"options": _big_options(OPTIONS_DISPLAY_LIMIT + 10)}
        assert truncate_field_config(cfg, full=True) is cfg

    def test_non_dict_or_missing_options(self):
        assert truncate_field_config(None) is None
        cfg = {"max_length": 10}
        assert truncate_field_config(cfg) is cfg

    def test_options_not_list(self):
        cfg = {"options": "oops"}
        assert truncate_field_config(cfg) is cfg


@pytest.fixture
def big_select_table(client, auth_headers):
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_opts"}).json()
    wid = ws["id"]
    tid = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_opts"}).json()["id"]
    total = OPTIONS_DISPLAY_LIMIT + 50
    resp = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "股票代码", "field_type": "select", "order": 0, "config": {"options": _big_options(total)}},
    )
    assert resp.status_code in (200, 201), resp.text
    return wid, tid, total


class TestApiTruncation:
    def test_table_detail_truncates(self, client, auth_headers, big_select_table):
        wid, tid, total = big_select_table
        detail = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}", headers=auth_headers).json()
        field = next(f for f in detail["fields"] if f["name"] == "股票代码")
        assert len(field["config"]["options"]) == OPTIONS_DISPLAY_LIMIT
        assert field["config"]["options_truncated"] is True
        assert field["config"]["options_total"] == total

    def test_fields_list_truncates_by_default(self, client, auth_headers, big_select_table):
        wid, tid, total = big_select_table
        fields = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=auth_headers).json()
        cfg = fields[0]["config"]
        assert len(cfg["options"]) == OPTIONS_DISPLAY_LIMIT
        assert cfg["options_total"] == total

    def test_fields_full_returns_all(self, client, auth_headers, big_select_table):
        wid, tid, total = big_select_table
        fields = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/fields?full=true", headers=auth_headers).json()
        cfg = fields[0]["config"]
        assert len(cfg["options"]) == total
        assert "options_truncated" not in cfg

    def test_db_config_keeps_full_options(self, client, auth_headers, big_select_table, db):
        from cndb.plugins.tables.models import DataField

        _wid, tid, total = big_select_table
        # 展示层截断不影响库内配置（编辑 / 校验仍拿全量）
        field = db.query(DataField).filter(DataField.table_id == tid).first()
        assert len(field.config["options"]) == total
        assert "options_truncated" not in field.config

    def test_small_field_not_marked_truncated(self, client, auth_headers):
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_small"}).json()
        wid = ws["id"]
        tid = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_small"}).json()[
            "id"
        ]
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "状态", "field_type": "select", "order": 0, "config": {"options": ["高", "中", "低"]}},
        )
        detail = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}", headers=auth_headers).json()
        cfg = detail["fields"][0]["config"]
        # 后端会把字符串选项归一化为 {label, value, color}，只断言数量与无截断标志
        assert len(cfg["options"]) == 3
        assert "options_truncated" not in cfg
