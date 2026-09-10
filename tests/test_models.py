"""models.base 测试."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import String, create_engine, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from pyweb_template.models import Base, TimestampMixin


def test_base_is_declarative() -> None:
    """Base 应是 SQLAlchemy DeclarativeBase."""

    class Simple(Base):
        __tablename__ = "_test_simple"
        name: Mapped[str] = mapped_column(String(50), primary_key=True)

    assert hasattr(Simple, "__table__")
    assert Simple.__table__.name == "_test_simple"  # type: ignore[union-attr]


def test_timestamp_mixin_fields_exist() -> None:
    """TimestampMixin 应提供 id/created_at/updated_at 三个字段."""

    class Timed(TimestampMixin, Base):
        __tablename__ = "_test_timed"
        name: Mapped[str] = mapped_column(String(50), nullable=False)

    columns = {c.name for c in Timed.__table__.columns}  # type: ignore[union-attr]
    assert "id" in columns
    assert "created_at" in columns
    assert "updated_at" in columns
    assert "name" in columns


def test_timestamp_mixin_creates_and_queries_sqlite() -> None:
    """在 SQLite 中实际建表、插入、查询 TimestampMixin 模型."""

    class User(TimestampMixin, Base):
        __tablename__ = "_test_users"
        username: Mapped[str] = mapped_column(String(50), nullable=False)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        u = User(username="alice")
        session.add(u)
        session.commit()
        session.refresh(u)

        assert u.id == 1
        assert u.username == "alice"
        assert isinstance(u.created_at, dt.datetime)
        assert isinstance(u.updated_at, dt.datetime)

        result = session.execute(
            select(User).where(User.username == "alice")  # type: ignore[arg-type]
        ).scalar_one()
        assert result.id == 1
        assert result.created_at == u.created_at

    Base.metadata.remove(User.__table__)  # type: ignore[arg-type]
    engine.dispose()


def test_timestamp_mixin_updates_field_on_modify() -> None:
    """更新模型后 updated_at 应变化（数据库层 onupdate 钩子）."""

    class Post(TimestampMixin, Base):
        __tablename__ = "_test_posts"
        title: Mapped[str] = mapped_column(String(100), nullable=False)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        p = Post(title="hi")
        session.add(p)
        session.commit()
        session.refresh(p)

        p.title = "hello"  # type: ignore[assignment]
        session.commit()
        session.refresh(p)

        assert p.updated_at is not None

    Base.metadata.remove(Post.__table__)  # type: ignore[arg-type]
    engine.dispose()
