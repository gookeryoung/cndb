"""AttachmentFieldType.validate_value 单测 —— 覆盖 30 个 statement miss."""

from __future__ import annotations

import pytest

from cndb.plugins.tables.field_types import AttachmentFieldType


@pytest.fixture
def att() -> AttachmentFieldType:
    return AttachmentFieldType()


class TestAttachmentValidateValue:
    def test_none_returns_none(self, att: AttachmentFieldType):
        assert att.validate_value(None, {}) is None
        assert att.validate_value("", {}) is None

    def test_empty_list_returns_none(self, att: AttachmentFieldType):
        # [] 走 list 分支但 result 为空 → 最终 json.dumps([]) 不是 None
        result = att.validate_value([], {})
        assert result == "[]"

    def test_valid_list_serialized(self, att: AttachmentFieldType):
        value = [
            {"file_key": "abc.txt", "filename": "abc.txt", "size": 100},
            {"file_key": "def.png", "filename": "def.png", "mime_type": "image/png"},
        ]
        result = att.validate_value(value, {})
        assert result is not None
        assert "abc.txt" in result
        assert "def.png" in result

    def test_json_string_passthrough(self, att: AttachmentFieldType):
        s = '[{"file_key": "x", "filename": "y"}]'
        result = att.validate_value(s, {})
        assert result == s

    def test_json_string_not_list_raises(self, att: AttachmentFieldType):
        with pytest.raises(ValueError, match="不是合法的 JSON 数组"):
            att.validate_value('{"not": "a list"}', {})

    def test_json_invalid_raises(self, att: AttachmentFieldType):
        with pytest.raises(ValueError, match="不是合法的 JSON 数组"):
            att.validate_value("not-json", {})

    def test_non_list_raises(self, att: AttachmentFieldType):
        # 非 list / 非 str → 走最后 raise
        with pytest.raises(ValueError, match=r"附件值不是合法的 JSON 数组|必须是附件元数据列表"):
            att.validate_value(123, {})

    def test_list_item_not_dict_raises(self, att: AttachmentFieldType):
        with pytest.raises(ValueError, match="第 0 项必须是 dict"):
            att.validate_value(["string"], {})

    def test_missing_file_key_raises(self, att: AttachmentFieldType):
        with pytest.raises(ValueError, match="缺少 file_key"):
            att.validate_value([{"filename": "x"}], {})

    def test_missing_filename_raises(self, att: AttachmentFieldType):
        with pytest.raises(ValueError, match="缺少 filename"):
            att.validate_value([{"file_key": "x"}], {})

    def test_optional_fields_preserved(self, att: AttachmentFieldType):
        value = [
            {
                "file_key": "a",
                "filename": "b",
                "size": "99",
                "mime_type": "text/plain",
                "created_at": "2024-01-01",
            }
        ]
        result = att.validate_value(value, {})
        import json

        parsed = json.loads(result or "[]")
        assert parsed[0]["size"] == 99  # int 转换
        assert parsed[0]["mime_type"] == "text/plain"
        assert parsed[0]["created_at"] == "2024-01-01"

    def test_none_optional_fields_skipped(self, att: AttachmentFieldType):
        value = [{"file_key": "a", "filename": "b", "size": None}]
        result = att.validate_value(value, {})
        import json

        parsed = json.loads(result or "[]")
        assert "size" not in parsed[0]
