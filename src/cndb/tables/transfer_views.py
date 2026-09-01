"""导入导出视图：表数据全量导出（CSV/JSON）与批量导入（CSV/JSON）."""

from __future__ import annotations

from operator import itemgetter

from django.http import HttpResponse
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cndb.tables import query, records, transfer
from cndb.tables.access import TableAction, hidden_field_names, row_scope
from cndb.tables.models import DataTable
from cndb.tables.views import TableMixin


def _visible_field_names(table: DataTable, hidden: set[str]) -> list[str]:
    """导出字段顺序：按字段展示顺序剔除当前角色不可见字段."""
    return [str(field.name) for field in table.active_fields() if str(field.name) not in hidden]


class ExportView(TableMixin, APIView):
    """全量导出表数据：format=csv（默认）或 json，应用行级范围与字段隐藏."""

    def get(self, request: Request, **_kwargs: object) -> Response | HttpResponse:
        """导出当前用户可见的行与字段."""
        table = self.get_table()
        hidden = hidden_field_names(request.user, table)
        field_names = _visible_field_names(table, hidden)
        spec = query.merge_where(query.RowQuery(), row_scope(request.user, table))
        rows = records.fetch_rows(table, spec)
        if request.query_params.get("format", "csv") == "json":
            return Response(transfer.export_json(rows, field_names))
        content = "\ufeff" + transfer.export_csv(rows, field_names)
        response = HttpResponse(content, content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{table.name}.csv"'
        return response


class ImportView(TableMixin, APIView):
    """批量导入行数据：multipart 文件（CSV）或 JSON 数组，要求行编辑权限."""

    def post(self, request: Request, **_kwargs: object) -> Response:
        """导入：仅可见字段可写，错误行跳过并报告，成功行批量落库."""
        table = self.get_table()
        denied = self.require_table_action(TableAction.EDIT_RECORDS)
        if denied is not None:
            return denied
        allowed = set(_visible_field_names(table, hidden_field_names(request.user, table)))
        parse_errors: list[dict[str, object]] = []
        try:
            if "file" in request.FILES:  # type: ignore[not-iterable]
                text = request.FILES["file"].read().decode("utf-8-sig")  # type: ignore[bad-specialization, not-a-type]
                parsed = transfer.parse_import_rows(table, text, allowed)
                parsed_rows, parse_errors = parsed.rows, parsed.errors
            else:
                parsed_rows = transfer.parse_json_import(table, request.data, allowed)
        except (transfer.InvalidImportError, UnicodeDecodeError) as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        result = transfer.import_rows(table, parsed_rows)
        errors = sorted([*parse_errors, *result.errors], key=itemgetter("row"))
        return Response({"created": result.created, "errors": errors})
