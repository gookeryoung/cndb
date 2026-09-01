"""工作区后台注册."""

from __future__ import annotations

from django.contrib import admin

from cndb.workspaces.models import Workspace, WorkspaceMember


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    """工作区后台."""

    list_display = ("id", "name", "created_by", "created_on")


@admin.register(WorkspaceMember)
class WorkspaceMemberAdmin(admin.ModelAdmin):
    """工作区成员后台."""

    list_display = ("id", "workspace", "user", "role", "created_on")
    list_filter = ("role",)
