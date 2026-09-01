"""看板/日历视图数据端点：视图规则之上的两种聚合读法.

看板：按单选字段分组返回桶行（空值行入未分组桶，每桶限量）；
日历：按日期字段做范围过滤返回行列表（start/end 均为 ISO 日期）。
两者均应用视图 filters/sortings、行级范围与字段隐藏，要求 READ 权限。
"""

from __future__ import annotations

from typing import Any

from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cndb.tables import query, records
from cndb.tables.access import hidden_field_names, row_scope
from cndb.tables.models import DataField, DataTable, DataView
from cndb.tables.views import TableMixin

# 看板每桶行数上限与默认值
_MAX_PER_GROUP = 200
_DEFAULT_PER_GROUP = 50


class InvalidBoardError(Exception):
    """看板/日历参数非法（分组字段类型不符、日期范围非法等）."""


def _view_spec(request: Request, table: DataTable, view: DataView, extra: list[tuple[str, str, Any]]) -> query.RowQuery:
    """编译视图规则与附加条件为行查询（附加条件以 AND 并入）."""
    try:
        where, params = query.compile_filters(table, view.filters, str(view.filter_type))  # type: ignore[bad-argument-type]
        order = query.compile_sortings(table, view.sortings)  # type: ignore[bad-argument-type]
        spec = query.RowQuery(where=where, params=params, order=order)
        for field_name, op, value in extra:
            clause, condition_params = query.compile_filters(
                table, [{"field": field_name, "op": op, "value": value}], "AND"
            )
            spec = query.merge_where(spec, query.RowQuery(where=clause, params=condition_params))
    except query.InvalidQueryError as exc:
        raise InvalidBoardError(str(exc)) from exc
    return query.merge_where(spec, row_scope(request.user, table))


def _strip_hidden(rows: list[dict[str, Any]], hidden: set[str]) -> list[dict[str, Any]]:
    """剔除当前角色不可见的字段键."""
    if not hidden:
        return rows
    return [{key: value for key, value in row.items() if key not in hidden} for row in rows]


def _field_by_name(table: DataTable, name: str, expected_type: str) -> DataField:
    """按名称取字段并校验类型（未回收字段，未知或类型不符抛 InvalidBoardError）."""
    for field in table.active_fields():
        if str(field.name) == name:
            if str(field.field_type) != expected_type:
                raise InvalidBoardError(f"字段 {name} 不是 {expected_type} 类型")
            return field
    raise InvalidBoardError(f"未知字段: {name}")


class ViewKanbanView(TableMixin, APIView):
    """看板读行：按 group_by 单选字段分桶，返回选项顺序的分组与未分组桶."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request, **_kwargs: object) -> Response:
        """看板数据：group_by=单选字段名，per_group=每桶行数（默认 50，上限 200）."""
        table = self.get_table()
        view = get_object_or_404(DataView, pk=self.kwargs["pk"], table=table)
        group_by = request.query_params.get("group_by")
        if not group_by:
            return Response({"detail": "group_by 参数必填"}, status=400)
        try:
            group_field = _field_by_name(table, str(group_by), "single_select")
            per_group = int(str(request.query_params.get("per_group", _DEFAULT_PER_GROUP)))
        except (InvalidBoardError, ValueError, TypeError) as exc:
            return Response({"detail": f"看板参数非法: {exc}"}, status=400)
        if not 1 <= per_group <= _MAX_PER_GROUP:
            return Response({"detail": f"per_group 须在 1 到 {_MAX_PER_GROUP} 之间"}, status=400)
        try:
            spec = _view_spec(request, table, view, [])
        except InvalidBoardError as exc:
            return Response({"detail": str(exc)}, status=400)
        rows = records.fetch_rows(table, spec)
        hidden = hidden_field_names(request.user, table)
        if group_field.name in hidden:
            return Response({"detail": "分组字段不可见"}, status=400)
        buckets: dict[str, list[dict[str, Any]]] = {choice: [] for choice in group_field.config.get("choices", [])}
        ungrouped: list[dict[str, Any]] = []
        for row in rows:
            value = row.get(str(group_field.name))
            if value in buckets:
                buckets[str(value)].append(row)
            else:
                ungrouped.append(row)
        groups = [
            {"value": choice, "count": len(bucket), "rows": _strip_hidden(bucket[:per_group], hidden)}
            for choice, bucket in buckets.items()
        ]
        return Response(
            {
                "groups": groups,
                "ungrouped": {"count": len(ungrouped), "rows": _strip_hidden(ungrouped[:per_group], hidden)},
            }
        )


class ViewCalendarView(TableMixin, APIView):
    """日历读行：按 date_field 日期字段过滤 start/end 范围，返回行列表."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request, **_kwargs: object) -> Response:
        """日历数据：date_field=date 类型字段名，start/end=ISO 日期（闭区间，均可选）."""
        table = self.get_table()
        view = get_object_or_404(DataView, pk=self.kwargs["pk"], table=table)
        date_field = request.query_params.get("date_field")
        if not date_field:
            return Response({"detail": "date_field 参数必填"}, status=400)
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        try:
            target = _field_by_name(table, str(date_field), "date")
            extra: list[tuple[str, str, Any]] = []
            if start is not None:
                extra.append((str(target.name), "gte", start))
            if end is not None:
                extra.append((str(target.name), "lte", end))
            spec = _view_spec(request, table, view, extra)
        except InvalidBoardError as exc:
            return Response({"detail": str(exc)}, status=400)
        hidden = hidden_field_names(request.user, table)
        if target.name in hidden:
            return Response({"detail": "日期字段不可见"}, status=400)
        rows = _strip_hidden(records.fetch_rows(table, spec), hidden)
        return Response({"date_field": str(target.name), "results": rows})
