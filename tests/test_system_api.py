"""system_api（/api/v1/admin 备份/恢复端点）测试.

覆盖：inspect 端点 schema 领先判定字段、restore 端点 mode 透传与降级报告、
非法 mode 拒绝、非管理员权限拦截。

注意：restore 端点内部按 settings.DATABASE_URL 恢复，测试用 monkeypatch
把该 URL 重定向到临时库，避免触碰真实用户数据库。
"""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cndb.cli.backup import create_backup
from cndb.core.config import settings
from cndb.plugins.accounts.models import User


def _setup_src_sqlite(tmp_path: Path) -> Path:
    """创建有数据的源 SQLite 库（模拟业务表）."""
    db = tmp_path / "src.db"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO customers (name) VALUES ('A'), ('B');
        """
    )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def superuser_headers(client: TestClient, auth_headers: dict[str, str], db) -> dict[str, str]:
    """把已登录的 testuser 提升为 superuser（token 每请求查库，即时生效）."""
    user = db.query(User).filter(User.username == "testuser").one()
    user.is_superuser = True
    db.commit()
    return auth_headers


def _make_archive(tmp_path: Path) -> Path:
    """用独立源库生成 native 备份归档."""
    src_db = _setup_src_sqlite(tmp_path)
    archive = tmp_path / "backup.tar.gz"
    create_backup(
        output=archive,
        mode="native",
        database_url=f"sqlite:///{src_db}",
        upload_dir=tmp_path / "uploads",  # 不存在 → 附件未包含
        include_uploads=True,
    )
    return archive


def _upload(client: TestClient, headers: dict[str, str], archive: Path, **fields: str):
    """以 multipart 上传归档并附加表单字段."""
    data = io.BytesIO(archive.read_bytes())
    return client.post(
        "/api/v1/admin/restore",
        headers=headers,
        files={"file": ("backup.tar.gz", data, "application/gzip")},
        data=fields,
    )


# ── 权限 ──────────────────────────────────────────────


def test_admin_restore_requires_superuser(client: TestClient, auth_headers: dict[str, str], tmp_path: Path) -> None:
    archive = _make_archive(tmp_path)
    r = _upload(client, auth_headers, archive)
    assert r.status_code == 403


# ── restore/inspect ───────────────────────────────────


def test_admin_restore_inspect_returns_schema_fields(
    client: TestClient, superuser_headers: dict[str, str], tmp_path: Path
) -> None:
    """inspect 端点返回 manifest + schema_known/backup_ahead 判定字段.

    裸建表源库无 alembic_version → schema_version 为空 → 不判领先。
    """
    archive = _make_archive(tmp_path)
    r = client.post(
        "/api/v1/admin/restore/inspect",
        headers=superuser_headers,
        files={"file": ("backup.tar.gz", io.BytesIO(archive.read_bytes()), "application/gzip")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == "1"
    assert body["database"]["backup_mode"] == "native"
    assert body["schema_known"] is True  # 空 schema_version（旧版备份）不算领先
    assert body["backup_ahead"] is False


# ── restore ───────────────────────────────────────────


def test_admin_restore_with_sqlalchemy_mode(
    client: TestClient,
    superuser_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """restore 端点透传 mode：native 归档以 sqlalchemy 模式恢复到临时库."""
    archive = _make_archive(tmp_path)
    target = tmp_path / "target.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{target}")

    r = _upload(client, superuser_headers, archive, mode="sqlalchemy", force="true")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    # customers 是裸建表（不在 ORM metadata），交集导入跳过 → 降级报告回传前端
    assert body["loss_report"] is not None
    assert body["loss_report"]["skipped_tables"] == ["customers"]
    assert "customers" in body["loss_report"]["summary"]

    # 目标库恢复为当前 schema（settings.DATABASE_URL 指向的临时库），
    # 被跳过的裸表不出现 —— 降级裁剪语义与报告一致
    conn = sqlite3.connect(str(target))
    try:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
        }
        assert "customers" not in tables
        assert "alembic_version" in tables  # sqlalchemy 恢复后补写版本标记
    finally:
        conn.close()


def test_admin_restore_invalid_mode_rejected(
    client: TestClient,
    superuser_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """非法 mode → 400（restore_backup 的 RestoreError 转换）."""
    archive = _make_archive(tmp_path)
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{tmp_path / 'target.db'}")

    r = _upload(client, superuser_headers, archive, mode="bogus")
    assert r.status_code == 400
    assert "无效的恢复模式" in r.json()["detail"]


# ── 权限边界 ──────────────────────────────────────────


def test_admin_endpoints_require_login(client: TestClient, tmp_path: Path) -> None:
    """未携带 token 访问 admin 端点 → 401."""
    assert client.get("/api/v1/admin/info").status_code == 401
    assert client.post("/api/v1/admin/backup").status_code == 401

    archive = _make_archive(tmp_path)
    data = io.BytesIO(archive.read_bytes())
    r = client.post(
        "/api/v1/admin/restore/inspect",
        files={"file": ("backup.tar.gz", data, "application/gzip")},
    )
    assert r.status_code == 401


# ── admin/info ────────────────────────────────────────


def test_admin_info_returns_system_fields(client: TestClient, superuser_headers: dict[str, str]) -> None:
    """登录用户可读系统信息（版本 / 数据库 / 数据目录 / 时区）."""
    r = client.get("/api/v1/admin/info", headers=superuser_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["app_name"]
    assert body["app_version"]
    assert body["database_url"]
    assert "data_dir" in body
    assert "upload_dir" in body
    assert body["timezone"] == "UTC"


# ── admin/backup ──────────────────────────────────────


def test_admin_backup_archive_download(
    client: TestClient,
    superuser_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """archive 格式备份 → 200 返回 tar.gz 下载流（Content-Disposition 带文件名）."""
    src_db = _setup_src_sqlite(tmp_path)
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{src_db}")
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")

    r = client.post(
        "/api/v1/admin/backup",
        headers=superuser_headers,
        json={"format": "archive", "include_uploads": False, "mode": "native"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/gzip"
    assert "attachment" in r.headers["content-disposition"]
    assert "cndb-backup-" in r.headers["content-disposition"]
    assert len(r.content) > 0
    # gzip 魔数校验
    assert r.content[:2] == b"\x1f\x8b"


def test_admin_backup_rejects_directory_format(client: TestClient, superuser_headers: dict[str, str]) -> None:
    """Web 端不支持 directory 格式 → 400 并提示使用 CLI."""
    r = client.post(
        "/api/v1/admin/backup",
        headers=superuser_headers,
        json={"format": "directory"},
    )
    assert r.status_code == 400
    assert "cndb backup" in r.json()["detail"]


def test_admin_backup_error_maps_to_400(
    client: TestClient,
    superuser_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_backup 抛 BackupError → 400 转换."""
    from cndb.cli.backup import BackupError
    from cndb.core import system_api

    def _boom(**_kwargs: object) -> None:
        raise BackupError("模拟备份失败")

    monkeypatch.setattr(system_api, "create_backup", _boom)
    r = client.post("/api/v1/admin/backup", headers=superuser_headers, json={"format": "archive"})
    assert r.status_code == 400
    assert "模拟备份失败" in r.json()["detail"]


# ── restore 错误分支 ──────────────────────────────────


def test_admin_restore_inspect_invalid_archive_rejected(client: TestClient, superuser_headers: dict[str, str]) -> None:
    """上传损坏的归档 → inspect 返回 400."""
    r = client.post(
        "/api/v1/admin/restore/inspect",
        headers=superuser_headers,
        files={"file": ("broken.tar.gz", io.BytesIO(b"not-a-tar"), "application/gzip")},
    )
    assert r.status_code == 400
    assert r.json()["detail"]


def test_admin_restore_unexpected_error_maps_to_500(
    client: TestClient,
    superuser_headers: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """restore_backup 抛非 RestoreError 异常 → 500（避免裸 500 无信息）."""
    from cndb.core import system_api

    archive = _make_archive(tmp_path)

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("数据库引擎爆炸")

    monkeypatch.setattr(system_api, "restore_backup", _boom)
    r = _upload(client, superuser_headers, archive)
    assert r.status_code == 500
    assert "数据库引擎爆炸" in r.json()["detail"]
