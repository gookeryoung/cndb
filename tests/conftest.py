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


@pytest.fixture(scope="session", autouse=True)
def _skip_lifespan_migrations(monkeypatch_session):
    """测试中 TestClient 每次启动都触发 lifespan 的 alembic 迁移（~0.6s/次），
    且目标是真实 settings.DATABASE_URL 而非测试内存库 —— 直接跳过，
    schema 由 db_engine 的 create_all 负责。"""
    import importlib

    app_module = importlib.import_module("cndb.app")
    monkeypatch_session.setattr(app_module, "ensure_db_migrated", lambda: None)


@pytest.fixture(scope="session")
def monkeypatch_session():
    m = pytest.MonkeyPatch()
    yield m
    m.undo()


@pytest.fixture(scope="session", autouse=True)
def _fast_bcrypt(monkeypatch_session):
    """bcrypt 默认 cost(12) 单次哈希 ~0.2s，auth_headers 每测试 register+login
    要付 2-3 次 —— 测试环境降到 cost=4，保持真实哈希/校验流程不变。"""
    import bcrypt

    orig_gensalt = bcrypt.gensalt
    monkeypatch_session.setattr(bcrypt, "gensalt", lambda *a, **kw: orig_gensalt(4))


@pytest.fixture(scope="session", autouse=True)
def _isolate_upload_dir(tmp_path_factory, monkeypatch_session):
    """把 settings.UPLOAD_DIR 重定向到 session 级临时目录.

    备份/恢复流程默认读写 settings.UPLOAD_DIR，未显式传参的测试会触碰
    真实用户附件目录（清空重建导致附件丢失）。全局隔离，xdist 下每
    worker 各自独立临时目录，顺带消除并行文件锁冲突。
    """
    upload_dir = tmp_path_factory.mktemp("uploads")
    monkeypatch_session.setattr(settings, "UPLOAD_DIR", upload_dir)


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
    """autouse：每个测试后等后台线程结束，再清空全部表 + 重置自增计数器."""
    yield
    # 等待 import_tasks 中所有后台线程完成，避免残留线程与清表冲突
    from cndb.plugins.tables.services.importing.import_tasks import join_background_threads

    join_background_threads(timeout=10)
    with db_engine.connect() as conn:
        # DELETE 比 DROP+CREATE 快一个量级；schema 在 session 级 engine 上只建一次
        for table in reversed(Base.metadata.sorted_tables):
            with suppress(Exception):
                conn.execute(text(f"DELETE FROM {table.name}"))
        with suppress(Exception):
            conn.execute(text("DELETE FROM sqlite_sequence WHERE name NOT LIKE 'sqlite_%'"))
        conn.commit()


@pytest.fixture(scope="session")
def _session_client():
    """session 级 TestClient 单例 — lifespan 只进一次（迁移已在别处跳过），
    避免每个测试重建 portal/客户端. 依赖覆盖由 client fixture 按测试切换."""
    from cndb.app import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(db, _session_client):
    """每个测试切换 get_db 覆盖到当前测试的 session，用毕移除并清 cookie."""
    from cndb.app import app

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    try:
        yield _session_client
    finally:
        # 只移除本 fixture 注册的键（app 是全局单例，clear() 会误伤其他覆盖）
        app.dependency_overrides.pop(get_db, None)
        # 单例客户端跨测试复用，清掉上一测试残留的会话 cookie
        _session_client.cookies.clear()


@pytest.fixture
def auth_headers(client, db):
    """登录获取 token — 先尝试登录，不存在再注册."""
    # 先尝试直接登录（用户可能已存在）
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": "testuser", "password": "passw0rd"},
    )
    if r.status_code != 200:
        # 用户不存在，注册
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
