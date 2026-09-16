"""pytest 全局 fixtures — 被各测试文件共享.

优化：session 级共享内存 SQLite + function 级 DELETE FROM 隔离,
避免每个测试都 drop_all/create_all 的开销.
"""

from __future__ import annotations

from contextlib import suppress

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from cndb.api.deps import get_db
from cndb.core.config import settings
from cndb.models.base import Base


@pytest.fixture(scope="session")
def db_engine():
    """session 级共享内存 SQLite engine — 每个 worker 只建一次 schema."""
    settings.AUTH_ENABLED = True
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # 确保所有模型已注册到 Base.metadata
    import cndb.plugins.accounts.models
    import cndb.plugins.reports.models
    import cndb.plugins.tables.models
    import cndb.plugins.wechat_auth.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def _session_factory(db_engine):
    """绑定 sessionmaker — 仅 session 级 engine 生命周期内有效."""
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture
def db(_session_factory):
    """function 级 session — 每个测试独立 session."""
    session = _session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _cleanup_tables(db_engine):
    """autouse：每个测试后彻底清表 + 重置自增计数器."""
    yield
    with db_engine.connect() as conn:
        # 先 DROP TABLE，彻底清理所有数据 + 自增计数器
        for table in reversed(Base.metadata.sorted_tables):
            with suppress(Exception):
                conn.execute(text(f"DROP TABLE IF EXISTS {table.name}"))
        conn.commit()
        # 重建 schema
        Base.metadata.create_all(bind=conn)
        conn.commit()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def auth_headers(client, db):
    """注册 + 登录获取 token."""
    r = client.post(
        "/api/v1/accounts/auth/register",
        json={"username": "testuser", "email": "t@t.com", "password": "passw0rd"},
    )
    assert r.status_code in (200, 201), f"Register failed: {r.text}"
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "testuser", "password": "passw0rd"},
    )
    assert r.status_code == 200, f"Login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
