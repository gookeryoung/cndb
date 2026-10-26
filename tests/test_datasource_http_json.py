"""datasource http_json 通用解析扩展：行数组 / 路径模板 / 常量列 / 数值缩放.

对应 ADR 0033 P0：``rows_array`` 记录形态、``data_path`` 模板、``row_defaults``、
``FieldTransform.scale`` 四项领域无关声明能力。
"""

from __future__ import annotations

import json

import pytest

from cndb.plugins.datasource.providers.base import (
    FieldTransform,
    ProviderError,
    RequestSpec,
    SyncJobSpec,
    normalize_field_mapping,
)
from cndb.plugins.datasource.providers.http_json import HttpJsonProvider, rows_array_to_rows
from cndb.plugins.datasource.services.normalize import apply_field_mapping
from cndb.plugins.datasource.services.pipeline import apply_row_defaults, run_pipeline
from cndb.plugins.datasource.services.runner import (
    field_mapping_from_payload,
    request_spec_from_payload,
)

PROVIDER = HttpJsonProvider()

# 腾讯日线形态：外层带 code，标的键下是「行数组的数组」
TENCENT_PAYLOAD = {
    "code": 0,
    "msg": "",
    "data": {
        "sh600519": {
            "qfqday": [
                ["2026-10-20", "1500.00", "1510.00", "1520.00", "1490.00", "12345"],
                ["2026-10-21", "1510.00", "1520.00", "1530.00", "1500.00", "23456"],
            ]
        }
    },
}

DAY_LAYOUT = {
    "日期": 0,
    "开盘": 1,
    "收盘": 2,
    "最高": 3,
    "最低": 4,
    "成交量": 5,
}


def _job(**overrides: object) -> SyncJobSpec:
    """构造最小可用 job，测试按需覆盖字段."""
    base: dict[str, object] = {"request": RequestSpec(url_template="https://api.example.com/v1/items")}
    base.update(overrides)
    return SyncJobSpec(**base)  # type: ignore[arg-type]


class TestRowsArrayToRows:
    def test_parses_nested_array_rows(self):
        rows = rows_array_to_rows(TENCENT_PAYLOAD, "data.sh600519.qfqday", DAY_LAYOUT)
        assert len(rows) == 2
        assert rows[0]["日期"] == "2026-10-20"
        assert rows[1]["成交量"] == "23456"

    def test_accepts_digit_string_index(self):
        rows = rows_array_to_rows([["a", "b"]], None, {"第一列": "0", "第二列": "1"})
        assert rows == [{"第一列": "a", "第二列": "b"}]

    def test_short_row_fills_none_without_dropping(self):
        rows = rows_array_to_rows([["a"]], None, {"x": 0, "y": 1})
        assert rows == [{"x": "a", "y": None}]

    def test_empty_series_returns_empty(self):
        assert rows_array_to_rows({"data": {"s": {"qfqday": []}}}, "data.s.qfqday", DAY_LAYOUT) == []

    def test_missing_path_raises(self):
        with pytest.raises(ProviderError, match="指向一个数组"):
            rows_array_to_rows(TENCENT_PAYLOAD, "data.sh600519.day", DAY_LAYOUT)

    def test_row_not_array_raises(self):
        with pytest.raises(ProviderError, match="元素必须是数组"):
            rows_array_to_rows([{"x": 1}], None, {"x": 0})

    def test_missing_layout_raises(self):
        with pytest.raises(ProviderError, match="必须声明 record_layout"):
            rows_array_to_rows([["a"]], None, {})

    def test_bool_index_raises(self):
        with pytest.raises(ProviderError, match="不能是布尔值"):
            rows_array_to_rows([["a"]], None, {"x": True})

    def test_non_numeric_index_raises(self):
        with pytest.raises(ProviderError, match="必须是整数"):
            rows_array_to_rows([["a"]], None, {"x": "第一列"})

    def test_negative_index_raises(self):
        with pytest.raises(ProviderError, match="不能为负"):
            rows_array_to_rows([["a"]], None, {"x": -1})


