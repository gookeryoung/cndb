"""发现物转 Issue 的文案映射单测（ADR 0076 P2 / D15）."""

from __future__ import annotations

import json

from cndb.plugins.pipeline.models import PipelineFinding
from cndb.plugins.pipeline.services.issue_bridge import (
    TITLE_MAX_LENGTH,
    _issue_description,
    _issue_title,
)


def _finding(**overrides) -> PipelineFinding:
    """构造内存态发现物（不落库，仅用于文案映射断言）."""
    data = {
        "check": "table/null-rate",
        "severity": "warn",
        "target_type": "table",
        "target_id": 1,
        "locator": {"field": "姓名", "row_id": 7},
        "message": "空值率超阈值",
        "detail": {},
    }
    data.update(overrides)
    finding = PipelineFinding(**data)
    return finding


class TestTitle:
    def test_prefixes_severity(self):
        assert _issue_title(_finding()) == "[warn] 空值率超阈值"

    def test_falls_back_to_check_name(self):
        assert _issue_title(_finding(message="  ")) == "[warn] table/null-rate 发现问题"

    def test_without_severity(self):
        assert _issue_title(_finding(severity="")) == "空值率超阈值"

    def test_truncated_to_issue_title_limit(self):
        title = _issue_title(_finding(message="超" * 400))
        assert len(title) == TITLE_MAX_LENGTH


class TestDescription:
    def test_includes_locator(self):
        text = _issue_description(_finding())
        assert text.startswith("流水线检查：table/null-rate")
        assert "严重度：warn" in text
        assert "空值率超阈值" in text
        assert "定位：" + json.dumps({"field": "姓名", "row_id": 7}, ensure_ascii=False, sort_keys=True) in text

    def test_omits_empty_message_and_locator(self):
        text = _issue_description(_finding(message="", locator={}))
        assert text == "流水线检查：table/null-rate\n严重度：warn"
