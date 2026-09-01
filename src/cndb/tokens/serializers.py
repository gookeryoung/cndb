"""API 令牌序列化器：列表与详情不暴露明文与摘要."""

from __future__ import annotations

from rest_framework import serializers

from cndb.tokens.models import ApiToken


class ApiTokenSerializer(serializers.ModelSerializer):
    """令牌信息：仅暴露名称、前缀与时间字段."""

    class Meta:
        model = ApiToken
        fields = ("id", "name", "prefix", "created_on", "last_used_on")
        read_only_fields = ("id", "prefix", "created_on", "last_used_on")
