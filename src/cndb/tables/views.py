"""数据表 API 视图：表与字段的结构管理，写操作要求 EDITOR 及以上角色."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions
from rest_framework.request import Request
from rest_framework.response import Response

from cndb.tables import services
from cndb.tables.field_types import FieldTypeError
from cndb.tables.models import DataField, DataTable
from cndb.tables.serializers import (
    DataFieldSerializer,
    DataTableCreateSerializer,
    DataTableSerializer,
    FieldDefSerializer,
)
from cndb.workspaces.models import Workspace, WorkspaceMember
from cndb.workspaces.permissions import get_member_role, has_role


class TableMixin:
    """表视图公共基类：解析 workspace_pk 并校验成员身份."""

    permission_classes = [permissions.IsAuthenticated]

    def get_workspace(self) -> Workspace:
        """获取路径中的工作区，非成员访问返回 404."""
        workspace = get_object_or_404(Workspace, pk=self.kwargs["workspace_pk"])
        if get_member_role(self.request.user, workspace) is None:
            self.permission_denied(self.request)
        return workspace  # type: ignore[return-value]

    def get_table(self) -> DataTable:
        """获取路径中的数据表，校验其属于当前工作区."""
        return get_object_or_404(DataTable, pk=self.kwargs["table_pk"], workspace=self.get_workspace())

    def require_editor(self) -> Response | None:
        """结构写操作要求 EDITOR 及以上角色，不满足返回 403 响应."""
        if not has_role(self.request.user, self.get_workspace(), WorkspaceMember.Role.EDITOR):
            return Response({"detail": "需要编辑者权限"}, status=403)
        return None


class TableListCreateView(TableMixin, generics.ListCreateAPIView):
    """数据表列表与建表."""

    def get_queryset(self):  # type: ignore[no-untyped-def]
        """当前工作区的全部数据表，内嵌字段避免 N+1."""
        return DataTable.objects.filter(workspace=self.get_workspace()).prefetch_related("fields")

    def get_serializer_class(self):  # type: ignore[no-untyped-def]
        """列表用表序列化器，创建用建表请求序列化器."""
        return DataTableCreateSerializer if self.request.method == "POST" else DataTableSerializer

    def create(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        """建表：元数据与物理表同事务创建，字段定义非法返回 400."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        serializer = DataTableCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            table = services.create_table(
                workspace=self.get_workspace(),
                name=serializer.validated_data["name"],
                field_defs=serializer.validated_data["fields"],
            )
        except FieldTypeError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(DataTableSerializer(table).data, status=201)


class TableDetailView(TableMixin, generics.RetrieveUpdateDestroyAPIView):
    """数据表详情：改名/排序（纯元数据）与删表（联动物理表）."""

    serializer_class = DataTableSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        """当前工作区的数据表."""
        return DataTable.objects.filter(workspace=self.get_workspace()).prefetch_related("fields")

    def update(self, request: Request, *_args: object, **kwargs: object) -> Response:
        """改表名/排序：无 DDL，要求 EDITOR 及以上角色."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        partial = kwargs.pop("partial", False)
        table = self.get_object()
        serializer = self.get_serializer(table, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, _request: Request, *_args: object, **_kwargs: object) -> Response:
        """删表：物理表与元数据同事务删除."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        services.delete_table(self.get_object())
        return Response(status=204)


class FieldListCreateView(TableMixin, generics.ListCreateAPIView):
    """字段列表与加字段."""

    def get_queryset(self):  # type: ignore[no-untyped-def]
        """当前数据表的全部字段."""
        return DataField.objects.filter(table=self.get_table())

    def get_serializer_class(self):  # type: ignore[no-untyped-def]
        """列表用字段序列化器，创建用字段定义序列化器."""
        return FieldDefSerializer if self.request.method == "POST" else DataFieldSerializer

    def create(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        """加字段：元数据与物理列同事务写入，定义非法返回 400."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        table = self.get_table()
        serializer = FieldDefSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            field = services.add_field(table, serializer.validated_data)
        except FieldTypeError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(DataFieldSerializer(field).data, status=201)


class FieldDetailView(TableMixin, generics.RetrieveUpdateDestroyAPIView):
    """字段详情：改定义（联动物理列）与删字段（联动物理列）."""

    serializer_class = DataFieldSerializer

    def get_queryset(self):  # type: ignore[no-untyped-def]
        """当前数据表的字段."""
        return DataField.objects.filter(table=self.get_table())

    def update(self, request: Request, *_args: object, **kwargs: object) -> Response:
        """改字段：名称/类型/配置/必填/回收站，物理列按需同步."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        partial = kwargs.pop("partial", False)
        field = self.get_object()
        serializer = self.get_serializer(field, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            services.update_field(
                field,
                services.FieldChanges(
                    name=data.get("name"),
                    field_type=data.get("field_type"),
                    config=data.get("config"),
                    required=data.get("required"),
                    trashed=data.get("trashed"),
                ),
            )
        except FieldTypeError as exc:
            return Response({"detail": str(exc)}, status=400)
        field.refresh_from_db()
        return Response(DataFieldSerializer(field).data)

    def destroy(self, _request: Request, *_args: object, **_kwargs: object) -> Response:
        """删字段：物理列与元数据同事务删除."""
        denied = self.require_editor()
        if denied is not None:
            return denied
        services.delete_field(self.get_object())
        return Response(status=204)
