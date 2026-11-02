"""``file_key`` 生成与去重（ADR 0086 D2）.

``file_key`` 是 DSL ``use`` 引用的稳定字符串标识：工作区内唯一、创建后不可变。
缺省由标题清洗生成（保留中文 / 字母 / 数字 / ``_`` / ``-``，其余折叠为 ``-``），
冲突时追加 ``-2`` / ``-3`` 序号后缀；清洗结果为空时回退 ``design``。
"""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from cndb.plugins.design.models import DesignDesign

#: file_key 列宽（models.DesignDesign.file_key String(64)）
_MAX_KEY_LEN = 64

#: 允许保留的字符：字母 / 数字 / 下划线 / 连字符 / CJK
_INVALID_CHARS = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff-]+")
_REPEAT_DASH = re.compile(r"-{2,}")


def _slugify(title: str) -> str:
    """标题 → 合法 file_key 基底；空结果回退 ``design``."""
    key = _INVALID_CHARS.sub("-", title.strip())
    key = _REPEAT_DASH.sub("-", key).strip("-")
    return key[:_MAX_KEY_LEN].strip("-") or "design"


def generate_file_key(db: Session, workspace_id: int, title: str, *, preferred: str = "") -> str:
    """生成工作区内唯一的 ``file_key``（调用方负责随后落库，非并发安全）.

    ``preferred`` 非空时优先采用（如备份 v13 携带的原始 key），仍做唯一性去重。
    """
    base = _slugify(preferred) if preferred.strip() else _slugify(title)
    taken = {
        row[0]
        for row in db.query(DesignDesign.file_key)
        .filter(DesignDesign.workspace_id == workspace_id, DesignDesign.file_key.like(f"{base}%"))
        .all()
    }
    key = base
    n = 2
    while key in taken:
        suffix = f"-{n}"
        key = base[: _MAX_KEY_LEN - len(suffix)] + suffix
        n += 1
    return key


__all__ = ["generate_file_key"]
