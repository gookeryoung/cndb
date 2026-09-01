"""工作区与成员模型."""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Workspace(models.Model):
    """工作区：数据与权限的隔离边界."""

    name = models.CharField("名称", max_length=255)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_workspaces",
        verbose_name="创建人",
    )
    created_on = models.DateTimeField("创建时间", auto_now_add=True)
    updated_on = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "工作区"
        verbose_name_plural = "工作区"
        ordering = ["id"]

    def __str__(self) -> str:
        """返回工作区名便于后台展示."""
        return self.name  # type: ignore[bad-return]


class WorkspaceMember(models.Model):
    """工作区成员：用户在工作区内的角色."""

    class Role(models.TextChoices):
        """成员角色，权限从高到低：owner > admin > editor > commenter > viewer."""

        OWNER = "owner", "所有者"
        ADMIN = "admin", "管理员"
        EDITOR = "editor", "编辑者"
        COMMENTER = "commenter", "评论者"
        VIEWER = "viewer", "查看者"

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="members",
        verbose_name="工作区",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
        verbose_name="用户",
    )
    role = models.CharField("角色", max_length=16, choices=Role.choices, default=Role.VIEWER)
    created_on = models.DateTimeField("加入时间", auto_now_add=True)

    class Meta:
        verbose_name = "工作区成员"
        verbose_name_plural = "工作区成员"
        constraints = [
            models.UniqueConstraint(fields=("workspace", "user"), name="uniq_workspace_member"),
        ]
        ordering = ["workspace", "id"]

    def __str__(self) -> str:
        """返回"工作区/用户"便于后台展示."""
        return f"{self.workspace_id}/{self.user_id}"
