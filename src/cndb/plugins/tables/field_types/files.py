"""文件族字段类型 — 附件（JSON 数组存储于 Text 列）."""

from __future__ import annotations

from typing import Any, override

from pydantic import Field
from sqlalchemy import Text

from cndb.plugins.tables.field_types.base import FieldType, FieldTypeCategory, FieldTypeConfig


class AttachmentFieldConfig(FieldTypeConfig):
    """附件字段的字段级配置.

    Attributes:
        max_size_mb: 单个附件最大 MB 数，0 表示由后端全局限制.
        allowed_mime_types: 允许的 MIME 类型白名单；空列表表示不限制.
        multiple: 是否允许多文件.
    """

    max_size_mb: int = Field(default=10, ge=0, le=1024)
    allowed_mime_types: list[str] = Field(default_factory=list)
    multiple: bool = True


class AttachmentFieldType(FieldType):
    """附件字段类型 —— 存储上传后返回的元数据列表（JSON 数组 in Text 列）.

    存储模型：值是 JSON 数组，每项形如::

        {
            "file_key":      "uuid.ext",     # 上传接口返回的稳定存储键
            "filename":      "report.pdf",    # 原始文件名
            "size":          12345,           # 字节数
            "mime_type":     "application/pdf",
            "created_at":    "2026-09-12T..."
        }

    has_physical_column=True —— 源表上占一个 Text 列存 JSON.
    """

    name = "attachment"
    label = "附件"
    category = FieldTypeCategory.ADVANCED
    sqlalchemy_type = Text
    sqlalchemy_length = None
    config_schema = AttachmentFieldConfig
    has_physical_column = True

    @override
    def validate_value(self, value: Any, _config: dict[str, Any]) -> str | None:
        """校验附件列表并序列化为 JSON 字符串.

        入参可以是：
        - None / [] → 存空数组 JSON
        - list[dict] → 每项必须包含 file_key + filename，可选 size/mime_type
        """
        import json

        if value is None or value == "":
            return None
        if isinstance(value, str):
            # 后端反序列化路径：已经是 JSON 字符串，校验格式后原样返回
            try:
                parsed = json.loads(value)
                if not isinstance(parsed, list):
                    raise ValueError()
            except (json.JSONDecodeError, ValueError) as exc:
                raise ValueError(f"附件值不是合法的 JSON 数组: {value!r}") from exc
            return value
        if not isinstance(value, list):
            raise ValueError(f"attachment 字段必须是附件元数据列表，收到 {type(value)!r}")

        result: list[dict[str, Any]] = []
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                raise ValueError(f"附件列表第 {i} 项必须是 dict，收到 {type(item)!r}")
            if not item.get("file_key"):
                raise ValueError(f"附件列表第 {i} 项缺少 file_key")
            if not item.get("filename"):
                raise ValueError(f"附件列表第 {i} 项缺少 filename")
            entry: dict[str, Any] = {
                "file_key": str(item["file_key"]),
                "filename": str(item["filename"]),
            }
            if "size" in item and item["size"] is not None:
                entry["size"] = int(item["size"])
            if "mime_type" in item and item["mime_type"] is not None:
                entry["mime_type"] = str(item["mime_type"])
            if "created_at" in item and item["created_at"] is not None:
                entry["created_at"] = str(item["created_at"])
            result.append(entry)
        return json.dumps(result, ensure_ascii=False)
