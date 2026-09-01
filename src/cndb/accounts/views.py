"""认证 API 视图：注册、登录、登出与个人信息."""

from __future__ import annotations

from django.contrib.auth import login, logout
from rest_framework import generics, permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from cndb.accounts.models import User
from cndb.accounts.serializers import LoginSerializer, RegisterSerializer, UserSerializer


class RegisterView(generics.CreateAPIView):
    """注册：创建用户并直接建立会话."""

    permission_classes = [permissions.AllowAny]
    serializer_class = RegisterSerializer

    def create(self, request: Request, *_args: object, **_kwargs: object) -> Response:
        """校验、创建用户并登录会话，返回用户信息."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        login(request, user)
        return Response(UserSerializer(user).data, status=201)


class LoginView(APIView):
    """登录：校验凭证并建立会话."""

    permission_classes = [permissions.AllowAny]

    def post(self, request: Request) -> Response:
        """校验用户名密码，成功返回用户信息."""
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        login(request, serializer.validated_data["user"])  # type: ignore[arg-type]
        return Response(UserSerializer(serializer.validated_data["user"]).data)  # type: ignore[arg-type]


class LogoutView(APIView):
    """登出：销毁当前会话."""

    def post(self, request: Request) -> Response:
        """销毁会话并返回 204."""
        logout(request)
        return Response(status=204)


class MeView(generics.RetrieveUpdateAPIView):
    """个人信息：读取与更新昵称、邮箱."""

    serializer_class = UserSerializer

    def get_object(self) -> User:
        """当前登录用户."""
        return self.request.user  # type: ignore[return-value]
