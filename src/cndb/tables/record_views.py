"""行数据 API 视图：行的增删改查，写操作要求 EDITOR 及以上角色."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cndb.tables import query, records
from cndb.tables.models import DataTable
from cndb.tables.views import TableMixin

# 分页默认值与上限
_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200
# 批量操作单批行数上限
_MAX_BATCH_SIZE = 200


def _parse_paging(params: Mapping[str, Any]) -> tuple[int, int]:
    """解析 page/page_size 查询参数，非法值抛 query.InvalidQueryError."""
    try:
        page = int(params.get("page", 1))
        page_size = int(params.get("page_size", _DEFAULT_PAGE_SIZE))
    except (TypeError, ValueError) as exc:
        raise query.InvalidQueryError("page/page_size 必须是整数") from exc
    if page < 1:
        raise query.InvalidQueryError("page 不能小于 1")
    if not 1 <= page_size <= _MAX_PAGE_SIZE:
        raise query.InvalidQueryError(f"page_size 须在 1 到 {_MAX_PAGE_SIZE} 之间")
    return page, page_size


def _page_url(request: Request, page: int) -> str:
    """构造指向指定页码的绝对地址."""
    parts = urlsplit(request.build_absolute_uri())
    query_string = dict(parse_qsl(parts.query, keep_blank_values=True))
    query_string["page"] = str(page)
    return str(urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query_string), parts.fragment)))


class RecordListCreateView(TableMixin, APIView):
    """行列表与新增行：列表支持过滤/排序/分页查询参数."""

    permission_classes = [permissions.IsAuthenticated]

    def get(self, request: Request, **_kwargs: object) -> Response:
        """读取行：filter__<字段>__<操作符> 过滤、order_by 排序、page/page_size 分页."""
        table = self.get_table()
        try:
            where, params = query.parse_filters(table, request.query_params)
            order = query.parse_order_by(table, str(request.query_params.get("order_by") or ""))
            page, page_size = _parse_paging(request.query_params)
        except query.InvalidQueryError as exc:
            return Response({"detail": str(exc)}, status=400)
        spec = query.RowQuery(where=where, params=params, order=order, limit=page_size, offset=(page - 1) * page_size)
        total = records.count_rows(table, spec)
        rows = records.fetch_rows(table, spec)
        next_url = _page_url(request, page + 1) if page * page_size < total else None
        previous_url = _page_url(request, page - 1) if page > 1 else None
        return Response({"count": total, "next": next_url, "previous": previous_url, "results": rows})

    def post(self, request: Request, **_kwargs: object) -> Response:
        """新增一行：请求体须为对象且逐字段校验，非法返回 400."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        table = self.get_table()
        if not isinstance(request.data, Mapping):
            return Response({"detail": "请求体必须是对象"}, status=400)
        try:
            cleaned = records.clean_row(table, request.data)
        except records.InvalidRowError as exc:
            return Response({"detail": str(exc)}, status=400)
        row_id = records.insert_row(table, cleaned)
        row = records.fetch_row(table, row_id)
        assert row is not None, "刚插入的行必然可读"
        return Response(row, status=201)


class RecordDetailView(TableMixin, APIView):
    """单行详情：读取/局部更新/删除."""

    permission_classes = [permissions.IsAuthenticated]

    def _get_row(self, table: DataTable, row_id: int) -> dict[str, Any] | None:
        """读取单行，不存在返回 None."""
        return records.fetch_row(table, row_id)

    def get(self, _request: Request, **_kwargs: object) -> Response:
        """读取单行."""
        table = self.get_table()
        row = self._get_row(table, int(self.kwargs["row_id"]))
        if row is None:
            return Response({"detail": "行不存在"}, status=404)
        return Response(row)

    def patch(self, request: Request, **_kwargs: object) -> Response:
        """局部更新行：数据非法返回 400，行不存在返回 404."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        table = self.get_table()
        row_id = int(self.kwargs["row_id"])
        if not isinstance(request.data, Mapping):
            return Response({"detail": "请求体必须是对象"}, status=400)
        try:
            cleaned = records.clean_row(table, request.data, partial=True)
        except records.InvalidRowError as exc:
            return Response({"detail": str(exc)}, status=400)
        if not records.update_row(table, row_id, cleaned):
            return Response({"detail": "行不存在"}, status=404)
        row = self._get_row(table, row_id)
        assert row is not None, "刚更新的行必然可读"
        return Response(row)

    def delete(self, _request: Request, **_kwargs: object) -> Response:
        """删除行."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        table = self.get_table()
        if not records.delete_row(table, int(self.kwargs["row_id"])):
            return Response({"detail": "行不存在"}, status=404)
        return Response(status=204)


