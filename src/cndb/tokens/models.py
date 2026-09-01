"""API 令牌模型：供外部脚本以用户身份调用 API.

安全设计：令牌明文仅在签发时返回一次，库中只存 SHA-256 摘要；
prefix 保存前 12 个字符用于列表识别，泄露后可按前缀定位撤销。
"""

from __future__ import annotations

import hashlib
import secrets

from django.db import models

from cndb.accounts.models import User


def generate_api_token() -> str:
    """生成随机令牌明文：cndb_ 前缀 + 40 位十六进制随机串."""
    return f"cndb_{secrets.token_hex(20)}"


def hash_token(token: str) -> str:
    """返回令牌的 SHA-256 十六进制摘要（落库形式）."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class ApiToken(models.Model):
    """用户的 API 访问令牌：认证通过后以令牌属主身份执行请求."""

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="api_tokens",
        verbose_name="所属用户",
    )
    name = models.CharField("名称", max_length=150)
    prefix = models.CharField("令牌前缀", max_length=12, editable=False)
    digest = models.CharField("令牌摘要", max_length=64, unique=True, editable=False)
    created_on = models.DateTimeField("创建时间", auto_now_add=True)
    last_used_on = models.DateTimeField("最近使用", null=True, blank=True)

    class Meta:
        verbose_name = "API 令牌"
        verbose_name_plural = "API 令牌"
        ordering = ["-created_on"]

    def __str__(self) -> str:
        """返回"名称 (前缀…)"便于后台展示."""
        return f"{self.name} ({self.prefix}…)"

    @classmethod
    def issue(cls, user: User, name: str) -> tuple[ApiToken, str]:
        """签发新令牌：返回 (令牌对象, 明文)，明文仅此一次可见."""
        token = generate_api_token()
        obj = cls.objects.create(
            user=user,
            name=name,
            prefix=token[:12],
            digest=hash_token(token),
        )
        return obj, token
