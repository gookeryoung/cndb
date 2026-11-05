"""datasource http_json：响应解析 / 请求展开 / payload 守卫（ADR 0104 口径）.

保留能力：``rows`` 记录形态、``data_path`` 模板（单路径）、标的展开、分页；
ADR 0104 删除的 ``rows_array`` / 候选路径 / ``row_defaults`` / ``scale``
必须被 payload 守卫显式拒绝（不静默忽略）。
"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    PagingSpec,
    ProviderError,
    RequestSpec,
    SyncJobSpec,
    normalize_field_mapping,
)
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider
from cndb.plugins.datasource.services.normalize import apply_field_mapping
from cndb.plugins.datasource.services.runner import (
    field_mapping_from_payload,
    request_spec_from_payload,
)

PROVIDER = HttpJsonProvider()


def _job(**overrides: object) -> SyncJobSpec:
    """构造最小可用 job，测试按需覆盖字段."""
    base: dict[str, object] = {"request": RequestSpec(url_template="https://api.example.com/v1/items")}
    base.update(overrides)
    return SyncJobSpec(**base)  # type: ignore[arg-type]


class TestRowsParse:
    def test_parse_uses_data_path(self):
        payload = {"data": {"items": [{"a": 1}, {"a": 2}]}}
        rows = PROVIDER.parse(
            json.dumps(payload), _job(request=RequestSpec(url_template="https://x.test", data_path="data.items"))
        )
        assert rows == [{"a": 1}, {"a": 2}]

    def test_parse_filters_non_object_rows(self):
        payload = [{"a": 1}, "坏行", 3]
        assert PROVIDER.parse(json.dumps(payload), _job()) == [{"a": 1}]

    def test_parse_invalid_json_raises(self):
        with pytest.raises(ProviderError, match="不是合法 JSON"):
            PROVIDER.parse("not-json", _job())

    def test_parse_columns_mode_delegates(self):
        payload = {"daily": {"time": ["2026-10-20"], "temp": [20.5]}}
        job = _job(
            request=RequestSpec(
                url_template="https://api.example.com/v1",
                record_mode="columns",
                data_path="daily",
            )
        )
        assert PROVIDER.parse(json.dumps(payload), job) == [{"time": "2026-10-20", "temp": 20.5}]


class TestBuildRequests:
    def test_data_path_rendered_per_entrant(self):
        job = _job(
            request=RequestSpec(url_template="https://api.example.com/v1", data_path="data.{entrant}.items"),
            entrant_param="symbol",
            entrant_values=("item-a", "item-b"),
        )
        configs = [plan.config for plan in PROVIDER.build_requests(job)]
        assert [config.data_path for config in configs] == ["data.item-a.items", "data.item-b.items"]
        assert [config.url for config in configs] == ["https://api.example.com/v1", "https://api.example.com/v1"]

    def test_paging_expands_to_pages(self):
        job = _job(
            request=RequestSpec(
                url_template="https://api.example.com/v1?page={page}",
                paging=PagingSpec(mode="page", page_size=2, max_pages=3),
            )
        )
        plans = PROVIDER.build_requests(job)
        assert [plan.page for plan in plans] == [1, 2, 3]
        assert plans[1].config.url.endswith("page=2")

    def test_no_entrant_yields_single_request(self):
        assert len(PROVIDER.build_requests(_job())) == 1

    def test_response_handler_only_for_custom_parse(self):
        assert PROVIDER.response_handler_for(_job()) is None

        class _Custom(HttpJsonProvider):
            uses_custom_parse = True

        assert _Custom().response_handler_for(_job()) is not None


class TestNormalize:
    def test_apply_field_mapping_converts_types(self):
        result = apply_field_mapping(
            [{"volume": "12", "name": 3}],
            {
                "volume": FieldTransform(name="成交量", field_type="int"),
                "name": FieldTransform(name="名称", field_type="text"),
            },
        )
        assert result.rows == [{"成交量": 12, "名称": "3"}]

    def test_normalize_field_mapping_reads_name_and_type(self):
        mapping = normalize_field_mapping({"volume": {"name": "成交量", "field_type": "int"}})
        assert mapping["volume"] == FieldTransform(name="成交量", field_type="int")


class TestRequestSpecGuards:
    @pytest.mark.parametrize("key", ["url_hosts", "row_defaults", "row_filter", "workers"])
    def test_removed_keys_rejected(self, key: str):
        with pytest.raises(ValueError, match=f"已删除的声明键.*{key}"):
            request_spec_from_payload({"url_template": "https://api.example.com/v1", key: {}})

    def test_rows_array_mode_rejected(self):
        with pytest.raises(ValueError, match="record_mode 非法"):
            request_spec_from_payload({"url_template": "https://api.example.com/v1", "record_mode": "rows_array"})

    def test_data_path_candidates_rejected(self):
        with pytest.raises(ValueError, match="不再支持 \\| 候选路径"):
            request_spec_from_payload({"url_template": "https://api.example.com/v1", "data_path": "a|b"})

    def test_single_data_path_accepted(self):
        spec = request_spec_from_payload(
            {"url_template": "https://api.example.com/v1", "data_path": "data.{entrant}.items"}
        )
        assert spec.data_path == "data.{entrant}.items"

    def test_columns_mode_accepted(self):
        spec = request_spec_from_payload(
            {
                "url_template": "https://api.example.com/v1",
                "record_mode": "columns",
                "record_layout": {"日期": "time"},
            }
        )
        assert spec.record_mode == "columns"
        assert spec.record_layout == {"日期": "time"}


class TestFieldMappingGuards:
    def test_scale_rejected(self):
        with pytest.raises(ValueError, match="scale 已删除"):
            field_mapping_from_payload({"volume": {"name": "成交量", "field_type": "int", "scale": 100}})

    def test_plain_mapping_accepted(self):
        mapping = field_mapping_from_payload({"volume": {"name": "成交量", "field_type": "int"}})
        assert mapping["volume"] == FieldTransform(name="成交量", field_type="int")

    def test_null_drops_field(self):
        assert field_mapping_from_payload({"raw": None}) == {"raw": None}

    def test_string_shorthand_renames(self):
        assert field_mapping_from_payload({"volume": "成交量"}) == {"volume": FieldTransform(name="成交量")}

    def test_invalid_value_rejected(self):
        with pytest.raises(ValueError, match="必须是对象 / 字符串 / null"):
            field_mapping_from_payload({"volume": 100})
