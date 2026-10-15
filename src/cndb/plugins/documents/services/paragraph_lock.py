"""按段落编辑锁 + 段落级三方合并.

**目标**（产品要求）：*不允许同时改同一段*，但**不同段落可以并发编辑**。

实现分三层：

1. **段落切分与定位**：``split_paragraphs`` 按空行切块（与 Markdown 块级语义一致），
   段落键为 **位置键** ``p1`` / ``p2`` …（基于**已保存版本**的位置）。
   为什么不用"内容哈希"做键：A 改了第 3 段后哈希就变了，B 手里基于旧哈希的锁将不再碰撞，
   同段互斥就失效了 —— 位置键才能保证"同一段"始终是同一把锁（代价：中间插入/删除会让后续
   段落位置平移，这是本方案的已知近似，真正的块 ID 需要块级数据模型）。

2. **段落锁**（``ParagraphLockRegistry``）：进程内注册表，键为 ``(doc_id, paragraph_key)``，
   带 TTL（默认 300s，与文档锁一致），同一用户重复获取即续期；被他人持有时抛
   ``ConflictError(code="paragraph_locked")``。**不做**事务外持久化：锁是"谁在编辑"的软状态，
   进程重启后由新的编辑行为重新建立（与既有文档锁同一取舍）。

3. **保存时合并**（``merge_incoming``）：客户端回传 ``base_content``（开始编辑时的正文），
   服务端做**段落级三方合并**：
   - 我改的段落 = base 与 incoming 不同的位置；
   - 别人改的段落 = base 与 latest 不同的位置；
   - 两者**交集** → 真冲突（409，指出第几段）；无交集 → 把"我改的段落"覆盖到 latest 上，保存合并结果。
   这样 A 改第 1 段、B 改第 3 段都能保存成功；同一段两人都改则后者被明确拒绝。
"""

from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field

from cndb.core.errors import ConflictError

logger = logging.getLogger(__name__)

# 段落锁 TTL（秒）；与文档锁一致
PARAGRAPH_LOCK_TTL_SECONDS = 300

_BLANK_LINE_RE = re.compile(r"\n\s*\n")


def split_paragraphs(text: str) -> list[str]:
    """按空行切分段落（保留段内换行，去除首尾空白）.

    与 Markdown 块级语义基本一致；空文本返回空列表。
    """
    if not text or not text.strip():
        return []
    parts = _BLANK_LINE_RE.split(text.replace("\r\n", "\n").replace("\r", "\n"))
    return [p.strip("\n") for p in parts if p.strip()]


def paragraph_keys(text: str) -> list[str]:
    """段落键列表（位置键 ``p1`` …）——与已保存版本的位置一一对应."""
    return [f"p{i + 1}" for i in range(len(split_paragraphs(text)))]


def key_to_index(key: str) -> int | None:
    """``p3`` → 3（1 基）；非法键返回 None."""
    if not key or not key.startswith("p"):
        return None
    tail = key[1:]
    return int(tail) if tail.isdigit() and int(tail) > 0 else None


def changed_paragraph_indices(base: str, incoming: str) -> set[int]:
    """返回 incoming 相对 base 发生变化的段落位置（1 基，含新增段落）."""
    base_parts = split_paragraphs(base)
    incoming_parts = split_paragraphs(incoming)
    changed: set[int] = set()
    for idx in range(max(len(base_parts), len(incoming_parts))):
        before = base_parts[idx] if idx < len(base_parts) else None
        after = incoming_parts[idx] if idx < len(incoming_parts) else None
        if before != after:
            changed.add(idx + 1)
    return changed


@dataclass
class MergeOutcome:
    """段落级合并结果."""

    text: str
    merged: bool
    incoming_changes: set[int] = field(default_factory=set)
    other_changes: set[int] = field(default_factory=set)
    conflicts: set[int] = field(default_factory=set)

    @property
    def conflict_keys(self) -> list[str]:
        return [f"p{i}" for i in sorted(self.conflicts)]


