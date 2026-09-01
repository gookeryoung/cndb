"""表级权限 API：读取与配置角色覆盖/字段隐藏/行级过滤，写操作要求 ADMIN 及以上角色."""

from __future__ import annotations

from rest_framework import generics
from rest_framework.request import Request
from rest_framework.response import Response

from cndb.tables.models import TablePermission
from cndb.tables.permission_rules import InvalidPermissionError
from cndb.tables.serializers import TablePermissionSerializer
from cndb.tables.views import TableMixin
from cndb.workspaces.models import WorkspaceMember
from cndb.workspaces.permissions import has_role


class PermissionDetailView(TableMixin, generics.RetrieveUpdateDestroyAPIView):
    """表级权限详情：读取（成员）/配置与恢复默认（ADMIN 及以上）."""

    serializer_class = TablePermissionSerializer

    def get_object(self):  # type: ignore[no-untyped-def]
        """获取当前表的权限对象；不存在时返回未落库的默认实例（GET 展示默认值）."""
        table = self.get_table()
        permission = TablePermission.objects.filter(table=table).first()
        if permission is None:
            return TablePermission(table=table)
        return permission

    def retrieve(self, _request: Request, *_args: object, **_kwargs: object) -> Response:
        """读取权限配置：未配置时返回默认（空覆盖）结构."""
        instance = self.get_object()
        return Response(TablePermissionSerializer(instance).data)

    def update(self, request: Request, *_args: object, **kwargs: object) -> Response:
        """配置权限：结构非法返回 400，首次配置即落库."""
        denied = self._require_admin()
        if denied is not None:
            return denied
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except InvalidPermissionError as exc:
            return Response({"detail": str(exc)}, status=400)
        return Response(TablePermissionSerializer(instance).data)

    def destroy(self, _request: Request, *_args: object, **_kwargs: object) -> Response:
        """删除权限对象，恢复工作区默认口径."""
        denied = self._require_admin()
        if denied is not None:
            return denied
        permission = TablePermission.objects.filter(table=self.get_table()).first()
        if permission is not None:
            permission.delete()
        return Response(status=204)

    def _require_admin(self) -> Response | None:
        """权限配置管理要求 ADMIN 及以上角色，不满足返回 403 响应."""
        if not has_role(self.request.user, self.get_workspace(), WorkspaceMember.Role.ADMIN):
            return Response({"detail": "需要管理员及以上权限"}, status=403)
        return None
