"""用户序列化器：注册、登录与个人信息."""

from __future__ import annotations

from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed

from cndb.accounts.models import User


class RegisterSerializer(serializers.ModelSerializer):
    """注册请求：创建用户并校验密码强度."""

    password = serializers.CharField(write_only=True, trim_whitespace=False, label="密码")

    class Meta:
        model = User
        fields = ("id", "username", "email", "nickname", "password")
        read_only_fields = ("id",)
        extra_kwargs = {"email": {"required": True}}

    def validate_password(self, value: str) -> str:
        """按全局密码校验器检查强度."""
        validate_password(value)
        return value

    def create(self, validated_data: dict[str, object]) -> User:
        """使用 create_user 完成密码哈希后落库."""
        return User.objects.create_user(**validated_data)  # type: ignore[arg-type]


class LoginSerializer(serializers.Serializer):
    """登录请求：校验用户名与密码."""

    username = serializers.CharField(label="用户名")
    password = serializers.CharField(write_only=True, trim_whitespace=False, label="密码")

    def validate(self, attrs: dict[str, str]) -> dict[str, object]:
        """认证失败统一抛 AuthenticationFailed，避免泄露具体原因."""
        user = authenticate(
            request=self.context.get("request"),
            username=attrs["username"],
            password=attrs["password"],
        )
        if user is None:
            raise AuthenticationFailed("用户名或密码错误")
        return {**attrs, "user": user}


class UserSerializer(serializers.ModelSerializer):
    """用户信息：注册响应与个人信息读写共用."""

    class Meta:
        model = User
        fields = ("id", "username", "email", "nickname", "date_joined")
        read_only_fields = ("id", "username", "date_joined")
