"""accounts 插件集成测试."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import ApiToken, User, generate_api_token, hash_api_token


@pytest.fixture
def _db_engine(tmp_path: Path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine


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

    def test_api_token_issue_returns_plain_once(self, db):
        user = User(username="bob", nickname="B")
        user.set_password("pw12345")
        db.add(user)
        db.commit()
        db.refresh(user)
        obj, plain = ApiToken.issue(db, user, "my-token")
        assert plain.startswith("cndb_")
        assert len(plain) == 45  # cndb_(5) + token_hex(20)=40 hex
        assert obj.prefix == plain[:12]
        assert obj.digest == hash_api_token(plain)
        db_token = db.get(ApiToken, obj.id)
        assert db_token.digest != plain


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


class TestApiTokenAPI:
    def _login(self, client, username="tester", password="passw0rd"):
        client.post("/api/v1/accounts/auth/register", json={"username": username, "password": password})
        return client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password}).json()[
            "access_token"
        ]

    def test_issue_token_and_list(self, client, db):
        jwt = self._login(client)
        r1 = client.post("/api/v1/accounts/tokens", headers={"Authorization": f"Bearer {jwt}"}, json={"name": "ci"})
        assert r1.status_code == 201
        plain = r1.json()["token"]
        assert plain.startswith("cndb_")
        r2 = client.get("/api/v1/accounts/tokens", headers={"Authorization": f"Bearer {jwt}"})
        assert r2.status_code == 200
        assert len(r2.json()) == 1
        db_token = db.query(ApiToken).first()
        assert db_token.digest == hash_api_token(plain)

    def test_revoke_token(self, client, db):
        jwt = self._login(client)
        plain = client.post(
            "/api/v1/accounts/tokens", headers={"Authorization": f"Bearer {jwt}"}, json={"name": "rv"}
        ).json()["token"]
        token_id = db.query(ApiToken).first().id
        r = client.delete(f"/api/v1/accounts/tokens/{token_id}", headers={"Authorization": f"Bearer {jwt}"})
        assert r.status_code == 204
        r = client.get("/api/v1/accounts/auth/me", headers={"Authorization": f"Bearer {plain}"})
        assert r.status_code == 401

    def test_me_via_api_token(self, client):
        jwt = self._login(client)
        plain = client.post(
            "/api/v1/accounts/tokens", headers={"Authorization": f"Bearer {jwt}"}, json={"name": "tk"}
        ).json()["token"]
        r = client.get("/api/v1/accounts/auth/me", headers={"Authorization": f"Bearer {plain}"})
        assert r.status_code == 200
        assert r.json()["username"] == "tester"

    def test_api_token_updates_last_used(self, client, db):
        jwt = self._login(client)
        plain = client.post(
            "/api/v1/accounts/tokens", headers={"Authorization": f"Bearer {jwt}"}, json={"name": "lu"}
        ).json()["token"]
        at = db.query(ApiToken).first()
        assert at.last_used_at is None
        client.get("/api/v1/accounts/auth/me", headers={"Authorization": f"Bearer {plain}"})
        db.refresh(at)
        assert at.last_used_at is not None
        assert isinstance(at.last_used_at, datetime)

    def test_cannot_revoke_others_token(self, client, db):
        client.post("/api/v1/accounts/auth/register", json={"username": "u1", "password": "passw0rd"})
        client.post("/api/v1/accounts/auth/register", json={"username": "u2", "password": "passw0rd"})
        jwt1 = client.post("/api/v1/accounts/auth/login", json={"login": "u1", "password": "passw0rd"}).json()[
            "access_token"
        ]
        client.post("/api/v1/accounts/tokens", headers={"Authorization": f"Bearer {jwt1}"}, json={"name": "tk1"})
        u1_token_id = db.query(ApiToken).first().id
        jwt2 = client.post("/api/v1/accounts/auth/login", json={"login": "u2", "password": "passw0rd"}).json()[
            "access_token"
        ]
        r = client.delete(f"/api/v1/accounts/tokens/{u1_token_id}", headers={"Authorization": f"Bearer {jwt2}"})
        assert r.status_code == 404

    def test_generate_and_hash_are_deterministic(self):
        token = generate_api_token()
        assert token.startswith("cndb_")
        digest = hash_api_token(token)
        assert len(digest) == 64
        assert hash_api_token(token) == digest
