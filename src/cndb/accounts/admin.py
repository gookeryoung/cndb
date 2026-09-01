"""用户后台注册."""

from __future__ import annotations

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from cndb.accounts.models import User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """用户后台：补充昵称展示."""

    list_display = ("id", "username", "nickname", "email", "is_active", "date_joined")
    fieldsets = (*DjangoUserAdmin.fieldsets, ("扩展信息", {"fields": ("nickname",)}))
