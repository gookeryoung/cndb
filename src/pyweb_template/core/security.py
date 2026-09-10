"""安全工具模块.

提供密码哈希 + JWT 令牌签发两个核心能力。
为可选模块：若未安装 bcrypt/python-jose（auth extra），调用时会抛出 RuntimeError
并给出安装指引，避免模板空壳运行时报错。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from pyweb_template.core.config import settings

logger = logging.getLogger(__name__)


def _check_auth_extra() -> None:
    """检查 auth extra 是否已安装.

    bcrypt / python-jose 不是运行时必需依赖，模板骨架允许裸跑。
    真正使用认证时需 `uv sync --extra auth`。
    """
    try:
        import bcrypt  # type: ignore  # noqa: F401 (运行时探测)
        import jose  # type: ignore  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 依赖探测分支
        raise RuntimeError("认证依赖未安装，请执行 `uv sync --extra auth` 安装 bcrypt + python-jose") from exc


# ── 密码哈希 ──────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """对明文密码进行 bcrypt 哈希.

    Args:
        plain: 用户原始密码

    Returns:
        bcrypt 生成的哈希值字符串
    """
    _check_auth_extra()
    import bcrypt

    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码是否匹配 bcrypt 哈希.

    Args:
        plain: 用户输入的明文密码
        hashed: 数据库中存储的 bcrypt 哈希值
    """
    _check_auth_extra()
    import bcrypt

    try:
        import bcrypt  # type: ignore

        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.warning("密码校验异常：%s", exc)
        return False


# ── JWT 令牌 ──────────────────────────────────────────────


def create_access_token(subject: str | int, extra: dict[str, Any] | None = None) -> str:
    """签发 JWT 访问令牌.

    Args:
        subject: 令牌主体（通常是用户 ID 或用户名）
        extra: 附加载荷（如 role / groups 等）

    Returns:
        JWT 字符串
    """
    _check_auth_extra()
    from jose import jwt  # type: ignore

    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """解析 JWT 令牌.

    Args:
        token: JWT 字符串

    Returns:
        解码后的 payload 字典；无效时抛出 jose.JWTError
    """
    _check_auth_extra()
    from jose import jwt  # type: ignore

    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


__all__ = [
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "verify_password",
]
