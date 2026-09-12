"""accounts 插件集成测试."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User


@pytest.fixture
def _db_engine(tmp_path: Path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db(_db_engine):
    SessionLocal = sessionmaker(bind=_db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


class TestUserModel:
    def test_set_and_check_password(self, db):
        user = User(username="alice", email="a@b.c", nickname="A")
        user.set_password("hunter2")
        assert user.hashed_password != "hunter2"
        assert user.check_password("hunter2") is True
        assert user.check_password("wrong") is False


class TestAuthAPI:
    def test_register_success(self, client):
        r = client.post("/api/v1/accounts/auth/register", json={"username": "alice", "password": "passw0rd"})
        assert r.status_code == 201
        assert r.json()["username"] == "alice"
        assert "hashed_password" not in r.json()

    def test_register_duplicate_username(self, client):
        client.post("/api/v1/accounts/auth/register", json={"username": "dup", "password": "passw0rd"})
        r = client.post("/api/v1/accounts/auth/register", json={"username": "dup", "password": "other123"})
        assert r.status_code == 400

    def test_login_success(self, client):
        client.post("/api/v1/accounts/auth/register", json={"username": "luke", "password": "force42"})
        r = client.post("/api/v1/accounts/auth/login", json={"login": "luke", "password": "force42"})
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_login_wrong_password(self, client):
        client.post("/api/v1/accounts/auth/register", json={"username": "bad", "password": "force42"})
        r = client.post("/api/v1/accounts/auth/login", json={"login": "bad", "password": "wrongpw"})
        assert r.status_code == 401

    def test_me_with_jwt(self, client):
        client.post("/api/v1/accounts/auth/register", json={"username": "me", "password": "passw0rd"})
        token = client.post("/api/v1/accounts/auth/login", json={"login": "me", "password": "passw0rd"}).json()[
            "access_token"
        ]
        r = client.get("/api/v1/accounts/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json()["username"] == "me"

    def test_me_no_auth(self, client):
        r = client.get("/api/v1/accounts/auth/me")
        assert r.status_code == 401

    def test_me_invalid_token(self, client):
        r = client.get("/api/v1/accounts/auth/me", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401
