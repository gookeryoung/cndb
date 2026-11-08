"""设计个人草稿判定（ADR 0125）.

- 3s 自动保存只写 ``design_designdraft``：不编译、不落版本、不改正式内容（C1/C2）；
- 内容与最新版本一致时删除草稿行（等价于「无修改」）；
- 距最新版本满 ``DESIGN_CHECKPOINT_INTERVAL_SECONDS`` 且内容有变化时落一条
  ``auto`` 检查点；编译失败保留草稿、不落版（C4 / I5）；
- 草稿按用户隔离，只有本人可读写；不进版本列表 / diff / 备份（I3 / C8）。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError
from cndb.plugins.accounts.models import User
from cndb.plugins.design.models import (
    CHANGE_TYPE_AUTO,
    DesignDesign,
    DesignDesignDraft,
    DesignDesignVersion,
)
from cndb.plugins.design.services.content import latest_version, persist_design_content
from cndb.plugins.design.services.dsl.limits import MAX_CONTENT_BYTES
from cndb.plugins.design.services.files import content_hash

#: 兜底检查点间隔（秒）：测试可 monkeypatch（ADR 0125 D5）
DESIGN_CHECKPOINT_INTERVAL_SECONDS = 600


def get_design_draft(db: Session, design_id: int, user_id: int) -> DesignDesignDraft | None:
    """取个人草稿（不存在返回 None）."""
    return db.execute(
        select(DesignDesignDraft).where(
            DesignDesignDraft.design_id == design_id,
            DesignDesignDraft.user_id == user_id,
        )
    ).scalar_one_or_none()


def _delete_own_draft(db: Session, design_id: int, user_id: int) -> None:
    """删除本人草稿行（不 commit，由调用方统一提交）."""
    db.execute(
        delete(DesignDesignDraft).where(
            DesignDesignDraft.design_id == design_id,
            DesignDesignDraft.user_id == user_id,
        )
    )


def discard_design_draft(db: Session, design: DesignDesign, user: User) -> None:
    """丢弃本人草稿（幂等，提交事务）."""
    _delete_own_draft(db, design.id, user.id)
    db.commit()


def delete_all_drafts(db: Session, design_id: int) -> None:
    """清空该设计全部用户草稿（刷新 / 恢复整体换代时用，不 commit）."""
    db.execute(delete(DesignDesignDraft).where(DesignDesignDraft.design_id == design_id))


def draft_payload(db: Session, design: DesignDesign, user: User) -> dict[str, Any] | None:
    """当前用户在该设计上的草稿载荷；草稿与最新版本一致时视为不存在."""
    draft = get_design_draft(db, design.id, user.id)
    if draft is None:
        return None
    latest = latest_version(db, design.id)
    latest_content = latest.content if latest is not None else ""
    latest_number = latest.version_number if latest is not None else 0
    if draft.content_hash == content_hash(latest_content):
        return None
    return {
        "content": draft.content,
        "content_size": draft.content_size,
        "base_version_number": draft.base_version_number,
        "current_version_number": latest_number,
        "stale": draft.base_version_number < latest_number,
        "updated_at": draft.updated_at.isoformat() if draft.updated_at else None,
    }


def _as_utc(value: dt.datetime) -> dt.datetime:
    """统一为带时区 UTC（SQLite 读回可能为 naive）."""
    return value.replace(tzinfo=dt.UTC) if value.tzinfo is None else value


def checkpoint_due(latest: DesignDesignVersion | None, *, now: dt.datetime | None = None) -> bool:
    """是否到达兜底检查点（距最新版本创建时间满间隔；无版本不自动落版）."""
    if latest is None or latest.created_at is None:
        return False
    current = now or dt.datetime.now(dt.UTC)
    return (current - _as_utc(latest.created_at)).total_seconds() >= DESIGN_CHECKPOINT_INTERVAL_SECONDS


def save_design_draft(
    db: Session,
    design: DesignDesign,
    user: User,
    *,
    content: str,
    base_version_number: int | None = None,
) -> dict[str, Any] | None:
    """保存个人草稿；到期且内容有变化时顺带落一条 ``auto`` 检查点.

    返回最新草稿载荷；草稿与最新版本一致或检查点已把内容落版时返回 None。
    """
    size = len(content.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise BadRequestError(
            f"草稿超过 {MAX_CONTENT_BYTES // 1024}KB 上限",
            code="design_draft_too_large",
        )

    latest = latest_version(db, design.id)
    latest_content = latest.content if latest is not None else ""
    latest_number = latest.version_number if latest is not None else 0
    base = latest_number if base_version_number is None else base_version_number
    if base > latest_number:
        raise BadRequestError(f"基准版本不存在：v{base}（当前最新 v{latest_number}）", code="design_draft_base_invalid")

    new_hash = content_hash(content)
    if new_hash == content_hash(latest_content):
        _delete_own_draft(db, design.id, user.id)
        db.commit()
        return None

    draft = get_design_draft(db, design.id, user.id)
    if draft is None:
        draft = DesignDesignDraft(design_id=design.id, user_id=user.id)
        db.add(draft)
    draft.content = content
    draft.content_size = size
    draft.content_hash = new_hash
    draft.base_version_number = base
    db.flush()

    if checkpoint_due(latest):
        try:
            persist_design_content(
                db,
                design,
                user,
                content=content,
                change_type=CHANGE_TYPE_AUTO,
                comment="自动检查点",
            )
        except BadRequestError:
            # 检查点编译失败：保留草稿，不改正式内容（I5）
            db.commit()
            db.refresh(draft)
            return draft_payload(db, design, user)
        _delete_own_draft(db, design.id, user.id)
        db.commit()
        return None

    db.commit()
    db.refresh(draft)
    return draft_payload(db, design, user)
