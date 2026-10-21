"""进程内缓存（TTL + LRU）—— 不装 Redis 也能拿到等价收益.

**为什么进程内就够**：单机单进程部署下，Redis 的相对收益是"跨进程共享 + 网络存储"，
而进程内缓存的**读取路径没有网络往返与序列化**，对同样命中率的数据只会更快；
代价是无法跨进程共享 —— 这与本项目"SQLite 单文件 + 单进程"的既有限制一致。

**什么时候才需要换 Redis**：多实例水平扩时（缓存需要跨进程一致），或需要 Redis 的数据结构
（pub/sub、分布式锁、限流）。届时不改调用方：本模块通过 :class:`CacheBackend` 协议抽象，
换后端只需要替换实现（Redis 后端的接入点见 ``RedisBackendPlaceholder`` 注释）。

**失效策略的两条路**（本模块都支持）：
- ``invalidate(prefix)``：写路径主动失效（推荐，精确）；
- 短 TTL：写入点很多、或跨进程时用短 TTL 兜底（本项目的列表接口即用 3~15s）。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# 默认上限：条目数与单条 TTL（秒）
DEFAULT_MAX_ENTRIES = 512


@dataclass
class CacheStats:
    """缓存统计（用于验证命中率与容量）。"""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expirations: int = 0
    entries: int = 0

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return (self.hits / total) if total else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "expirations": self.expirations,
            "entries": self.entries,
            "hit_rate": round(self.hit_rate, 4),
        }


class CacheBackend(Protocol):
    """缓存后端协议（进程内实现见 :class:`TTLCache`）.

    需要接入 Redis 时，实现同样的 get/set/delete/clear 即可：
    ``core/redis_backend.py`` 里用 ``redis.Redis`` 包一层，键名带 ``cndb:`` 前缀，
    TTL 用 ``SETEX``，``clear(prefix)`` 用 SCAN + DEL（或按前缀维护集合）。
    """

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any, ttl_seconds: float) -> None: ...

    def delete(self, key: str) -> None: ...

    def clear(self, prefix: str | None = None) -> int: ...


class RedisBackendPlaceholder:  # pragma: no cover - 文档性质，不参与运行
    """（占位）Redis 后端接入点说明.

    本项目**刻意不引入 Redis**：单机单进程下进程内缓存性能更好（无网络往返）。
    若将来多实例部署需要共享缓存，按下面的形态实现即可，业务代码无需改动：

    .. code-block:: python

        class RedisCache:
            def __init__(self, url: str) -> None:
                import redis  # 仅在启用时才依赖

                self.client = redis.Redis.from_url(url)

            def get(self, key): ...
            def set(self, key, value, ttl_seconds): ...
            def delete(self, key): ...
            def clear(self, prefix=None): ...
    """


class TTLCache:
    """线程安全的 TTL + LRU 缓存（进程内）."""

    def __init__(self, *, max_entries: int = DEFAULT_MAX_ENTRIES, name: str = "default") -> None:
        self.max_entries = max(1, max_entries)
        self.name = name
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()
        self._stats = CacheStats()

    # ── 基础操作 ──

    def get(self, key: str) -> Any | None:
        now = time.monotonic()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                self._stats.misses += 1
                return None
            expires_at, value = item
            if expires_at <= now:
                del self._data[key]
                self._stats.expirations += 1
                self._stats.misses += 1
                return None
            self._data.move_to_end(key)  # LRU：命中即刷新位置
            self._stats.hits += 1
            return value

    def set(self, key: str, value: Any, ttl_seconds: float) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._data[key] = (time.monotonic() + ttl_seconds, value)
            self._data.move_to_end(key)
            while len(self._data) > self.max_entries:
                self._data.popitem(last=False)
                self._stats.evictions += 1

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self, prefix: str | None = None) -> int:
        """清除全部或某前缀的条目，返回清除数量."""
        with self._lock:
            if prefix is None:
                count = len(self._data)
                self._data.clear()
                return count
            keys = [k for k in self._data if k.startswith(prefix)]
            for key in keys:
                del self._data[key]
            return len(keys)

    # ── 便捷方法 ──

    def get_or_set(self, key: str, ttl_seconds: float, producer: Callable[[], T]) -> T:
        """读缓存；未命中时调用 ``producer`` 并写入.

        注意：命中时返回的是**同一对象引用**，调用方不得修改缓存对象
        （本项目缓存的是序列化后的响应 dict，按约定只读）。
        """
        cached = self.get(key)
        if cached is not None:
            return cached  # type: ignore[return-value]
        value = producer()
        self.set(key, value, ttl_seconds)
        return value

    def stats(self) -> CacheStats:
        with self._lock:
            snapshot = CacheStats(
                hits=self._stats.hits,
                misses=self._stats.misses,
                evictions=self._stats.evictions,
                expirations=self._stats.expirations,
                entries=len(self._data),
            )
        return snapshot

    def reset_stats(self) -> None:
        with self._lock:
            self._stats = CacheStats()

    def purge_expired(self) -> int:
        """清理过期条目（可挂到定时任务；TTL 到期读时也会自动清）."""
        now = time.monotonic()
        with self._lock:
            dead = [k for k, (expires_at, _) in self._data.items() if expires_at <= now]
            for key in dead:
                del self._data[key]
            self._stats.expirations += len(dead)
            return len(dead)


def cache_key(*parts: Any) -> str:
    """构造带命名空间的缓存键（避免不同用途串键）."""
    return "|".join(str(p) for p in parts)


# ── 预置实例 ──

# 列表类只读响应（短 TTL：写入点较多，用 TTL 兜底最稳）
list_cache = TTLCache(max_entries=512, name="list")

# 统计/元信息类（较长 TTL，由调用方显式失效）
meta_cache = TTLCache(max_entries=256, name="meta")

# 顶栏工作区搜索结果（短 TTL：单行写由事件即时失效，批量写显式失效，TTL 兜底）
search_cache = TTLCache(max_entries=256, name="search")


def invalidate_all(prefix: str | None = None) -> int:
    """失效所有预置缓存（可按前缀），供写路径或管理接口调用."""
    return list_cache.clear(prefix) + meta_cache.clear(prefix) + search_cache.clear(prefix)


__all__ = [
    "DEFAULT_MAX_ENTRIES",
    "CacheBackend",
    "CacheStats",
    "RedisBackendPlaceholder",
    "TTLCache",
    "cache_key",
    "invalidate_all",
    "list_cache",
    "meta_cache",
    "search_cache",
]
