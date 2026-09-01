"""工作区序列化器：工作区与成员的读写."""

from __future__ import annotations

from rest_framework import serializers

from cndb.accounts.models import User
from cndb.workspaces.models import Workspace, WorkspaceMember
from cndb.workspaces.permissions import get_member_role


class WorkspaceSerializer(serializers.ModelSerializer):
    """工作区信息：附带当前请求用户在该工作区的角色."""

    role = serializers.SerializerMethodField(label="当前用户角色")

    class Meta:
        model = Workspace
        fields = ("id", "name", "role", "created_on", "updated_on")
        read_only_fields = ("id", "created_on", "updated_on")

    def get_role(self, obj: Workspace) -> str | None:
        """返回当前用户在工作区的角色，非成员为 None."""
        return get_member_role(self.context["request"].user, obj)


class MemberUserSerializer(serializers.ModelSerializer):
    """成员内嵌的用户简要信息."""

    class Meta:
        model = User
        fields = ("id", "username", "nickname")
        read_only_fields = ("id", "username", "nickname")


class WorkspaceMemberSerializer(serializers.ModelSerializer):
    """工作区成员信息."""

    user = MemberUserSerializer(read_only=True)

    class Meta:
        model = WorkspaceMember
        fields = ("id", "user", "role", "created_on")
        read_only_fields = ("id", "created_on")


class MemberAddSerializer(serializers.Serializer):
    """添加成员请求：按用户名定位用户并指定角色."""

    username = serializers.CharField(label="用户名")
    role = serializers.ChoiceField(choices=WorkspaceMember.Role.choices, label="角色")
