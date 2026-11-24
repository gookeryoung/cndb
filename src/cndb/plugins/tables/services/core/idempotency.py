"""写请求幂等（ADR 0145）：``Idempotency-Key`` 头 + 响应回放.

用途：弱网 / 脚本重试时，同一个写请求只执行一次。口径：

- 键 = ``(user_id, key, route)`` 唯一；命中时**回放首个响应**（状态码 + body），不重复执行；
- 同一 key 但请求体不同 → 409（防止把 A 的响应当成 B 的结果）；
- 只登记 2xx 结果；失败不写登记（客户端重试会重新执行，符合"失败可重试"）；
- 保留期由 ``IDEMPOTENCY_RETENTION_DAYS``（默认 24 小时）控制，超期视同未命中；
- 未提供 ``Idempotency-Key`` 时整条链路是 no-op（不改变既有行为）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.tables.models import IdempotencyKey

logger = logging.getLogger(__name__)

#: 幂等键最长长度（超出直接 400，避免脏键写库）
MAX_KEY_LENGTH = 128

#: 记录保留时长（小时）：超期的键视同未命中
DEFAULT_RETENTION_HOURS = 24


def normalize_key(key: str | None) -> str | None:
    """规范化幂等键：去空白；超长 / 空串视为非法（返回 None 由调用方决定报错或忽略）."""
    if key is None:
        return None
    text = key.strip()
    if not text or len(text) > MAX_KEY_LENGTH:
        return None
    return text


def request_fingerprint(payload: Any) -> str:
    """请求体指纹：稳定 JSON 序列化后 sha256（同 key 复用到不同请求体要 409）."""
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):  # pragma: no cover - 极端不可序列化输入
        raw = repr(payload)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_aware(value: datetime) -> datetime:
    """SQLite 读回的 datetime 是 naive（UTC 存储）：比较前统一补 tz."""
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def find_replay(
    db: Session,
    *,
    user_id: int | None,
    key: str,
    route: str,
    fingerprint: str,
    retention_hours: int = DEFAULT_RETENTION_HOURS,
) -> tuple[bool, dict[str, Any] | None, int | None]:
    """查找可回放的响应.

    Returns:
        ``(hit, response, status_code)``：
        - 未命中 → ``(False, None, None)``
        - 同 key + 同请求体 → 命中，返回首个响应
        - 同 key + 不同请求体 → 抛 ``ValueError``（调用方转 409）
    """
    cutoff = datetime.now(UTC) - timedelta(hours=max(int(retention_hours), 1))
    entry = (
        db.query(IdempotencyKey)
        .filter(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == key,
            IdempotencyKey.route == route,
        )
        .first()
    )
    if entry is None:
        return False, None, None
    if entry.created_at is not None and _as_aware(entry.created_at) < cutoff:
        # 超期：清理掉当作未命中，让重试正常执行
        try:
            db.delete(entry)
            db.commit()
        except Exception:  # pragma: no cover - 清理失败不影响主流程
            db.rollback()
        return False, None, None
    if entry.request_hash != fingerprint:
        raise ValueError("同一 Idempotency-Key 对应了不同的请求体，请换一个 key 重试")
    return True, dict(entry.response or {}), int(entry.status_code)


def store_replay(
    db: Session,
    *,
    user_id: int | None,
    key: str,
    route: str,
    fingerprint: str,
    status_code: int,
    response: dict[str, Any],
) -> None:
    """登记首个成功响应（尽力而为：失败只记日志，不影响本次写入结果）."""
    try:
        db.add(
            IdempotencyKey(
                user_id=user_id,
                key=key,
                route=route,
                request_hash=fingerprint,
                status_code=int(status_code),
                response=response,
            )
        )
        db.commit()
    except Exception as exc:  # pragma: no cover - 并发同 key 时唯一约束冲突
        logger.warning("登记幂等键失败（忽略）: %s", exc)
        with contextlib.suppress(Exception):
            db.rollback()


def purge_expired_keys(db: Session, *, retention_hours: int = DEFAULT_RETENTION_HOURS) -> int:
    """清理超期幂等键，返回删除行数（运维用；也可挂 CLI）."""
    cutoff = datetime.now(UTC) - timedelta(hours=max(int(retention_hours), 1))
    deleted = db.query(IdempotencyKey).filter(IdempotencyKey.created_at < cutoff).delete(synchronize_session=False)
    db.commit()
    return int(deleted or 0)


__all__ = [
    "DEFAULT_RETENTION_HOURS",
    "MAX_KEY_LENGTH",
    "find_replay",
    "normalize_key",
    "purge_expired_keys",
    "request_fingerprint",
    "store_replay",
]
