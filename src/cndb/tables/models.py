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
