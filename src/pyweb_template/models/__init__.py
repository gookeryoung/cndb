"""SQLAlchemy ORM 模型层.

模板骨架阶段仅提供 Base + 通用 mixin（id/created_at/updated_at），
具体业务模型由使用者按需添加（放在 models/<domain>.py）。
"""

from __future__ import annotations

from pyweb_template.models.base import Base, TimestampMixin

__all__ = ["Base", "TimestampMixin"]
