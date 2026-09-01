"""数据表序列化器：表与字段的读写."""

from __future__ import annotations

from rest_framework import serializers

from cndb.tables.models import DataField, DataTable


class DataFieldSerializer(serializers.ModelSerializer):
    """字段信息：db_column_name 由系统生成，只读对外暴露."""

    class Meta:
        model = DataField
        fields = (
            "id",
            "name",
            "field_type",
            "db_column_name",
            "config",
            "required",
            "order",
            "trashed",
            "created_on",
            "updated_on",
        )
        read_only_fields = ("id", "db_column_name", "created_on", "updated_on")


class DataTableSerializer(serializers.ModelSerializer):
    """数据表信息：内嵌全部字段元数据（fields 与 DRF 基类成员同名，运行时由元类正确处理）."""

    fields = DataFieldSerializer(many=True, read_only=True)  # type: ignore[bad-override]

    class Meta:
        model = DataTable
        fields = ("id", "name", "order", "trashed", "fields", "created_on", "updated_on")
        read_only_fields = ("id", "created_on", "updated_on")


class FieldDefSerializer(serializers.Serializer):
    """建表时字段定义：结构与 DataField 写入字段对应，由服务层落库."""

    name = serializers.CharField(max_length=255, label="字段名")
    field_type = serializers.CharField(max_length=32, label="字段类型")
    config = serializers.JSONField(default=dict, label="字段配置")
    required = serializers.BooleanField(default=False, label="必填")
    order = serializers.IntegerField(default=0, label="排序")


class DataTableCreateSerializer(serializers.Serializer):
    """建表请求：表名与初始字段定义列表（fields 与 DRF 基类成员同名，运行时由元类正确处理）."""

    name = serializers.CharField(max_length=255, label="表名")
    fields = FieldDefSerializer(many=True, label="字段定义")  # type: ignore[bad-override]
