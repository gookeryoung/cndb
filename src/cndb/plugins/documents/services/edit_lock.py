"""应用层编辑锁：防止同一文档被同时编辑（单进程内有效）.

SQLite 库级写锁已由 WAL + 短事务保障；本模块解决的是
「两个用户同时打开编辑器互相覆盖」的体验问题（配合乐观锁）。

锁语义：
- 编辑器打开文档时 acquire，保存/关闭时 release；
- 锁超时 5 分钟自动失效（编辑器崩溃兜底）；
- 进程级实现（单机部署场景足够，多进程部署需换 Redis）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from cndb.core.errors import ConflictError

LOCK_TIMEOUT_SECONDS = 300  # 5 分钟


@dataclass
class LockInfo:
    doc_id: int
    user_id: int
    username: str
    acquired_at: float

    @property
    def expired(self) -> bool:
        return time.time() - self.acquired_at > LOCK_TIMEOUT_SECONDS

    @property
    def elapsed_seconds(self) -> int:
        return int(time.time() - self.acquired_at)


class EditLockRegistry:
    """进程内文档编辑锁注册表."""

    def __init__(self) -> None:
        self._locks: dict[int, LockInfo] = {}

    def acquire(self, doc_id: int, user_id: int, username: str, *, force: bool = False) -> LockInfo:
        """获取编辑锁；被他人持有时抛 ConflictError.

        Args:
            force: 同一用户重复进入编辑器时刷新持有时间。
        """
        info = self._locks.get(doc_id)
        if info is not None and not info.expired:
            if info.user_id == user_id or force:
                info.acquired_at = time.time()
                return info
            raise ConflictError(
                f"{info.username} 正在编辑此文档（已持续 {info.elapsed_seconds} 秒）",
                code="doc_locked",
            )
        info = LockInfo(doc_id=doc_id, user_id=user_id, username=username, acquired_at=time.time())
        self._locks[doc_id] = info
        return info

    def release(self, doc_id: int, user_id: int) -> None:
        """释放锁（仅持有人可释放）。"""
        info = self._locks.get(doc_id)
        if info and info.user_id == user_id:
            del self._locks[doc_id]

    def status(self, doc_id: int) -> LockInfo | None:
        """查询锁状态（过期自动清理）。"""
        info = self._locks.get(doc_id)
        if info and info.expired:
            del self._locks[doc_id]
            return None
        return info

    def clear_expired(self) -> int:
        """批量清理过期锁，返回清理数。"""
        expired = [k for k, v in self._locks.items() if v.expired]
        for k in expired:
            del self._locks[k]
        return len(expired)


# 全局单例
edit_lock_registry = EditLockRegistry()

__all__ = ["EditLockRegistry", "LockInfo", "edit_lock_registry"]
