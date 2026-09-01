"""数据表与字段元数据模型：用户自定义结构的单一事实来源."""

from __future__ import annotations

import uuid
from typing import Any

from django.db import models

from cndb.tables.field_types import get_field_type


def generate_db_table_name() -> str:
    """生成物理表名：table_ 前缀 + 12 位十六进制随机串，确保不与用户输入相关."""
    return f"table_{uuid.uuid4().hex[:12]}"


def generate_db_column_name() -> str:
    """生成物理列名：field_ 前缀 + 12 位十六进制随机串，确保不与用户输入相关."""
    return f"field_{uuid.uuid4().hex[:12]}"


class DataTable(models.Model):
    """用户自定义表的元数据，物理表由 DDL 引擎（P2）按 db_table_name 创建."""

    workspace = models.ForeignKey(
        "workspaces.Workspace",
        on_delete=models.CASCADE,
        related_name="tables",
        verbose_name="所属工作区",
    )
    name = models.CharField("表名", max_length=255)
    db_table_name = models.CharField("物理表名", max_length=63, unique=True, editable=False)
    order = models.IntegerField("排序", default=0)
    trashed = models.BooleanField("回收站", default=False)
    created_on = models.DateTimeField("创建时间", auto_now_add=True)
    updated_on = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "数据表"
        verbose_name_plural = "数据表"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        """返回"表名 (物理表名)"便于后台展示."""
        return f"{self.name} ({self.db_table_name})"

    def active_fields(self) -> list[DataField]:
        """返回未进回收站的字段（按展示顺序），行读写与查询编译共用."""
        return list(self.fields.filter(trashed=False).order_by("order", "id"))

    def save(self, *args: Any, **kwargs: Any) -> None:
        """首次保存时生成物理表名，杜绝用户可控标识符进入 DDL."""
        if not self.db_table_name:
            self.db_table_name = generate_db_table_name()  # type: ignore[bad-assignment]
        super().save(*args, **kwargs)