class TestProviderDispatch:
    def test_rows_array_mode_uses_custom_handler(self):
        job = _job(request=RequestSpec(url_template="https://api.example.com/v1", record_mode="rows_array"))
        assert PROVIDER.response_handler_for(job) is not None

    def test_rows_mode_has_no_custom_handler(self):
        assert PROVIDER.response_handler_for(_job()) is None

    def test_parse_dispatches_rows_array(self):
        job = _job(
            request=RequestSpec(
                url_template="https://api.example.com/v1",
                record_mode="rows_array",
                data_path="data.{symbol}.qfqday",
                record_layout=DAY_LAYOUT,
            ),
            entrant_param="symbol",
            entrant_values=("sh600519",),
        )
        config = PROVIDER.build_requests(job)[0].config
        # data_path 按标的渲染
        assert config.data_path == "data.sh600519.qfqday"
        rows = PROVIDER.parse(json.dumps(TENCENT_PAYLOAD), job, data_path=config.data_path)
        assert rows[0]["收盘"] == "1510.00"

    def test_parse_uses_spec_data_path_without_override(self):
        job = _job(
            request=RequestSpec(
                url_template="https://api.example.com/v1",
                record_mode="rows_array",
                data_path="data.sh600519.qfqday",
                record_layout={"日期": 0},
            )
        )
        rows = PROVIDER.parse(json.dumps(TENCENT_PAYLOAD), job)
        assert rows[0]["日期"] == "2026-10-20"

    def test_parse_rows_mode_still_works(self):
        payload = {"items": [{"a": 1}]}
        rows = PROVIDER.parse(json.dumps(payload), _job())
        assert rows == [{"a": 1}]

    def test_parse_rows_array_invalid_json_raises(self):
        job = _job(request=RequestSpec(url_template="https://api.example.com/v1", record_mode="rows_array"))
        with pytest.raises(ProviderError, match="不是合法 JSON"):
            PROVIDER.parse("not-json", job)


class TestDataPathCandidates:
    """``data_path`` 候选回退（ADR 0039 D1/D3）：同一资源可能只回 qfqday 或 day."""

    DAY_ONLY_PAYLOAD = {
        "code": 0,
        "data": {
            "sh562550": {
                "day": [
                    ["2026-10-20", "1.100", "1.120", "1.130", "1.090", "1234"],
                    ["2026-10-21", "1.120", "1.130", "1.140", "1.110", "2345"],
                ]
            }
        },
    }

    @staticmethod
    def _mk_job(data_path: str) -> SyncJobSpec:
        return _job(
            request=RequestSpec(
                url_template="https://proxy.example.com/kline?param={symbol}",
                record_mode="rows_array",
                data_path=data_path,
                record_layout={"日期": 0, "收盘": 2},
            ),
            entrant_param="symbol",
            entrant_values=("sh562550",),
        )

    def test_falls_back_to_day_when_qfqday_absent(self):
        job = self._mk_job("data.{entrant}.qfqday|data.{entrant}.day")
        config = PROVIDER.build_requests(job)[0].config
        # 候选串整体渲染，分隔符保留
        assert config.data_path == "data.sh562550.qfqday|data.sh562550.day"
        rows = PROVIDER.parse(json.dumps(self.DAY_ONLY_PAYLOAD), job, data_path=config.data_path)
        assert rows == [
            {"日期": "2026-10-20", "收盘": "1.120"},
            {"日期": "2026-10-21", "收盘": "1.130"},
        ]

    def test_prefers_first_non_empty_candidate(self):
        payload = {"data": {"sh562550": {"qfqday": TENCENT_PAYLOAD["data"]["sh600519"]["qfqday"], "day": []}}}
        rows = PROVIDER.parse(
            json.dumps(payload),
            self._mk_job("data.sh562550.qfqday|data.sh562550.day"),
            data_path="data.sh562550.qfqday|data.sh562550.day",
        )
        assert rows[0]["日期"] == "2026-10-20"

    def test_empty_first_candidate_tries_next(self):
        payload = {"data": {"sh562550": {"qfqday": [], "day": [["2026-10-20", "1.100", "1.120"]]}}}
        rows = PROVIDER.parse(
            json.dumps(payload),
            self._mk_job("data.sh562550.qfqday|data.sh562550.day"),
            data_path="data.sh562550.qfqday|data.sh562550.day",
        )
        assert rows == [{"日期": "2026-10-20", "收盘": "1.120"}]

    def test_all_candidates_empty_returns_empty(self):
        payload = {"data": {"sh562550": {"qfqday": [], "day": []}}}
        rows = PROVIDER.parse(
            json.dumps(payload),
            self._mk_job("data.sh562550.qfqday|data.sh562550.day"),
            data_path="data.sh562550.qfqday|data.sh562550.day",
        )
        assert rows == []

    def test_all_candidates_missing_lists_candidates(self):
        payload = {"data": {"sh562550": {"qt": {}}}}
        with pytest.raises(ProviderError) as excinfo:
            PROVIDER.parse(
                json.dumps(payload),
                self._mk_job("data.sh562550.qfqday|data.sh562550.day"),
                data_path="data.sh562550.qfqday|data.sh562550.day",
            )
        message = str(excinfo.value)
        assert "指向一个数组" in message
        assert "data.sh562550.qfqday" in message
        assert "data.sh562550.day" in message

    def test_single_path_message_unchanged(self):
        with pytest.raises(ProviderError, match=r"^行数组记录要求 data_path 指向一个数组$"):
            PROVIDER.parse(
                json.dumps(self.DAY_ONLY_PAYLOAD),
                self._mk_job("data.sh562550.qfqday"),
                data_path="data.sh562550.qfqday",
            )


