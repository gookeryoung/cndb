"""SQL 方言公共辅助：标识符引用与当前时间表达式（DDL 与行数据共用）."""

from __future__ import annotations

from django.db import connection


def quote(name: object) -> str:
    """按当前数据库方言引用标识符（模型描述符取值运行时均为 str）."""
    return connection.ops.quote_name(str(name))


def now() -> str:
    """返回当前数据库的当前时间 SQL 表达式."""
    return "now()" if connection.vendor == "postgresql" else "current_timestamp"
