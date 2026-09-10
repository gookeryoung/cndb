"""api.deps 测试."""

from __future__ import annotations

from pyweb_template.api.deps import get_request_id


def test_get_request_id_passthrough() -> None:
    """有 X-Request-Id 时应透传."""
    assert get_request_id("abc-123") == "abc-123"


def test_get_request_id_generates_uuid() -> None:
    """无 X-Request-Id 时应生成 UUID hex."""
    rid = get_request_id(None)
    assert len(rid) == 32  # UUID4 hex 无连字符
    int(rid, 16)  # 验证是合法 hex