class DataField(models.Model):
    """用户自定义字段的元数据，config 由字段类型系统解释与校验."""

    table = models.ForeignKey(
        DataTable,
        on_delete=models.CASCADE,
        related_name="fields",
        verbose_name="所属数据表",
    )
    name = models.CharField("字段名", max_length=255)
    field_type = models.CharField("字段类型", max_length=32)
    db_column_name = models.CharField("物理列名", max_length=63, default=generate_db_column_name, editable=False)
    config = models.JSONField("字段配置", default=dict, blank=True)
    required = models.BooleanField("必填", default=False)
    order = models.IntegerField("排序", default=0)
    trashed = models.BooleanField("回收站", default=False)
    created_on = models.DateTimeField("创建时间", auto_now_add=True)
    updated_on = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "数据字段"
        verbose_name_plural = "数据字段"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=("table", "name"), name="uniq_table_field_name"),
        ]

    def __str__(self) -> str:
        """返回"字段名: 类型"便于后台展示."""
        return f"{self.name}: {self.field_type}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """保存前经字段类型系统校验并归一化 config，保证元数据完整性."""
        field_type = get_field_type(self.field_type)  # type: ignore[bad-argument-type]
        self.config = field_type.validate_config(self.config)  # type: ignore[bad-assignment, bad-argument-type]
        super().save(*args, **kwargs)


class DataView(models.Model):
    """数据表视图：保存筛选/排序/字段显隐等展示规则，规则结构由 view_rules 校验."""

    class ViewType(models.TextChoices):
        """视图形态：P3 交付 Grid 行查询，其余形态先存储配置."""

        GRID = "grid", "表格"
        KANBAN = "kanban", "看板"
        CALENDAR = "calendar", "日历"
        GALLERY = "gallery", "画册"
        FORM = "form", "表单"

    class FilterType(models.TextChoices):
        """多条件组合方式."""

        AND = "AND", "全部满足"
        OR = "OR", "任一满足"

    table = models.ForeignKey(
        DataTable,
        on_delete=models.CASCADE,
        related_name="views",
        verbose_name="所属数据表",
    )
    name = models.CharField("视图名", max_length=255)
    view_type = models.CharField("视图形态", max_length=32, choices=ViewType.choices, default=ViewType.GRID)
    filter_type = models.CharField("条件组合", max_length=3, choices=FilterType.choices, default=FilterType.AND)
    filters = models.JSONField("筛选规则", default=list, blank=True)
    sortings = models.JSONField("排序规则", default=list, blank=True)
    field_options = models.JSONField("字段选项", default=dict, blank=True)
    public = models.BooleanField("公开共享", default=False)
    order = models.IntegerField("排序", default=0)
    created_on = models.DateTimeField("创建时间", auto_now_add=True)
    updated_on = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "数据视图"
        verbose_name_plural = "数据视图"
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=("table", "name"), name="uniq_table_view_name"),
        ]

    def __str__(self) -> str:
        """返回"视图名: 形态"便于后台展示."""
        return f"{self.name}: {self.view_type}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """保存前经视图规则校验并归一化筛选/排序/字段选项结构."""
        from cndb.tables.view_rules import ViewRules, normalize_view

        normalized = normalize_view(
            self.table,  # type: ignore[bad-argument-type]
            ViewRules(
                view_type=str(self.view_type),
                filter_type=str(self.filter_type),
                filters=self.filters,
                sortings=self.sortings,
                field_options=self.field_options,
            ),
        )
        self.filters = normalized["filters"]
        self.sortings = normalized["sortings"]
        self.field_options = normalized["field_options"]
        super().save(*args, **kwargs)


class TablePermission(models.Model):
    """表级访问控制：角色覆盖、行级过滤与字段级隐藏，规则由 permission_rules 校验."""

    table = models.OneToOneField(
        DataTable,
        on_delete=models.CASCADE,
        related_name="permission",
        verbose_name="所属数据表",
    )
    read_role = models.CharField("读取最低角色", max_length=16, blank=True, default="")
    edit_records_role = models.CharField("行数据编辑最低角色", max_length=16, blank=True, default="")
    edit_views_role = models.CharField("视图编辑最低角色", max_length=16, blank=True, default="")
    edit_schema_role = models.CharField("结构编辑最低角色", max_length=16, blank=True, default="")
    hidden_fields = models.JSONField("字段级隐藏", default=dict, blank=True)
    row_filters = models.JSONField("行级过滤规则", default=list, blank=True)
    row_filter_type = models.CharField("行级条件组合", max_length=3, default="AND")
    created_on = models.DateTimeField("创建时间", auto_now_add=True)
    updated_on = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "表级权限"
        verbose_name_plural = "表级权限"

    def __str__(self) -> str:
        """返回"表权限: 表名"便于后台展示."""
        return f"表权限: {self.table.name}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """保存前经 permission_rules 校验并归一化行级规则与字段隐藏结构."""
        from cndb.tables.permission_rules import PermissionRules, normalize_permission

        normalized = normalize_permission(
            self.table,  # type: ignore[bad-argument-type]
            PermissionRules(
                read_role=str(self.read_role),
                edit_records_role=str(self.edit_records_role),
                edit_views_role=str(self.edit_views_role),
                edit_schema_role=str(self.edit_schema_role),
                hidden_fields=self.hidden_fields,
                row_filters=self.row_filters,
                row_filter_type=str(self.row_filter_type),
            ),
        )
        self.read_role = normalized["read_role"]
        self.edit_records_role = normalized["edit_records_role"]
        self.edit_views_role = normalized["edit_views_role"]
        self.edit_schema_role = normalized["edit_schema_role"]
        self.hidden_fields = normalized["hidden_fields"]
        self.row_filters = normalized["row_filters"]
        self.row_filter_type = normalized["row_filter_type"]
        super().save(*args, **kwargs)
