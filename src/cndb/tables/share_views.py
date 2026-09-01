"""共享视图公开端点：匿名按视图规则只读行数据.

与公开表单同理，公开端点不走任何认证——
SessionAuthentication 对携带平台会话 cookie 的请求会强制 CSRF 校验，
共享视图的访客须与平台会话完全解耦。
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cndb.tables import query, records
from cndb.tables.models import DataView
from cndb.tables.record_views import _page_url, _parse_paging


def _public_view(slug: str) -> DataView:
    """按 slug 取公开共享的 grid 视图：非 grid/未共享一律 404，不泄露存在性."""
    return get_object_or_404(
        DataView.objects.select_related("table"),
        slug=slug,
        view_type=DataView.ViewType.GRID,
        public=True,
    )


class PublicViewRowsView(APIView):
    """共享视图行数据：匿名按视图规则（筛选/排序/分页）只读."""

    permission_classes = [permissions.AllowAny]
    authentication_classes: list[type[object]] = []

    def get(self, request: Request, slug: str) -> Response:
        """读取视图行：视图 filters/sortings 生效，page/page_size 分页."""
        view = _public_view(slug)
        table = view.table
        try:
            where, params = query.compile_filters(table, view.filters, str(view.filter_type))  # type: ignore[bad-argument-type]
            order = query.compile_sortings(table, view.sortings)  # type: ignore[bad-argument-type]
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
                "field_options": view.field_options or {},
            }
        )