def _is_int(value: object) -> bool:
    """判断是否为真整数（排除 bool 子类）."""
    return isinstance(value, int) and not isinstance(value, bool)


def _parse_bulk_updates(table: DataTable, items: list[Any]) -> tuple[dict[int, dict[str, Any]], str | None]:
    """解析批量更新请求体为 {id: 清洗后行数据}，非法时返回错误信息."""
    updates: dict[int, dict[str, Any]] = {}
    try:
        for item in items:
            if not isinstance(item, Mapping) or not _is_int(item.get("id")):
                return {}, "每个元素必须是对象且包含整数 id"
            row_id = item["id"]
            if row_id in updates:
                return {}, f"存在重复的行 id: {row_id}"
            data = {key: value for key, value in item.items() if key != "id"}
            updates[row_id] = records.clean_row(table, data, partial=True)
    except records.InvalidRowError as exc:
        return {}, str(exc)
    return updates, None


class RecordBulkView(TableMixin, APIView):
    """行批量操作：批量创建/更新/删除，要求 EDITOR 及以上角色."""

    permission_classes = [permissions.IsAuthenticated]

    def _check_items(self, data: Any) -> list[Any] | None:
        """校验请求体为非空且不超上限的数组，非法返回 None."""
        if not isinstance(data, list) or not data:
            return None
        if len(data) > _MAX_BATCH_SIZE:
            return None
        return data

    def post(self, request: Request, **_kwargs: object) -> Response:
        """批量创建：请求体为行对象数组，返回创建的行（按提交顺序）."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        table = self.get_table()
        items = self._check_items(request.data)
        if items is None:
            return Response({"detail": f"请求体必须是非空数组，一次最多 {_MAX_BATCH_SIZE} 行"}, status=400)
        try:
            cleaned_rows = [records.clean_row(table, item) for item in items]
        except records.InvalidRowError as exc:
            return Response({"detail": str(exc)}, status=400)
        row_ids = records.insert_rows(table, cleaned_rows)
        return Response(records.fetch_rows_by_ids(table, row_ids), status=201)

    def patch(self, request: Request, **_kwargs: object) -> Response:
        """批量局部更新：请求体为 [{"id": 1, ...字段}, ...]，返回更新后的行."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        table = self.get_table()
        items = self._check_items(request.data)
        if items is None:
            return Response({"detail": f"请求体必须是非空数组，一次最多 {_MAX_BATCH_SIZE} 行"}, status=400)
        updates, error = _parse_bulk_updates(table, items)
        if error is not None:
            return Response({"detail": error}, status=400)
        if len(records.fetch_rows_by_ids(table, list(updates))) != len(updates):
            return Response({"detail": "部分行不存在"}, status=404)
        records.update_rows(table, updates)
        return Response(records.fetch_rows_by_ids(table, list(updates)))

    def delete(self, request: Request, **_kwargs: object) -> Response:
        """批量删除：请求体为 {"ids": [1, 2, ...]}，返回删除行数."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        table = self.get_table()
        data = request.data
        if not isinstance(data, Mapping):
            return Response({"detail": "请求体必须是对象"}, status=400)
        ids = data.get("ids")
        if not isinstance(ids, list) or not ids or not all(_is_int(value) for value in ids):
            return Response({"detail": f"ids 必须是非空整数数组，一次最多 {_MAX_BATCH_SIZE} 行"}, status=400)
        if len(ids) > _MAX_BATCH_SIZE:
            return Response({"detail": f"一次最多删除 {_MAX_BATCH_SIZE} 行"}, status=400)
        deleted = records.delete_rows(table, ids)
        return Response({"deleted": deleted})
