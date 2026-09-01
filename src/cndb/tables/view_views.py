"""视图 API：视图规则的增删改查与按视图规则读取行数据."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cndb.tables import query, records
from cndb.tables.aggregations import InvalidAggregationError, fetch_aggregations, parse_aggregations
from cndb.tables.models import DataView
from cndb.tables.record_views import _page_url, _parse_paging
from cndb.tables.serializers import DataViewSerializer
from cndb.tables.view_rules import InvalidViewError
from cndb.tables.views import TableMixin


class ViewListCreateView(TableMixin, generics.ListCreateAPIView):
    """视图列表与建视图，写操作要求 EDITOR 及以上角色."""

    serializer_class = DataViewSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        """当前数据表的全部视图."""
        return DataView.objects.filter(table=self.get_table())

    def create(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        """建视图：规则结构非法返回 400."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            view = DataView.objects.create(table=self.get_table(), **serializer.validated_data)
        except InvalidViewError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(DataViewSerializer(view).data, status=201)


class ViewDetailView(TableMixin, generics.RetrieveUpdateDestroyAPIView):
    """视图详情：改规则与删视图，写操作要求 EDITOR 及以上角色."""

    serializer_class = DataViewSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        """当前数据表的视图."""
        return DataView.objects.filter(table=self.get_table())

    def update(self, request: Request, *_args: object, **kwargs: object) -> Response:
        """改视图：名称/规则/公开性，规则结构非法返回 400."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        partial = kwargs.pop("partial", False)
        view = self.get_object()
        serializer = self.get_serializer(view, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except InvalidViewError as exc:
            return Response({"detail": str(exc)}, status=400)
        view.refresh_from_db()
        return Response(DataViewSerializer(view).data)

    def destroy(self, _request: Request, *_args: object, **_kwargs: object) -> Response:
        """删视图：纯元数据删除."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        self.get_object().delete()
        return Response(status=204)


class ViewRowsView(TableMixin, APIView):
    """按视图规则读取行：应用筛选/排序 + 分页，附视图字段选项供前端渲染."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request, **_kwargs: object) -> Response:
        """读取视图行：page/page_size 分页，规则编译失败返回 400."""
        table = self.get_table()
        view = get_object_or_404(DataView, pk=self.kwargs["pk"], table=table)
        try:
            where, params = query.compile_filters(table, view.filters, str(view.filter_type))
            order = query.compile_sortings(table, view.sortings)
            page, page_size = _parse_paging(request.query_params)
        except query.InvalidQueryError as exc:
            return Response({"detail": str(exc)}, status=400)
        spec = query.RowQuery(where=where, params=params, order=order, limit=page_size, offset=(page - 1) * page_size)
        total = records.count_rows(table, spec)
        rows = records.fetch_rows(table, spec)
        next_url = _page_url(request, page + 1) if page * page_size < total else None
        previous_url = _page_url(request, page - 1) if page > 1 else None
        return Response(
            {
                "count": total,
                "next": next_url,
                "previous": previous_url,
                "results": rows,
                "field_options": view.field_options,
            }
        )


class ViewAggregationsView(TableMixin, APIView):
    """按视图规则聚合统计：group_by 分组 + agg__<字段>=<函数> 聚合."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request, **_kwargs: object) -> Response:
        """聚合查询：group_by 分组字段（可空），agg__<字段>=count/sum/avg/min/max."""
        table = self.get_table()
        view = get_object_or_404(DataView, pk=self.kwargs["pk"], table=table)
        try:
            where, params = query.compile_filters(table, view.filters, str(view.filter_type))
            agg = parse_aggregations(table, request.query_params)
        except (query.InvalidQueryError, InvalidAggregationError) as exc:
            return Response({"detail": str(exc)}, status=400)
        spec = query.RowQuery(where=where, params=params)
        return Response(fetch_aggregations(table, spec, agg))
