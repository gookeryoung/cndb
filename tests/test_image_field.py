"""ImageFieldType.validate_value 单测 —— 图片元数据列表校验与序列化."""

from __future__ import annotations

import json

import pytest

from cndb.plugins.tables.field_types import ImageFieldType, is_image_meta


@pytest.fixture
def img() -> ImageFieldType:
    return ImageFieldType()


class TestImageMeta:
    def test_mime_image_prefix(self):
        assert is_image_meta({"mime_type": "image/png", "filename": "x"})
        assert is_image_meta({"mime_type": "image/jpeg"})

    def test_filename_extension_fallback(self):
        assert is_image_meta({"filename": "photo.JPG", "mime_type": ""})
        assert is_image_meta({"filename": "icon.svg"})

    def test_non_image_rejected(self):
        assert not is_image_meta({"mime_type": "application/pdf", "filename": "a.pdf"})
        assert not is_image_meta({"filename": "doc.txt"})
        assert not is_image_meta({"filename": "noext"})


class TestImageValidateValue:
    def test_none_returns_none(self, img: ImageFieldType):
        assert img.validate_value(None, {}) is None
        assert img.validate_value("", {}) is None

    def test_empty_list_serialized(self, img: ImageFieldType):
        assert img.validate_value([], {}) == "[]"

    def test_valid_list_serialized(self, img: ImageFieldType):
        value = [{"file_key": "abc.png", "filename": "abc.png", "mime_type": "image/png", "size": 100}]
        result = img.validate_value(value, {})
        parsed = json.loads(result or "[]")
        assert parsed[0]["file_key"] == "abc.png"
        assert parsed[0]["mime_type"] == "image/png"
        assert parsed[0]["size"] == 100

    def test_filename_ext_without_mime_accepted(self, img: ImageFieldType):
        result = img.validate_value([{"file_key": "a.jpeg", "filename": "a.jpeg"}], {})
        assert result is not None
        assert "a.jpeg" in result

    def test_non_image_item_rejected(self, img: ImageFieldType):
        with pytest.raises(ValueError, match="不是图片"):
            img.validate_value([{"file_key": "a.pdf", "filename": "a.pdf", "mime_type": "application/pdf"}], {})

    def test_json_string_passthrough(self, img: ImageFieldType):
        s = '[{"file_key": "x.png", "filename": "y.png", "mime_type": "image/png"}]'
        assert img.validate_value(s, {}) == s

    def test_json_string_non_list_rejected(self, img: ImageFieldType):
        with pytest.raises(ValueError, match="不是合法的 JSON 数组"):
            img.validate_value('{"not": "a list"}', {})

    def test_json_string_non_image_rejected(self, img: ImageFieldType):
        s = '[{"file_key": "a.pdf", "filename": "a.pdf", "mime_type": "application/pdf"}]'
        with pytest.raises(ValueError, match="不是图片元数据"):
            img.validate_value(s, {})

    def test_non_list_rejected(self, img: ImageFieldType):
        with pytest.raises(ValueError, match="必须是图片元数据列表"):
            img.validate_value(123, {})

    def test_list_item_not_dict_rejected(self, img: ImageFieldType):
        with pytest.raises(ValueError, match="必须是 dict"):
            img.validate_value(["string"], {})

    def test_missing_file_key_rejected(self, img: ImageFieldType):
        with pytest.raises(ValueError, match="缺少 file_key"):
            img.validate_value([{"filename": "a.png"}], {})

    def test_missing_filename_rejected(self, img: ImageFieldType):
        with pytest.raises(ValueError, match="缺少 filename"):
            img.validate_value([{"file_key": "a.png"}], {})

    def test_optional_fields_preserved(self, img: ImageFieldType):
        value = [
            {
                "file_key": "a.png",
                "filename": "b.png",
                "size": "99",
                "mime_type": "image/png",
                "created_at": "2026-01-01",
            }
        ]
        parsed = json.loads(img.validate_value(value, {}) or "[]")
        assert parsed[0]["size"] == 99
        assert parsed[0]["created_at"] == "2026-01-01"

    def test_none_optional_fields_skipped(self, img: ImageFieldType):
        parsed = json.loads(img.validate_value([{"file_key": "a.png", "filename": "b.png", "size": None}], {}) or "[]")
        assert "size" not in parsed[0]


class TestImageFieldTypeMeta:
    def test_registered_in_default_registry(self):
        from cndb.plugins.tables.field_types import default_registry

        ft = default_registry.get("image")
        assert ft is not None
        assert ft.label == "图片"
        assert ft.has_physical_column is True

    def test_column_is_text(self):
        from sqlalchemy import Text

        ft = ImageFieldType()
        col = ft.make_column("c_img")
        assert isinstance(col.type, Text)

    def test_config_defaults(self):
        from cndb.plugins.tables.field_types import ImageFieldConfig

        cfg = ImageFieldConfig()
        assert cfg.max_size_mb == 10
        assert cfg.multiple is True
        assert cfg.allowed_mime_types == []
