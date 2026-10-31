"""pytest 全局 fixtures — 被各测试文件共享.

优化：session 级共享内存 SQLite + function 级 DELETE FROM 隔离,
避免每个测试都 drop_all/create_all 的开销.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from cndb.api.deps import get_db
from cndb.core.config import settings
from cndb.models.base import Base

# 测试不启动「用量快照」后台刷新线程（ADR 0024）：它用独立 SessionLocal 连真实
# 数据库文件，而测试库是进程内内存 SQLite（StaticPool 单连接），跨线程写会污染。
# 需要验证线程行为的用例自行构造 StorageSnapshotRefresher。
settings.STORAGE_SNAPSHOT_ENABLED = False
# 同理不进「帮助图示」后台重建线程（ADR 0030）：图示走请求期懒生成，
# 线程行为由 tests/test_help_figures.py 直接构造 FigureRefresher 验证。
settings.HELP_FIGURES_ENABLED = False


@pytest.fixture(scope="session")
def db_engine():
    """session 级共享内存 SQLite engine — 每个 worker 只建一次 schema.

    注意：StaticPool 单连接意味着所有 Session 共用同一物理事务，
    因此导入后台任务必须同步执行（见 _sync_import_tasks）。
    """
    settings.AUTH_ENABLED = True
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False, "isolation_level": None},
        poolclass=StaticPool,
    )
    # 确保所有模型已注册到 Base.metadata
    import cndb.core.events
    import cndb.plugins.accounts.models
    import cndb.plugins.analytics.models
    import cndb.plugins.change_requests.models
    import cndb.plugins.datasource.models
    import cndb.plugins.documents.models
    import cndb.plugins.files.models
    import cndb.plugins.issues.models
    import cndb.plugins.pipeline.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def _session_factory(db_engine):
    """绑定 sessionmaker — 仅 session 级 engine 生命周期内有效."""
    return sessionmaker(bind=db_engine, autocommit=False, autoflush=False)


@pytest.fixture(autouse=True)
def _clear_process_caches():
    """每个用例前清空进程内缓存.

    测试共用同一个内存库，workspace/table 等 id 会在不同用例间重复，
    而缓存键正是基于这些 id —— 不清会跨用例串数据（曾导致 filter/sort 用例偶发失败）。
    """
    from cndb.core.cache import list_cache, meta_cache, search_cache

    list_cache.clear()
    meta_cache.clear()
    search_cache.clear()
    yield
    list_cache.clear()
    meta_cache.clear()
    search_cache.clear()


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
def _sync_import_tasks(monkeypatch_session: pytest.MonkeyPatch):
    """导入后台任务在测试中同步执行.

    测试库是 StaticPool 单连接内存库，所有 Session 共用同一物理事务：
    后台线程 session 的 rollback/close 会回滚整个物理事务，吃掉请求
    session 尚未提交的写入，导致 create_import_task 的 db.refresh 偶发
    "Could not refresh instance"（CI 慢机放大窗口，xdist 下偶发失败）。
    同步执行消除线程并发，任务流程与状态机语义不变。
    """
    import cndb.plugins.tables.routers.bulk_import as bulk_import_router
    from cndb.plugins.tables.services.importing import import_tasks

    def _run_sync(
        db_session_factory: Callable[[], Session],
        task_id: int,
        *,
        phase: str = "execute",
    ) -> None:
        # 与 import_tasks.run_task_in_background._worker 的分发逻辑保持一致
        session = db_session_factory()
        try:
            if phase == "analyze":
                import_tasks.analyze_import_task(session, task_id)
            elif phase == "reanalyze":
                import_tasks.reanalyze_import_task(session, task_id)
            else:
                import_tasks.execute_import_task(session, task_id)
        finally:
            session.close()

    monkeypatch_session.setattr(bulk_import_router, "run_task_in_background", _run_sync)


@pytest.fixture(scope="session", autouse=True)
def _sync_governance_tasks(monkeypatch_session: pytest.MonkeyPatch):
    """治理后台任务在测试中同步执行（原因同 _sync_import_tasks：StaticPool 单连接）.

    治理路由模块在 RED 阶段尚不存在，容错导入：存在才打补丁。
    """
    from contextlib import suppress

    with suppress(ImportError):
        import cndb.plugins.tables.routers.governance as governance_router
        from cndb.plugins.tables.services.governance import tasks as gov_tasks

        def _run_sync(
            db_session_factory: Callable[[], Session],
            task_id: int,
        ) -> None:
            session = db_session_factory()
            try:
                gov_tasks.execute_governance_task(session, task_id)
            finally:
                session.close()

        monkeypatch_session.setattr(governance_router, "run_governance_task_in_background", _run_sync)


@pytest.fixture(scope="session", autouse=True)
def _sync_pipeline_tasks(monkeypatch_session: pytest.MonkeyPatch):
    """流水线后台运行在测试中同步执行（原因同 _sync_import_tasks：StaticPool 单连接）."""
    from contextlib import suppress

    with suppress(ImportError):
        import cndb.plugins.pipeline.routers.workflows as pipeline_router
        from cndb.plugins.pipeline.services import runner

        def _run_sync(
            db_session_factory: Callable[[], Session],
            run_id: int,
        ) -> None:
            session = db_session_factory()
            try:
                runner.execute_pipeline_run(session, run_id)
            finally:
                session.close()

        monkeypatch_session.setattr(pipeline_router, "run_pipeline_in_background", _run_sync)
        # 事件触发走 services.triggers 的模块级引用，同样换成同步桩
        from cndb.plugins.pipeline.services import triggers as pipeline_triggers

        monkeypatch_session.setattr(pipeline_triggers, "run_pipeline_in_background", _run_sync)


@pytest.fixture(scope="session", autouse=True)
def _isolate_upload_dir(tmp_path_factory, monkeypatch_session):
    """把 settings.UPLOAD_DIR 重定向到 session 级临时目录.

    备份/恢复流程默认读写 settings.UPLOAD_DIR，未显式传参的测试会触碰
    真实用户附件目录（清空重建导致附件丢失）。全局隔离，xdist 下每
    worker 各自独立临时目录，顺带消除并行文件锁冲突。
    """
    upload_dir = tmp_path_factory.mktemp("uploads")
    monkeypatch_session.setattr(settings, "UPLOAD_DIR", upload_dir)


@pytest.fixture(scope="session", autouse=True)
def _isolate_docs_dir(tmp_path_factory, monkeypatch_session):
    """把文档外存根目录重定向到 session 级临时目录（原因同 _isolate_upload_dir）.

    默认根目录跟随 DATABASE_URL 落在 data/docs，测试里直接写会污染真实数据；
    且文外存路径按 doc_id 分目录，跨用例 id 重复会互相覆盖。
    """
    from cndb.plugins.documents.services import content as content_service

    docs_dir = tmp_path_factory.mktemp("docs")
    monkeypatch_session.setattr(content_service, "_DOCS_DIR", docs_dir)


def _clear_dir(path: Path) -> None:
    """清空目录内容（保留目录本身），不可删除的条目忽略."""
    if not path.is_dir():
        return
    for child in path.iterdir():
        with suppress(OSError):
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)


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
    """autouse：每个测试后等后台线程结束，再清空全部表 + 重置自增计数器.

    磁盘侧同样按用例清理：workspace/document id 会随 sqlite_sequence 归零，
    上一条用例留下的 ``UPLOAD_DIR/{ws_id}``、``docs/{doc_id}`` 会被下一条用例
    按同名 id 统计进用量（曾导致「空工作区已用空间不为 0」）。
    """
    yield
    # 等待 import/治理/流水线后台线程完成，避免残留线程与清表冲突
    from cndb.plugins.pipeline.services.runner import join_background_threads as join_pipeline
    from cndb.plugins.tables.services.governance.tasks import join_background_threads as join_gov
    from cndb.plugins.tables.services.importing.import_tasks import join_background_threads

    join_background_threads(timeout=10)
    join_gov(timeout=10)
    join_pipeline(timeout=10)
    with db_engine.connect() as conn:
        # DELETE 比 DROP+CREATE 快一个量级；schema 在 session 级 engine 上只建一次
        for table in reversed(Base.metadata.sorted_tables):
            with suppress(Exception):
                conn.execute(text(f"DELETE FROM {table.name}"))
        with suppress(Exception):
            conn.execute(text("DELETE FROM sqlite_sequence WHERE name NOT LIKE 'sqlite_%'"))
        conn.commit()

    from cndb.plugins.documents.services import content as content_service

    _clear_dir(Path(settings.UPLOAD_DIR))
    _clear_dir(Path(content_service._DOCS_DIR))


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
            json={"username": "testuser", "email": "t@example.com", "password": "passw0rd"},
        )
        assert r.status_code in (200, 201), f"Register failed: {r.text}"
        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "testuser", "password": "passw0rd"},
        )
    assert r.status_code == 200, f"Login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
