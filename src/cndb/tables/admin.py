"""数据表后台注册."""

from __future__ import annotations

from django.contrib import admin

from cndb.tables.models import DataField, DataTable


@admin.register(DataTable)
class DataTableAdmin(admin.ModelAdmin):
    """数据表后台."""

    list_display = ("id", "name", "workspace", "db_table_name", "trashed", "created_on")
    list_filter = ("trashed",)


@admin.register(DataField)
class DataFieldAdmin(admin.ModelAdmin):
    """数据字段后台."""

    list_display = ("id", "name", "table", "field_type", "required", "trashed", "order")
    list_filter = ("field_type", "required", "trashed")
