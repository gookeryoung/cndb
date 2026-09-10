"""core.security 测试."""

from __future__ import annotations

import pytest

from pyweb_template.core import security


def test_hash_and_verify_roundtrip() -> None:
    plain = "p@ssw0rd"
    h = security.hash_password(plain)
    assert h != plain
    assert security.verify_password(plain, h) is True
    assert security.verify_password("wrong", h) is False


def test_verify_invalid_hash_returns_false() -> None:
    assert security.verify_password("anything", "not-a-real-hash") is False


def test_create_and_decode_token() -> None:
    token = security.create_access_token("user-42", extra={"role": "admin"})
    payload = security.decode_access_token(token)
    assert payload["sub"] == "user-42"
    assert payload["role"] == "admin"


def test_decode_invalid_token_raises() -> None:
    try:
        from jose import JWTError
    except ImportError:
        pytest.skip("python-jose 未安装，跳过")

    with pytest.raises(JWTError):
        security.decode_access_token("not.a.valid.token")
