"""API 令牌认证器：解析 Authorization: Token <明文令牌> 请求头."""

from __future__ import annotations

from django.utils import timezone
from rest_framework import authentication, exceptions

from cndb.accounts.models import User
from cndb.tokens.models import ApiToken, hash_token


class TokenAuthentication(authentication.BaseAuthentication):
    """请求头携带 Token 关键字时按摘要查库，以令牌属主身份认证."""

    keyword = "Token"

    def authenticate(self, request):  # type: ignore[no-untyped-def]
        """解析 Authorization 头；无 Token 关键字时返回 None 交由后续认证器."""
        header = authentication.get_authorization_header(request).decode("utf-8")
        keyword, _, value = header.partition(" ")
        if not keyword or keyword.lower() != self.keyword.lower():
            return None
        token = value.strip()
        if not token:
            raise exceptions.AuthenticationFailed("令牌不能为空")
        try:
            obj = ApiToken.objects.select_related("user").get(digest=hash_token(token))
        except ApiToken.DoesNotExist as exc:
            raise exceptions.AuthenticationFailed("令牌无效") from exc
        ApiToken.objects.filter(pk=obj.pk).update(last_used_on=timezone.now())
        user: User = obj.user
        return user, obj

    def authenticate_header(self, _request):  # type: ignore[no-untyped-def]
        """返回 WWW-Authenticate 值，使未认证响应为 401 而非 403."""
        return self.keyword
