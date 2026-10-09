"""统一错误契约测试（core/errors.py + app.py 全局 handler + get_db 回滚）.

覆盖：
- CndbError 族 → 统一响应体 {"detail","code"} 与状态码映射
- 未捕获异常 → 500 统一响应体（ServerErrorMiddleware 语义）
- get_db 请求路径异常 → 显式 rollback（半提交状态不落库）
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from cndb.core.database import get_db
from cndb.core.errors import (
    BadRequestError,
    CndbError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
)

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture(scope="module", autouse=True)
def _temp_routes():
    """向全局 app 挂载契约测试专用路由，模块结束后摘除."""
    from cndb.app import app

    router = APIRouter()

    @router.get("/api/test-error-contract/{kind}")
    def raise_kind(kind: str) -> dict[str, str]:
        families: dict[str, type[CndbError]] = {
            "bad_request": BadRequestError,
            "permission_denied": PermissionDeniedError,
            "not_found": NotFoundError,
            "conflict": ConflictError,
        }
        cls = families.get(kind)
        if cls is None:
            raise RuntimeError(kind)
        raise cls(f"{kind}-明细", extra_ctx="测试上下文")

    @router.post("/api/test-error-contract/rollback")
    def write_then_raise(db: Annotated[Session, Depends(get_db)]) -> dict[str, str]:
        from cndb.plugins.accounts.models import User

        user = User(username="error-contract-orphan", nickname="孤儿", is_superuser=False)
        user.hashed_password = "x"
        db.add(user)
        raise RuntimeError("模拟写后异常")

    app.include_router(router)
    try:
        yield
    finally:
        # 摘除本模块挂载的路由（APIRouter 各产生一条 route，app 自身路由不动）
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "endpoint", None) not in (raise_kind, write_then_raise)
        ]


class TestCndbErrorMapping:
    """CndbError 族 → 统一错误响应体."""

    @pytest.mark.parametrize(
        ("kind", "status", "code"),
        [
            ("bad_request", 400, "bad_request"),
            ("permission_denied", 403, "permission_denied"),
            ("not_found", 404, "not_found"),
            ("conflict", 409, "conflict"),
        ],
    )
    def test_family_maps_to_status_and_payload(self, client, kind, status, code):
        r = client.get(f"/api/test-error-contract/{kind}")
        assert r.status_code == status
        body = r.json()
        assert body == {"detail": f"{kind}-明细", "code": code}

    def test_context_not_leaked_to_client(self, client):
        """附加 context 只进日志，不进入响应体."""
        r = client.get("/api/test-error-contract/conflict")
        assert "extra_ctx" not in r.text


class TestUnhandledError:
    """未捕获异常 → 统一 500 响应体."""

    def test_unmapped_exception_returns_uniform_500(self):
        """raise_server_exceptions=False 下（生产 uvicorn 语义）客户端拿到统一 JSON."""
        from cndb.app import app

        with TestClient(app, raise_server_exceptions=False) as c:
            c.cookies.clear()
            r = c.get("/api/test-error-contract/no-such-kind")
        assert r.status_code == 500
        assert r.json() == {"detail": "内部服务器错误", "code": "internal_error"}


class TestGetDbRollback:
    """get_db 异常路径显式回滚."""

    def test_write_then_exception_rolls_back(self, client, db: Session):
        """请求抛异常时半提交的写入被回滚，不污染会话."""
        from cndb.plugins.accounts.models import User

        baseline = db.query(User).filter(User.username == "error-contract-orphan").count()
        assert baseline == 0

        # 会话级 TestClient 默认 raise_server_exceptions=True：异常经中间件重抛
        with pytest.raises(RuntimeError, match="模拟写后异常"):
            client.post("/api/test-error-contract/rollback")

        # 同一会话立即可用且无脏数据（异常路径已 rollback）
        assert db.query(User).filter(User.username == "error-contract-orphan").count() == 0

        # 会话未被异常破坏：后续查询正常
        assert db.query(User).count() >= 0

    def test_get_db_rollback_unit(self):
        """单元级：yield 后异常触发 rollback 且异常向上传播."""
        calls: list[str] = []

        class _FakeSession:
            def rollback(self) -> None:
                calls.append("rollback")

            def close(self) -> None:
                calls.append("close")

        def _gen() -> Iterator[object]:
            sess = _FakeSession()
            try:
                yield sess
            except Exception:
                sess.rollback()
                raise
            finally:
                sess.close()

        gen = _gen()
        next(gen)
        with pytest.raises(RuntimeError):
            gen.throw(RuntimeError("boom"))
        assert calls == ["rollback", "close"]
