"""进程内滑动窗口限流（登录失败防爆破）.

取舍：单机单进程部署下，进程内计数与 Redis 等价（多实例才需要共享存储 —— 与编辑锁同一结论）。
窗口语义：每个 key 记录失败时间戳，窗口外的自动淘汰；达到上限后拒绝并返回 Retry-After。
"""

from __future__ import annotations

import threading
import time
from collections import deque


class SlidingWindowLimiter:
    """按 key 的滑动窗口计数器（线程安全）."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = max(1, limit)
        self.window = max(1, window_seconds)
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        bucket = self._hits.setdefault(key, deque())
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        return bucket

    def configure(self, limit: int, window_seconds: int) -> None:
        """同步阈值（配置变更 / 测试调整后调用；已有计数保留）."""
        with self._lock:
            self.limit = max(1, limit)
            self.window = max(1, window_seconds)

    def retry_after(self, key: str) -> int:
        """达到上限时返回建议等待秒数（>0），否则返回 0."""
        now = time.monotonic()
        with self._lock:
            bucket = self._prune(key, now)
            if len(bucket) < self.limit:
                return 0
            # 最早一次失败滑出窗口的时间即为可重试时刻
            remaining = self.window - (now - bucket[0])
            return max(1, int(remaining + 0.999))

    def record(self, key: str) -> None:
        """记录一次失败."""
        now = time.monotonic()
        with self._lock:
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        """清除某 key 的计数（登录成功后调用）."""
        with self._lock:
            self._hits.pop(key, None)

    def reset_all(self) -> None:  # pragma: no cover - 测试/调试辅助
        with self._lock:
            self._hits.clear()


class LoginRateLimiter:
    """登录限流门面：按「账号」与「来源 IP」双维度计数.

    账号维度拦截针对单账号的爆破；IP 维度（更高阈值）拦截同一来源对多账号的喷洒。
    成功登录后清除账号维度计数（IP 维度保留，避免用少量有效账号洗掉喷洒记录）。
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.user_limiter = SlidingWindowLimiter(limit, window_seconds)
        self.ip_limiter = SlidingWindowLimiter(limit * 4, window_seconds)

    def configure(self, limit: int, window_seconds: int) -> None:
        """同步两个维度的阈值."""
        self.user_limiter.configure(limit, window_seconds)
        self.ip_limiter.configure(limit * 4, window_seconds)

    @staticmethod
    def user_key(username: str) -> str:
        return f"user:{username.strip().lower()}"

    @staticmethod
    def ip_key(ip: str | None) -> str:
        return f"ip:{ip or 'unknown'}"

    def retry_after(self, username: str, ip: str | None) -> int:
        """返回需要等待的秒数（0 表示允许）."""
        return max(
            self.user_limiter.retry_after(self.user_key(username)),
            self.ip_limiter.retry_after(self.ip_key(ip)),
        )

    def record_failure(self, username: str, ip: str | None) -> None:
        self.user_limiter.record(self.user_key(username))
        self.ip_limiter.record(self.ip_key(ip))

    def reset(self, username: str, ip: str | None = None) -> None:
        """登录成功后清账号计数；传入 ip 时同时清该 IP 计数."""
        self.user_limiter.reset(self.user_key(username))
        if ip is not None:
            self.ip_limiter.reset(self.ip_key(ip))


__all__ = ["LoginRateLimiter", "SlidingWindowLimiter"]
