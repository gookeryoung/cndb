"""SQLAlchemy 模型基类与通用 Mixin."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的公共基类.

    继承自 SQLAlchemy 2.0 的 DeclarativeBase，
    可直接在子类中定义 Column/Mapped 字段。
    """

    # 为所有模型提供统一的 __repr__（仅展示主键和有值字段）
    def __repr__(self) -> str:  # pragma: no cover - 调试辅助
        cls_name = type(self).__name__
        fields: list[str] = []
        for c in self.__table__.columns:
            value = getattr(self, c.name, None)
            if value is not None:
                fields.append(f"{c.name}={value!r}")
        return f"{cls_name}({', '.join(fields)})"


class TimestampMixin:
    """通用时间戳字段 mixin.

    自动提供 created_at / updated_at 两个字段，
    default 由数据库层 func.now() 填充，updated_at 通过事件钩子自动刷新。
    若需关闭某字段（如只有创建时间不需要更新时间），可在子类覆盖字段声明。
    """

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        comment="创建时间（UTC）",
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="最后更新时间（UTC）",
    )


def __getattr__(name: str) -> Any:  # pragma: no cover - 惰性加载辅助
    """惰性导出：按需加载 models 包下的子模块.

    使用者直接 `from pyweb_template.models import User` 时，
    __getattr__ 会尝试从 models 子包的同名模块加载类，
    避免 models/__init__.py 显式 import 所有子模块。
    """
    if name.startswith("_"):
        raise AttributeError(name)
    import importlib

    try:
        module = importlib.import_module(f"pyweb_template.models.{name.lower()}")
        return getattr(module, name)
    except (ImportError, AttributeError) as exc:
        raise AttributeError(f"module 'pyweb_template.models' has no attribute {name!r}") from exc
