"""安全工具模块.

提供密码哈希 + JWT 令牌签发两个核心能力。
bcrypt / python-jose 已在 pyproject.toml 主依赖中；运行时探测是为了在 C 扩展加载失败
（如 Win7 下 bcrypt 4.x 的 Rust 模块因 ProcessPrng API 缺失无法加载）时给出清晰提示。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from cndb.core.config import settings

logger = logging.getLogger(__name__)


def _check_auth_deps() -> None:
    """探测 bcrypt / jose 能否正常 import.

    虽然两者是 pyproject.toml 主依赖，但 CFFI / Rust 编译的 C 扩展（bcrypt._bcrypt、
    cryptography._rust 等）在老系统上可能因缺少系统 API 而加载失败，此时 Python
    层会报 ImportError。我们在这里把原始异常包成带上下文的 RuntimeError，便于排障。
    """
    try:
        import bcrypt  # type: ignore  # noqa: F401 (运行时探测)
        import jose  # type: ignore  # noqa: F401
    except ImportError as exc:  # pragma: no cover - 依赖探测分支
        raise RuntimeError(
            f"认证依赖导入失败：{exc}\n"
            "可能原因：C 扩展加载失败（如 Win7 上 bcrypt 4.x Rust 模块缺少 ProcessPrng API）。\n"
            "请确认依赖版本兼容当前系统，或联系维护者检查打包配置。"
        ) from exc


# ── 密码哈希 ──────────────────────────────────────────────


def hash_password(plain: str) -> str:
    """对明文密码进行 bcrypt 哈希.

    Args:
        plain: 用户原始密码

    Returns:
        bcrypt 生成的哈希值字符串
    """
    _check_auth_deps()
    import bcrypt

    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码是否匹配 bcrypt 哈希.

    Args:
        plain: 用户输入的明文密码
        hashed: 数据库中存储的 bcrypt 哈希值
    """
    _check_auth_deps()
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
    _check_auth_deps()
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
    _check_auth_deps()
    from jose import jwt  # type: ignore

    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


__all__ = [
    "create_access_token",
    "decode_access_token",
    "hash_password",
    "verify_password",
]