def merge_incoming(base: str, latest: str, incoming: str) -> MergeOutcome:
    """把「我的段落改动」合并到最新版本上；返回冲突段落（若有）.

    - 无冲突：``text`` 为合并结果（我的改动 + 别人的改动都在）；
    - 有冲突：``text`` 为 latest（调用方应拒绝保存并提示冲突段落）。
    """
    incoming_changes = changed_paragraph_indices(base, incoming)
    other_changes = changed_paragraph_indices(base, latest)
    conflicts = incoming_changes & other_changes

    base_parts = split_paragraphs(base)
    latest_parts = split_paragraphs(latest)
    incoming_parts = split_paragraphs(incoming)

    if conflicts:
        return MergeOutcome(
            text=latest,
            merged=False,
            incoming_changes=incoming_changes,
            other_changes=other_changes,
            conflicts=conflicts,
        )

    if not incoming_changes:
        # 我没有改动：保持最新（可能是别人的改动）
        return MergeOutcome(text=latest, merged=True, incoming_changes=set(), other_changes=other_changes)

    total = max(len(latest_parts), len(incoming_parts))
    merged_parts: list[str] = []
    for idx in range(total):
        position = idx + 1
        if position in incoming_changes:
            if idx < len(incoming_parts):
                merged_parts.append(incoming_parts[idx])
            # 我在这个位置删除了段落 → 不追加
        elif idx < len(latest_parts):
            merged_parts.append(latest_parts[idx])
        elif idx < len(base_parts):
            # latest 缺失而 base 有 → 别人删掉了，尊重删除
            continue
    return MergeOutcome(
        text="\n\n".join(merged_parts) + ("\n" if merged_parts else ""),
        merged=True,
        incoming_changes=incoming_changes,
        other_changes=other_changes,
    )


def remap_positions(old_text: str, new_text: str) -> dict[int, int | None]:
    """把「旧段落位置」映射到「新段落位置」（内容相同者按出现顺序一一配对）.

    解决的问题：段落键是**位置键**，一旦有人在中间插入/删除段落，其余人的锁位置就会漂移
    （锁住的其实是另一段）。保存时按内容配对重排锁位置，即可让锁"跟着段落走"：

    - 内容未变的段落 → 映射到它的新位置；
    - 被改写或删除的段落 → 映射为 ``None``（其锁释放：该段落的编辑已经落地）。

    相同内容的重复段落按出现顺序配对（deque 逐个消费），保证稳定且可预期。
    """
    from collections import deque

    old_parts = split_paragraphs(old_text)
    new_parts = split_paragraphs(new_text)
    buckets: dict[str, deque[int]] = {}
    for idx, part in enumerate(new_parts):
        buckets.setdefault(part, deque()).append(idx + 1)

    mapping: dict[int, int | None] = {}
    for idx, part in enumerate(old_parts):
        bucket = buckets.get(part)
        mapping[idx + 1] = bucket.popleft() if bucket else None
    return mapping


@dataclass
class ParagraphLockInfo:
    """段落锁信息."""

    document_id: int
    key: str
    user_id: int
    username: str
    acquired_at: float

    @property
    def expired(self) -> bool:
        return (time.time() - self.acquired_at) > PARAGRAPH_LOCK_TTL_SECONDS

    @property
    def elapsed_seconds(self) -> int:
        return int(time.time() - self.acquired_at)

    def as_dict(self) -> dict[str, object]:
        return {
            "document_id": self.document_id,
            "key": self.key,
            "user_id": self.user_id,
            "username": self.username,
            "elapsed_seconds": self.elapsed_seconds,
        }


