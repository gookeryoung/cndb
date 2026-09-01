"""工作区 API 视图：工作区增删改查与成员管理."""

from __future__ import annotations

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, viewsets
from rest_framework.request import Request
from rest_framework.response import Response

from cndb.accounts.models import User
from cndb.workspaces.models import Workspace, WorkspaceMember
from cndb.workspaces.permissions import IsWorkspaceMember, get_member_role, has_role
from cndb.workspaces.serializers import (
    MemberAddSerializer,
    WorkspaceMemberSerializer,
    WorkspaceSerializer,
)


class WorkspaceViewSet(viewsets.ModelViewSet):
    """工作区 CRUD：查询集限定为当前用户所属工作区."""

    serializer_class = WorkspaceSerializer
    permission_classes = [permissions.IsAuthenticated, IsWorkspaceMember]

    def get_queryset(self):
        """仅返回当前用户是成员的工作区."""
        return Workspace.objects.filter(members__user=self.request.user)

    def perform_create(self, serializer: WorkspaceSerializer) -> None:
        """创建工作区并把创建者登记为 OWNER 成员."""
        with transaction.atomic():  # type: ignore[bad-context-manager]
            workspace = serializer.save(created_by=self.request.user)
            WorkspaceMember.objects.create(
                workspace=workspace,
                user=self.request.user,
                role=WorkspaceMember.Role.OWNER,
            )


class WorkspaceMixin:
    """成员视图公共基类：解析 workspace_pk 并校验成员身份."""

    permission_classes = [permissions.IsAuthenticated]

    def get_workspace(self) -> Workspace:
        """获取路径中的工作区，非成员访问返回 404."""
        workspace = get_object_or_404(Workspace, pk=self.kwargs["workspace_pk"])
        if get_member_role(self.request.user, workspace) is None:
            self.permission_denied(self.request)
        return workspace  # type: ignore[return-value]


class MemberListCreateView(WorkspaceMixin, generics.ListCreateAPIView):
    """成员列表与添加成员."""

    def get_serializer_class(self):  # type: ignore[no-untyped-def]
        """列表用成员序列化器，创建用添加成员序列化器."""
        return MemberAddSerializer if self.request.method == "POST" else WorkspaceMemberSerializer

    def get_queryset(self):
        """当前工作区的全部成员."""
        return WorkspaceMember.objects.filter(workspace=self.get_workspace()).select_related("user")

    def create(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        """添加成员：要求 ADMIN 及以上角色，不允许添加为 OWNER."""
        workspace = self.get_workspace()
        if not has_role(request.user, workspace, WorkspaceMember.Role.ADMIN):
            return Response({"detail": "需要管理员权限"}, status=403)
        serializer = MemberAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data["role"] == WorkspaceMember.Role.OWNER:
            return Response({"detail": "不能直接添加所有者"}, status=400)
        user = get_object_or_404(User, username=serializer.validated_data["username"])
        if WorkspaceMember.objects.filter(workspace=workspace, user=user).exists():
            return Response({"detail": "用户已是成员"}, status=400)
        member = WorkspaceMember.objects.create(workspace=workspace, user=user, role=serializer.validated_data["role"])
        return Response(WorkspaceMemberSerializer(member).data, status=201)


class MemberDetailView(WorkspaceMixin, generics.RetrieveUpdateDestroyAPIView):
    """成员详情：改角色与移除成员，要求 ADMIN 及以上角色."""

    serializer_class = WorkspaceMemberSerializer

    def get_queryset(self):
        """当前工作区的成员记录."""
        return WorkspaceMember.objects.filter(workspace=self.get_workspace()).select_related("user")

    def _require_admin(self, request: Request, member: WorkspaceMember) -> Response | None:
        """校验操作者为 ADMIN+，且对 OWNER 的操作要求操作者本人为 OWNER。"""
        requester_role = get_member_role(request.user, member.workspace)
        if requester_role not in (WorkspaceMember.Role.OWNER, WorkspaceMember.Role.ADMIN):
            return Response({"detail": "需要管理员权限"}, status=403)
        if member.role == WorkspaceMember.Role.OWNER and requester_role != WorkspaceMember.Role.OWNER:
            return Response({"detail": "仅所有者可操作所有者"}, status=403)
        return None

    def update(self, request: Request, *_args: object, **kwargs: object) -> Response:
        """修改成员角色：保护最后一个 OWNER 不可降级。"""
        member = self.get_object()
        denied = self._require_admin(request, member)
        if denied is not None:
            return denied
        partial = kwargs.pop("partial", False)
        serializer = self.get_serializer(member, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        new_role = serializer.validated_data.get("role")
        if member.role == WorkspaceMember.Role.OWNER and new_role != WorkspaceMember.Role.OWNER:
            owners = WorkspaceMember.objects.filter(workspace=member.workspace, role=WorkspaceMember.Role.OWNER).count()
            if owners <= 1:
                return Response({"detail": "工作区至少保留一名所有者"}, status=400)
        serializer.save()
        return Response(serializer.data)

    def destroy(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        """移除成员：保护最后一个 OWNER 不可移除."""
        member = self.get_object()
        denied = self._require_admin(request, member)
        if denied is not None:
            return denied
        if member.role == WorkspaceMember.Role.OWNER:
            owners = WorkspaceMember.objects.filter(workspace=member.workspace, role=WorkspaceMember.Role.OWNER).count()
            if owners <= 1:
                return Response({"detail": "工作区至少保留一名所有者"}, status=400)
        member.delete()
        return Response(status=204)
