"""API 令牌视图：签发、列表与撤销，查询集限定为本人令牌."""

from __future__ import annotations

from rest_framework import generics
from rest_framework.request import Request
from rest_framework.response import Response

from cndb.tokens.models import ApiToken
from cndb.tokens.serializers import ApiTokenSerializer


class TokenListCreateView(generics.ListCreateAPIView):
    """令牌列表与签发：明文只在签发响应中出现一次."""

    serializer_class = ApiTokenSerializer

    def get_queryset(self):
        """仅返回当前用户持有的令牌."""
        return ApiToken.objects.filter(user=self.request.user)

    def create(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        """签发令牌：校验名称后生成随机明文，响应附明文供一次性保存."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj, token = ApiToken.issue(request.user, str(serializer.validated_data["name"]))
        return Response({**ApiTokenSerializer(obj).data, "token": token}, status=201)


class TokenDetailView(generics.RetrieveDestroyAPIView):
    """令牌详情与撤销：DELETE 删除令牌对象即刻失效."""

    serializer_class = ApiTokenSerializer

    def get_queryset(self):
        """仅允许操作当前用户自己的令牌."""
        return ApiToken.objects.filter(user=self.request.user)
