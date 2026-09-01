"""用户模型."""

from __future__ import annotations

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """平台用户：扩展 Django 内置用户，增加昵称用于界面展示."""

    nickname = models.CharField("昵称", max_length=150, blank=True)

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = "用户"

    def __str__(self) -> str:
        """返回用户名便于后台展示."""
        return self.username  # type: ignore[bad-return]