class TestRowDefaults:
    def test_setdefault_semantics(self):
        rows = apply_row_defaults([{"a": 1, "来源": "响应自带"}], {"来源": "新浪"})
        assert rows == [{"a": 1, "来源": "响应自带"}]

    def test_fills_missing_columns(self):
        rows = apply_row_defaults([{"a": 1}], {"来源": "新浪", "复权方式": "不复权"})
        assert rows == [{"a": 1, "来源": "新浪", "复权方式": "不复权"}]

    def test_without_defaults_copies_rows(self):
        rows = apply_row_defaults([{"a": 1}], {})
        assert rows == [{"a": 1}]

    def test_sync_job_spec_falls_back_to_request_defaults(self):
        job = _job(request=RequestSpec(url_template="https://api.example.com/v1", row_defaults={"来源": "腾讯"}))
        assert job.row_defaults == {"来源": "腾讯"}

    def test_pipeline_applies_defaults_and_entrant(self):
        job = _job(
            request=RequestSpec(
                url_template="https://api.example.com/v1",
                record_mode="rows_array",
                record_layout={"日期": 0, "收盘": 1},
                row_defaults={"来源": "腾讯", "复权方式": "前复权"},
            ),
            entrant_param="symbol",
            entrant_values=("sh600519",),
        )
        outcome = run_pipeline(job, fetch=lambda _config: [{"日期": "2026-10-20", "收盘": "1510.00"}])
        assert outcome.rows == [
            {"日期": "2026-10-20", "收盘": "1510.00", "symbol": "sh600519", "来源": "腾讯", "复权方式": "前复权"}
        ]


