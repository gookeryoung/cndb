"""字段级对称加密（Fernet）：用于凭证会话的密钥列（ADR 0006 M5 遗留项）.

设计约束：

- **只加密值，不加密键名** —— 读接口要回显「已配置哪些密钥」（键名），值一律不出库；
- **前缀可辨识**：密文形如 ``enc:v1:<fernet token>``。历史明文（无前缀）读时原样返回，
  因此存量数据**不需要迁移**，重新保存一次即完成加密；
- **密钥来源**：``settings.DATASOURCE_SECRET_KEY`` 优先，留空回退 ``settings.JWT_SECRET``。
  两处都经 ``sha256(salt + secret)`` 派生 32 字节再 urlsafe-base64 成 Fernet key，
  避免直接用口令当密钥（Fernet 要求 32 字节 base64）。
- **解密失败必须显式报错**：换过密钥 / 密文损坏时抛 :class:`SecretDecryptError`，
  由调用方（同步运行）落成 ``failed`` 运行记录 —— 静默返回空密钥只会让鉴权失败
  变成一个莫名其妙的 401，排查成本远高于直接报错。
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from cndb.core.config import settings

# 密文前缀：``enc:v1:`` = 第 1 版密钥派生方案（sha256 → Fernet）
ENC_PREFIX = "enc:v1:"
_KEY_SALT = b"cndb.datasource.secrets"


class SecretDecryptError(ValueError):
    """密文无法解密（密钥变更 / 数据损坏）."""


@lru_cache(maxsize=4)
def _fernet_for(secret: str) -> Fernet:
    """按口令派生 Fernet 实例（同口令复用；测试换密钥后调用 ``_fernet_for.cache_clear()``）."""
    digest = hashlib.sha256(_KEY_SALT + secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def _current_fernet() -> Fernet:
    secret = settings.DATASOURCE_SECRET_KEY or settings.JWT_SECRET
    return _fernet_for(secret)


def is_encrypted(value: object) -> bool:
    """是否已是本模块产出的密文."""
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def encrypt_secret(plain: str) -> str:
    """加密单个密钥值；空串原样返回（空值没有保护价值，也避免无意义密文）."""
    if not plain:
        return plain
    if is_encrypted(plain):
        return plain
    token = _current_fernet().encrypt(plain.encode("utf-8")).decode("ascii")
    return f"{ENC_PREFIX}{token}"


def decrypt_secret(value: str) -> str:
    """解密单个密钥值；历史明文（无前缀）原样返回.

    Raises:
        SecretDecryptError: 带前缀但解密失败（密钥变更 / 密文损坏）。
    """
    if not is_encrypted(value):
        return value
    try:
        return _current_fernet().decrypt(value[len(ENC_PREFIX) :].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise SecretDecryptError(
            "密钥解密失败：DATASOURCE_SECRET_KEY / JWT_SECRET 是否变更？请到「数据源同步 → 凭证会话」重新保存密钥"
        ) from exc


def encrypt_secrets(mapping: Mapping[str, str]) -> dict[str, str]:
    """整表加密（键名保持明文，值逐个加密）."""
    return {str(key): encrypt_secret(str(value or "")) for key, value in mapping.items()}


def decrypt_secrets(mapping: Mapping[str, str] | None) -> dict[str, str]:
    """整表解密；空 / None 返回空字典."""
    return {str(key): decrypt_secret(str(value or "")) for key, value in (mapping or {}).items()}


def rotate_secrets(mapping: Mapping[str, str], *, new_secret: str) -> dict[str, str]:
    """用新口令重加密（运维换密钥时用）：先按旧密钥解密，再按新密钥加密.

    说明：调用前需保证 ``settings.DATASOURCE_SECRET_KEY`` 仍是**旧值**，
    返回的字典由调用方写回；写回后再切配置，顺序不能反。
    """
    plain = decrypt_secrets(mapping)
    old = settings.DATASOURCE_SECRET_KEY
    try:
        settings.DATASOURCE_SECRET_KEY = new_secret
        return encrypt_secrets(plain)
    finally:
        settings.DATASOURCE_SECRET_KEY = old


__all__ = [
    "ENC_PREFIX",
    "SecretDecryptError",
    "decrypt_secret",
    "decrypt_secrets",
    "encrypt_secret",
    "encrypt_secrets",
    "is_encrypted",
    "rotate_secrets",
]
