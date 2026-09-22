"""api_config_loader 模块单元测试 —— 覆盖配置校验、加载、批量建表."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from cndb.plugins.tables.services.importing import api_config_loader as acl
from cndb.plugins.tables.services.importing import api_fetch as af
from cndb.plugins.tables.services.importing.api_config_loader import ApiConfigError

# ── validate_api_config 错误分支 ───────────────────


class TestValidateApiConfigErrors:
    def test_top_level_not_dict(self):
        with pytest.raises(ApiConfigError, match="顶层必须是对象"):
            acl.validate_api_config("not a dict")

    def test_missing_tables_key(self):
        with pytest.raises(ApiConfigError, match="缺少有效的 tables"):
            acl.validate_api_config({})

    def test_tables_not_list(self):
        with pytest.raises(ApiConfigError, match="缺少有效的 tables"):
            acl.validate_api_config({"tables": "not-a-list"})

    def test_tables_empty(self):
        with pytest.raises(ApiConfigError, match="缺少有效的 tables"):
            acl.validate_api_config({"tables": []})

    def test_table_item_not_dict(self):
        with pytest.raises(ApiConfigError, match="tables\\[0\\] 必须是对象"):
            acl.validate_api_config({"tables": ["bad"]})

    def test_table_missing_name(self):
        with pytest.raises(ApiConfigError, match="缺少 table_name"):
            acl.validate_api_config({"tables": [{"fetch": {"url": "http://x"}}]})

    def test_table_name_empty(self):
        with pytest.raises(ApiConfigError, match="缺少 table_name"):
            acl.validate_api_config({"tables": [{"table_name": "", "fetch": {"url": "http://x"}}]})

    def test_duplicate_table_names(self):
        cfg = {
            "tables": [
                {"table_name": "重复表", "fetch": {"url": "https://a.com"}},
                {"table_name": "重复表", "fetch": {"url": "https://b.com"}},
            ]
        }
        with pytest.raises(ApiConfigError, match="重复"):
            acl.validate_api_config(cfg)

    def test_fetch_not_dict(self):
        with pytest.raises(ApiConfigError, match="fetch 必须是对象"):
            acl.validate_api_config({"tables": [{"table_name": "t", "fetch": "nope"}]})

    def test_fetch_missing_url(self):
        with pytest.raises(ApiConfigError, match=r"fetch\.url 必须是非空字符串"):
            acl.validate_api_config({"tables": [{"table_name": "t", "fetch": {}}]})

    def test_fetch_url_empty(self):
        with pytest.raises(ApiConfigError, match=r"fetch\.url 必须是非空字符串"):
            acl.validate_api_config({"tables": [{"table_name": "t", "fetch": {"url": ""}}]})

    def test_unknown_response_handler(self):
        cfg = {
            "tables": [
                {
                    "table_name": "t",
                    "fetch": {"url": "https://x.com", "response_handler": "nonexistent_handler"},
                }
            ]
        }
        with pytest.raises(ApiConfigError, match="未注册"):
            acl.validate_api_config(cfg)

    def test_query_interval_below_min_warns(self):
        """query_interval < MIN_QUERY_INTERVAL 应记录 warning 但不报错."""
        cfg = {
            "tables": [
                {
                    "table_name": "t",
                    "fetch": {"url": "https://x.com", "query_interval": 1},
                }
            ]
        }
        result = acl.validate_api_config(cfg)
        assert len(result) == 1


# ── validate_api_config 成功路径 ────────────────────


class TestValidateApiConfigOk:
    def test_basic_valid_config(self):
        cfg = {
            "tables": [
                {"table_name": "股票", "fetch": {"url": "https://qt.gtimg.cn/q=sh600519"}},
            ]
        }
        result = acl.validate_api_config(cfg)
        assert len(result) == 1
        assert result[0]["table_name"] == "股票"

    def test_multiple_tables(self):
        cfg = {
            "tables": [
                {"table_name": "A", "fetch": {"url": "https://a.com"}},
                {"table_name": "B", "fetch": {"url": "https://b.com", "method": "POST"}},
                {"table_name": "C", "fetch": {"url": "https://c.com", "response_handler": "tencent_stock"}},
            ]
        }
        result = acl.validate_api_config(cfg)
        assert len(result) == 3


# ── build_fetch_config ─────────────────────────────


class TestBuildFetchConfig:
    def test_defaults(self):
        td = {"table_name": "t", "fetch": {"url": "https://x.com"}}
        cfg = acl.build_fetch_config(td)
        assert cfg.url == "https://x.com"
        assert cfg.method == "GET"
        assert cfg.headers == {}
        assert cfg.params == {}
        assert cfg.body is None
        assert cfg.timeout == 15.0
        assert cfg.data_path is None
        assert cfg.response_handler == "json"
        assert cfg.encoding == "utf-8"
        assert cfg.query_interval == af.DEFAULT_QUERY_INTERVAL

    def test_all_fields(self):
        td = {
            "table_name": "t",
            "fetch": {
                "url": "https://x.com",
                "method": "POST",
                "headers": {"X": "1"},
                "params": {"k": "v"},
                "body": {"q": "hi"},
                "timeout": 30,
                "data_path": "data.items",
                "response_handler": "tencent_stock",
                "encoding": "gbk",
                "query_interval": 3,
            },
        }
        cfg = acl.build_fetch_config(td)
        assert cfg.method == "POST"
        assert cfg.headers == {"X": "1"}
        assert cfg.params == {"k": "v"}
        assert cfg.body == {"q": "hi"}
        assert cfg.timeout == 30.0
        assert cfg.data_path == "data.items"
        assert cfg.response_handler == "tencent_stock"
        assert cfg.encoding == "gbk"
        # query_interval=3 低于 MIN_QUERY_INTERVAL=6，会被夹取
        assert cfg.query_interval == af.MIN_QUERY_INTERVAL

    def test_query_interval_zero_uses_default(self):
        td = {"table_name": "t", "fetch": {"url": "https://x.com", "query_interval": 0}}
        cfg = acl.build_fetch_config(td)
        assert cfg.query_interval == af.DEFAULT_QUERY_INTERVAL

    def test_query_interval_negative_uses_default(self):
        td = {"table_name": "t", "fetch": {"url": "https://x.com", "query_interval": -10}}
        cfg = acl.build_fetch_config(td)
        assert cfg.query_interval == af.DEFAULT_QUERY_INTERVAL

    def test_headers_and_params_falsy_become_empty_dict(self):
        td = {
            "table_name": "t",
            "fetch": {"url": "https://x.com", "headers": None, "params": None},
        }
        cfg = acl.build_fetch_config(td)
        assert cfg.headers == {}
        assert cfg.params == {}


# ── load_api_config_file ───────────────────────────


class TestLoadApiConfigFile:
    def test_file_not_found(self, tmp_path):
        missing = tmp_path / "no_such_file.json"
        with pytest.raises(ApiConfigError, match="配置文件不存在"):
            acl.load_api_config_file(missing)

    def test_invalid_json(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        with pytest.raises(ApiConfigError, match="解析失败"):
            acl.load_api_config_file(bad)

    def test_valid_file(self, tmp_path):
        good = tmp_path / "good.json"
        good.write_text(
            json.dumps({"tables": [{"table_name": "行情", "fetch": {"url": "https://qt.gtimg.cn/q=sh600519"}}]}),
            encoding="utf-8-sig",  # 测试 BOM
        )
        result = acl.load_api_config_file(good)
        assert len(result) == 1

    def test_path_str(self, tmp_path):
        good = tmp_path / "str_path.json"
        good.write_text(json.dumps({"tables": [{"table_name": "x", "fetch": {"url": "http://x"}}]}))
        result = acl.load_api_config_file(str(good))
        assert len(result) == 1


# ── load_api_config_text ───────────────────────────


class TestLoadApiConfigText:
    def test_invalid_json(self):
        with pytest.raises(ApiConfigError, match="JSON 解析失败"):
            acl.load_api_config_text("not json")

    def test_valid_text(self):
        text = json.dumps({"tables": [{"table_name": "x", "fetch": {"url": "http://x"}}]})
        result = acl.load_api_config_text(text)
        assert len(result) == 1

    def test_invalid_config_payload(self):
        with pytest.raises(ApiConfigError, match="缺少有效的 tables"):
            acl.load_api_config_text(json.dumps({}))


# ── ingest_tables_from_config（mock ingest_from_api） ─


class TestIngestTablesFromConfig:
    def test_success(self):
        mock_dt = MagicMock()
        mock_dt.id = 42

        with patch("cndb.plugins.tables.transfer.ingest_from_api", return_value=(mock_dt, [1, 2, 3], ["a", "b"])):
            results = acl.ingest_tables_from_config(
                engine=MagicMock(),
                db=MagicMock(),
                workspace_id=1,
                table_defs=[{"table_name": "测试表", "fetch": {"url": "https://example.com/api"}}],
            )

        assert len(results) == 1
        assert results[0]["table_name"] == "测试表"
        assert results[0]["table_id"] == 42
        assert results[0]["imported_rows"] == 3
        assert results[0]["field_count"] == 2
        assert results[0]["query_interval"] == af.DEFAULT_QUERY_INTERVAL

    def test_multiple_tables(self):
        mock_dt1 = MagicMock()
        mock_dt1.id = 100
        mock_dt2 = MagicMock()
        mock_dt2.id = 200

        call_count = [0]

        def _fake_ingest(*args, **kwargs):
            call_count[0] += 1
            dt = mock_dt1 if call_count[0] == 1 else mock_dt2
            return dt, [1], ["col"]

        with patch("cndb.plugins.tables.transfer.ingest_from_api", side_effect=_fake_ingest):
            results = acl.ingest_tables_from_config(
                engine=MagicMock(),
                db=MagicMock(),
                workspace_id=1,
                table_defs=[
                    {"table_name": "表A", "fetch": {"url": "https://a.com"}},
                    {"table_name": "表B", "fetch": {"url": "https://b.com"}},
                ],
            )

        assert len(results) == 2
        assert results[0]["table_name"] == "表A"
        assert results[1]["table_name"] == "表B"


__all__ = []