class TestFieldScale:
    def test_scale_multiplies_numeric(self):
        result = apply_field_mapping(
            [{"volume": 12}], {"volume": FieldTransform(name="成交量", field_type="int", scale=100)}
        )
        assert result.rows == [{"成交量": 1200}]

    def test_scale_keeps_none(self):
        result = apply_field_mapping(
            [{"volume": None}], {"volume": FieldTransform(name="成交量", field_type="int", scale=100)}
        )
        assert result.rows == [{"成交量": None}]

    def test_scale_applies_to_numeric_strings(self):
        # 行情接口多以字符串返回数值，缩放须同样生效
        result = apply_field_mapping(
            [{"volume": "12"}], {"volume": FieldTransform(name="成交量", field_type="int", scale=100)}
        )
        assert result.rows == [{"成交量": 1200}]

    def test_scale_passes_through_unconvertible_string(self):
        result = apply_field_mapping(
            [{"volume": "N/A"}], {"volume": FieldTransform(name="成交量", field_type="int", scale=100)}
        )
        assert result.rows == [{"成交量": None}]
        assert result.failures and result.failures[0].field == "成交量"

    def test_scale_ignored_for_text_target(self):
        result = apply_field_mapping(
            [{"volume": "12"}], {"volume": FieldTransform(name="成交量", field_type="text", scale=100)}
        )
        assert result.rows == [{"成交量": "12"}]

    def test_scale_ignores_bool(self):
        result = apply_field_mapping(
            [{"flag": True}], {"flag": FieldTransform(name="标志", field_type="bool", scale=100)}
        )
        assert result.rows == [{"标志": True}]

    def test_without_scale_is_unchanged(self):
        result = apply_field_mapping([{"volume": 12}], {"volume": FieldTransform(name="成交量", field_type="int")})
        assert result.rows == [{"成交量": 12}]

    def test_scale_rejects_non_numeric_declaration(self):
        with pytest.raises(ProviderError, match="scale 必须是数值"):
            FieldTransform(name="x", scale="100")  # type: ignore[arg-type]

    def test_normalize_field_mapping_parses_scale(self):
        mapping = normalize_field_mapping({"volume": {"name": "成交量", "field_type": "int", "scale": 100}})
        assert mapping["volume"] == FieldTransform(name="成交量", field_type="int", scale=100.0)

    def test_normalize_field_mapping_blank_scale(self):
        mapping = normalize_field_mapping({"volume": {"name": "成交量", "scale": ""}})
        assert mapping["volume"] == FieldTransform(name="成交量")

    def test_normalize_field_mapping_bool_scale_raises(self):
        with pytest.raises(ProviderError, match="scale 必须是数值"):
            normalize_field_mapping({"volume": {"name": "成交量", "scale": True}})

    def test_normalize_field_mapping_bad_scale_raises(self):
        with pytest.raises(ProviderError, match="scale 必须是数值"):
            normalize_field_mapping({"volume": {"name": "成交量", "scale": "abc"}})


class TestPayloadParsing:
    def test_request_spec_accepts_rows_array(self):
        spec = request_spec_from_payload(
            {
                "url_template": "https://api.example.com/v1",
                "record_mode": "rows_array",
                "record_layout": {"日期": 0},
                "row_defaults": {"来源": "腾讯"},
            }
        )
        assert spec.record_mode == "rows_array"
        assert spec.row_defaults == {"来源": "腾讯"}

    def test_request_spec_rejects_unknown_mode(self):
        with pytest.raises(ValueError, match="record_mode 非法"):
            request_spec_from_payload({"url_template": "https://api.example.com/v1", "record_mode": "matrix"})

    def test_field_mapping_payload_parses_scale(self):
        mapping = field_mapping_from_payload({"volume": {"name": "成交量", "field_type": "int", "scale": 100}})
        assert mapping["volume"] == FieldTransform(name="成交量", field_type="int", scale=100.0)

    def test_field_mapping_payload_blank_scale(self):
        mapping = field_mapping_from_payload({"volume": {"name": "成交量", "scale": None}})
        assert mapping["volume"] == FieldTransform(name="成交量")

    def test_field_mapping_payload_bool_scale_raises(self):
        with pytest.raises(ValueError, match="scale 必须是数值"):
            field_mapping_from_payload({"volume": {"name": "成交量", "scale": True}})

    def test_field_mapping_payload_bad_scale_raises(self):
        with pytest.raises(ValueError, match="scale 必须是数值"):
            field_mapping_from_payload({"volume": {"name": "成交量", "scale": "abc"}})