class ParagraphLockRegistry:
    """段落锁注册表（进程内，线程安全，带 TTL）."""

    def __init__(self, ttl_seconds: int = PARAGRAPH_LOCK_TTL_SECONDS) -> None:
        self._locks: dict[tuple[int, str], ParagraphLockInfo] = {}
        self._ttl = ttl_seconds
        self._lock = threading.Lock()

    # ── 内部 ──

    def _expired(self, info: ParagraphLockInfo) -> bool:
        return (time.time() - info.acquired_at) > self._ttl

    def _prune_locked(self) -> int:
        dead = [k for k, v in self._locks.items() if self._expired(v)]
        for k in dead:
            del self._locks[k]
        return len(dead)

    # ── 获取 / 释放 ──

    def acquire_many(
        self,
        document_id: int,
        keys: list[str],
        user_id: int,
        username: str,
    ) -> list[ParagraphLockInfo]:
        """批量获取段落锁（原子：任一被他人持有时整体失败）."""
        if not keys:
            return []
        with self._lock:
            self._prune_locked()
            for key in keys:
                info = self._locks.get((document_id, key))
                if info is not None and info.user_id != user_id:
                    raise ConflictError(
                        f"{info.username} 正在编辑第 {key_to_index(key)} 段",
                        code="paragraph_locked",
                        context={"key": key, "user_id": info.user_id, "username": info.username},
                    )
            acquired: list[ParagraphLockInfo] = []
            for key in keys:
                info = self._locks.get((document_id, key))
                if info is not None and info.user_id == user_id:
                    info.acquired_at = time.time()  # 续期
                else:
                    info = ParagraphLockInfo(
                        document_id=document_id,
                        key=key,
                        user_id=user_id,
                        username=username,
                        acquired_at=time.time(),
                    )
                    self._locks[(document_id, key)] = info
                acquired.append(info)
            return acquired

    def release_many(self, document_id: int, keys: list[str], user_id: int) -> int:
        """释放指定段落锁（仅限自己持有的）；返回释放数量."""
        released = 0
        with self._lock:
            for key in keys:
                info = self._locks.get((document_id, key))
                if info is not None and info.user_id == user_id:
                    del self._locks[(document_id, key)]
                    released += 1
        return released

    def release_all_for_user(self, document_id: int, user_id: int) -> int:
        """释放某用户在该文档的全部段落锁（离开文档/保存后清理）."""
        with self._lock:
            keys = [k for k, v in self._locks.items() if k[0] == document_id and v.user_id == user_id]
            for key in keys:
                del self._locks[key]
            return len(keys)

    # ── 查询 ──

    def locks_for_document(self, document_id: int) -> list[ParagraphLockInfo]:
        """该文档当前有效的段落锁（按段落位置排序）."""
        with self._lock:
            self._prune_locked()
            locks = [v for k, v in self._locks.items() if k[0] == document_id]
        locks.sort(key=lambda info: key_to_index(info.key) or 0)
        return locks

    def held_by_others(self, document_id: int, keys: list[str], user_id: int) -> list[ParagraphLockInfo]:
        """给定段落中，被**其他人**锁住的那些."""
        with self._lock:
            self._prune_locked()
            return [
                self._locks[(document_id, key)]
                for key in keys
                if (document_id, key) in self._locks and self._locks[(document_id, key)].user_id != user_id
            ]

    def conflicts_for_indices(self, document_id: int, indices: set[int], user_id: int) -> list[ParagraphLockInfo]:
        """保存时：我改动的段落里，哪些被别人锁住（真冲突）."""
        keys = [f"p{i}" for i in sorted(indices)]
        return self.held_by_others(document_id, keys, user_id)

    def remap(self, document_id: int, mapping: dict[int, int | None]) -> dict[str, object]:
        """按「旧位置 → 新位置」重排该文档的段落锁.

        - 映射到新位置：把锁移到该位置（``p3 → p4``），锁的持有者与时间保持不变；
        - 映射为 ``None``：段落已被改写/删除 → 释放该锁；
        - 目标位置已被他人占用：保留原锁不动（保守策略，避免悄悄抢锁），并计入 ``kept``。

        Returns:
            ``{"moved": n, "released": n, "kept": n, "mapping": {...}}``（便于日志与测试）
        """
        moved = released = kept = 0
        details: dict[str, str] = {}
        with self._lock:
            self._prune_locked()
            items = [(k, v) for k, v in self._locks.items() if k[0] == document_id]
            for (doc_id, old_key), info in items:
                old_index = key_to_index(old_key)
                if old_index is None:
                    continue
                target_index = mapping.get(old_index)
                if target_index is None:
                    del self._locks[(doc_id, old_key)]
                    released += 1
                    details[old_key] = "released"
                    continue
                new_key = f"p{target_index}"
                if new_key == old_key:
                    continue
                occupied = self._locks.get((doc_id, new_key))
                if occupied is not None and occupied.user_id != info.user_id:
                    kept += 1
                    details[old_key] = f"kept(occupied by {occupied.username})"
                    continue
                del self._locks[(doc_id, old_key)]
                info.key = new_key
                self._locks[(doc_id, new_key)] = info
                moved += 1
                details[old_key] = new_key
        return {"moved": moved, "released": released, "kept": kept, "mapping": details}

    def clear_expired(self) -> int:
        with self._lock:
            return self._prune_locked()

    def reset(self) -> None:
        """清空（测试隔离用）."""
        with self._lock:
            self._locks.clear()


# 全局单例（与文档锁、实时中枢同一取舍：单机单进程）
paragraph_lock_registry = ParagraphLockRegistry()

__all__ = [
    "PARAGRAPH_LOCK_TTL_SECONDS",
    "MergeOutcome",
    "ParagraphLockInfo",
    "ParagraphLockRegistry",
    "changed_paragraph_indices",
    "key_to_index",
    "merge_incoming",
    "paragraph_keys",
    "paragraph_lock_registry",
    "remap_positions",
    "split_paragraphs",
]
