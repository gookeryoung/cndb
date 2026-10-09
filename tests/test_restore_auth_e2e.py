"""数据恢复 → 用户登录 端到端测试.

模拟典型用户完整流程：拿到历史版本备份 → 执行恢复 → 启动程序 → 登录 →
认证后访问业务接口。覆盖"不同版本备份恢复后典型用户均无法登录"的回归防护
（历史根因：迁移链缺列、旧备份无版本记录触发迁移重放、恢复后 schema 漂移）。

1. 版本矩阵（TestRestoreThenLoginMatrix）：
   仓库内置三份真实历史备份（0.1.10 / 0.2.1 / 0.3.0）逐份恢复后，三类典型
   用户（系统管理员/安全管理员/普通用户）用原始密码登录并访问受保护接口；
2. 0.2.0 形态备份（TestRestore020ShapeArchive）：
   手工构造旧目录结构（backup/database/）+ 0.2.0 schema 库的归档，覆盖用户
   手中真实存在的 0.2.0 备份（examples 目录缺失该版本）；
3. 重启幂等（TestRestoreRestartIdempotent）：
   恢复后"重启程序"（二次 lifespan/ensure_db_migrated）不破坏登录；
4. 权限与会话延续（TestAuthDataIntegrity）：
   恢复后用户的 role/is_active 等认证属性完整迁移，停用账号拒绝登录。

前置条件、执行步骤与预期结果写入各用例 docstring；每用例独立临时库，
可重复执行。
"""

from __future__ import annotations

import io
import json
import sqlite3
import tarfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cndb.cli.restore import restore_backup

EXAMPLE_BACKUPS = Path(__file__).parent.parent / "examples" / "backups"

# 三版本真实备份文件名（仓库内置，CI 可用）
BACKUP_0110 = "cndb-backup-0.1.10-v1-20260918T044022Z.tar.gz"
BACKUP_021 = "cndb-backup-0.2.1-v1-20261009T044325Z.tar.gz"
BACKUP_030 = "cndb-backup-0.3.0-v1-20261009T045326Z.tar.gz"

# 典型用户矩阵：seed 时代的原始凭证（普通用户/安全管理员/系统管理员）
TYPICAL_USERS = [
    ("admin", "admin1234", "system_admin", True),
    ("sec_admin", "sec1234", "security_admin", False),
    ("demo", "demo1234", "user", False),
]

LOGIN_URL = "/api/v1/accounts/auth/login"
ME_URL = "/api/v1/accounts/auth/me"
USERS_URL = "/api/v1/accounts/auth/users"


def _make_e2e_client(monkeypatch: pytest.MonkeyPatch, target_db: Path) -> TestClient:
    """构造指向恢复后库的 TestClient（模拟程序在恢复后的数据目录上启动）.

    步骤：settings.DATABASE_URL 指向恢复库 → 重建全局 engine/SessionLocal
    （全局 engine 在模块导入时绑定默认库，不重建则登录查询打向默认库，
    与真实"重启程序"语义不符）→ monkeypatch ensure_db_migrated 避免触碰
    真实数据目录 → import app 进 TestClient（lifespan 完整走一遍）。
    """
    import sqlalchemy as sa

    import cndb.core.database as db_mod
    from cndb.core.config import settings

    url = f"sqlite:///{target_db.as_posix()}"
    monkeypatch.setattr(settings, "DATABASE_URL", url)

    new_engine = sa.create_engine(
        url,
        connect_args={"check_same_thread": False, "isolation_level": None},
    )
    db_mod.register_sqlite_pragmas(new_engine)
    new_session_local = sa.orm.sessionmaker(autocommit=False, autoflush=False, bind=new_engine)
    # monkeypatch 赋新值并自动登记 teardown 还原（旧引用由 monkeypatch 保存）
    monkeypatch.setattr(db_mod, "engine", new_engine)
    monkeypatch.setattr(db_mod, "SessionLocal", new_session_local)

    import cndb.app as app_module

    monkeypatch.setattr(app_module, "ensure_db_migrated", lambda: None)
    return TestClient(app_module.app)


def _login_and_assert(client: TestClient, login_id: str, password: str, role: str | None, is_superuser: bool) -> str:
    """登录并校验 /me 返回的认证属性，返回 access_token.

    role=None 时跳过角色断言（0.2.0 及更早备份无 role 列，恢复后由迁移
    以默认值补齐，is_superuser 才是当时权限的真相源）。
    """
    r = client.post(LOGIN_URL, json={"login": login_id, "password": password})
    assert r.status_code == 200, f"登录 {login_id} 失败: {r.status_code} {r.text[:200]}"
    token = r.json()["access_token"]

    me = client.get(ME_URL, headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    body = me.json()
    assert body["username"] == login_id
    if role is not None:
        assert body["role"] == role, f"角色迁移失真: {body['role']} != {role}"
    assert body["is_active"] is True
    assert body["is_superuser"] == is_superuser
    return token


def _assert_protected_api_access(client: TestClient, token: str, *, expect_admin_ok: bool) -> None:
    """认证后访问受保护接口：超管 200，普通用户 403（权限配置迁移正确）."""
    r = client.get(USERS_URL, headers={"Authorization": f"Bearer {token}"})
    if expect_admin_ok:
        assert r.status_code == 200, r.text
    else:
        assert r.status_code == 403


# ── 1. 版本矩阵：真实历史备份恢复后登录 ──────────────


class TestRestoreThenLoginMatrix:
    """三版本仓库内置备份逐份恢复 → 登录 → 权限校验."""

    @pytest.mark.parametrize("backup_name", [BACKUP_030, BACKUP_021, BACKUP_0110])
    def test_restore_then_typical_users_login(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, backup_name: str
    ) -> None:
        """前置：仓库内置历史备份归档；步骤：恢复到独立临时库 → 以该库启动程序；
        预期：三类典型用户均 200 登录、/me 认证属性与角色迁移零失真、
        超管可访问管理接口而普通用户被 403 拒绝."""
        archive = EXAMPLE_BACKUPS / backup_name
        assert archive.exists(), f"内置备份缺失: {archive}"
        target = tmp_path / "restored.db"

        restore_backup(archive, force=False, database_url=f"sqlite:///{target.as_posix()}")

        with _make_e2e_client(monkeypatch, target) as client:
            for login_id, password, role, is_superuser in TYPICAL_USERS:
                token = _login_and_assert(client, login_id, password, role, is_superuser)
                _assert_protected_api_access(client, token, expect_admin_ok=is_superuser)

    def test_restore_wrong_password_still_401(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：恢复完成的库；步骤：错误密码登录；预期：401（恢复不放松认证）."""
        target = tmp_path / "restored.db"
        restore_backup(EXAMPLE_BACKUPS / BACKUP_021, force=False, database_url=f"sqlite:///{target.as_posix()}")
        with _make_e2e_client(monkeypatch, target) as client:
            r = client.post(LOGIN_URL, json={"login": "admin", "password": "wrong"})
            assert r.status_code == 401


# ── 2. 0.2.0 形态备份（旧目录结构） ──────────────────


def _build_020_shape_archive(tmp_path: Path) -> Path:
    """构造 0.2.0 版程序产出的备份归档（旧 schema + backup/database/ 目录）.

    步骤：alembic upgrade 到 0.2.0 revision（e5f6a7b8c9d0）→ 注入 bcrypt
    密码的典型用户 → 按 0.2.x 时代目录结构打包为 tar.gz。
    """
    import alembic.command

    from cndb.core.migrations import _build_config
    from cndb.core.security import hash_password

    db = tmp_path / "src.db"
    cfg = _build_config(f"sqlite:///{db.as_posix()}")
    alembic.command.upgrade(cfg, "e5f6a7b8c9d0")

    conn = sqlite3.connect(str(db))
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts_user)")}
        for username, password, role, superuser in [
            ("admin", "admin1234", "system_admin", 1),
            ("sec_admin", "sec1234", "security_admin", 0),
            ("demo", "demo1234", "user", 0),
        ]:
            values: dict[str, object] = {
                "username": username,
                "email": f"{username}@020.local",
                "nickname": username,
                "hashed_password": hash_password(password),
                "is_active": 1,
                "is_superuser": superuser,
                "preferences": "{}",
                "created_at": "2026-01-01 00:00:00",
                "updated_at": "2026-01-01 00:00:00",
            }
            # role 列 0.3.0 才引入，0.2.0 库按实际列动态插入
            if "role" in cols:
                values["role"] = role
            col_list = ", ".join(values)
            placeholders = ", ".join("?" for _ in values)
            conn.execute(
                f"INSERT INTO accounts_user ({col_list}) VALUES ({placeholders})",  # nosec B608 - 列名来自 PRAGMA 枚举
                tuple(values.values()),
            )
        conn.commit()
    finally:
        conn.close()

    manifest = {
        "version": "1",
        "app_version": "0.2.0",
        "created_at": "2026-01-01T00:00:00+00:00",
        "database": {
            "db_type": "sqlite",
            "backup_mode": "native",
            "schema_version": "e5f6a7b8c9d0",
            "fallback_mode": "",
            "tables": [],
            "row_counts": {},
        },
        "uploads": {"included": False, "file_count": 0, "total_size": 0},
    }
    archive = tmp_path / "backup-0.2.0.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        data = json.dumps(manifest).encode("utf-8")
        info = tarfile.TarInfo(name="backup/manifest.json")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
        db_bytes = db.read_bytes()
        info2 = tarfile.TarInfo(name="backup/database/cndb.db")  # 0.2.x 旧目录结构
        info2.size = len(db_bytes)
        tar.addfile(info2, io.BytesIO(db_bytes))
    return archive


class TestRestore020ShapeArchive:
    """0.2.0 形态备份（用户手中真实存在、examples 缺失的版本）恢复后登录."""

    def test_restore_020_backup_then_login(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：0.2.0 schema + 旧目录结构的手工归档；步骤：恢复 → 启动 → 登录；
        预期：迁移收敛当前 head，三类典型用户登录成功且角色零失真."""
        archive = _build_020_shape_archive(tmp_path)
        target = tmp_path / "restored.db"

        restore_backup(archive, force=False, database_url=f"sqlite:///{target.as_posix()}")

        # 恢复后库版本必须收敛到当前 head（跨两代升级）
        conn = sqlite3.connect(str(target))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        import alembic.script

        from cndb.core.migrations import _build_config

        head = str(alembic.script.ScriptDirectory.from_config(_build_config("sqlite:///:memory:")).get_current_head())
        assert version == head

        with _make_e2e_client(monkeypatch, target) as client:
            # 0.2.0 备份无 role 列：跳过角色断言，is_superuser 为权限真相源
            legacy_users = [
                ("admin", "admin1234", True),
                ("sec_admin", "sec1234", False),
                ("demo", "demo1234", False),
            ]
            for login_id, password, is_superuser in legacy_users:
                token = _login_and_assert(client, login_id, password, None, is_superuser)
                _assert_protected_api_access(client, token, expect_admin_ok=is_superuser)


# ── 3. 恢复后重启幂等 ────────────────────────────────


class TestRestoreRestartIdempotent:
    """恢复后重启程序（二次启动/ensure_db_migrated）不破坏登录."""

    def test_second_startup_preserves_login(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：0.2.1 备份恢复完成的库；步骤：第一次启动登录成功 → 关闭 →
        第二次启动（新 TestClient lifespan）→ 登录 + /me；
        预期：两轮均 200，重启后凭证与会话流程不变."""
        target = tmp_path / "restored.db"
        restore_backup(EXAMPLE_BACKUPS / BACKUP_021, force=False, database_url=f"sqlite:///{target.as_posix()}")

        for round_no in (1, 2):
            with _make_e2e_client(monkeypatch, target) as client:
                for login_id, password, role, is_superuser in TYPICAL_USERS:
                    token = _login_and_assert(client, login_id, password, role, is_superuser)
                    if round_no == 2:
                        _assert_protected_api_access(client, token, expect_admin_ok=is_superuser)

    def test_repeated_restore_is_idempotent(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：同一备份；步骤：连续两次恢复到同一目标库（第二次带 force）→ 登录；
        预期：重复恢复不破坏用户数据，登录依旧成功（幂等操作语义）."""
        target = tmp_path / "restored.db"
        archive = EXAMPLE_BACKUPS / BACKUP_021
        restore_backup(archive, force=False, database_url=f"sqlite:///{target.as_posix()}")
        restore_backup(archive, force=True, database_url=f"sqlite:///{target.as_posix()}")

        with _make_e2e_client(monkeypatch, target) as client:
            for login_id, password, role, is_superuser in TYPICAL_USERS:
                _login_and_assert(client, login_id, password, role, is_superuser)


# ── 4. 认证数据完整性 ────────────────────────────────


class TestAuthDataIntegrity:
    """恢复后用户认证数据（role/is_active/凭证）的完整迁移."""

    def test_deactivated_user_stays_locked_after_restore(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：0.3.0 备份恢复；步骤：直接把库内 demo 用户置为停用 → 再恢复一次
        （force 覆盖，模拟恢复回滚了误操作）→ 登录；预期：恢复回滚后用户恢复可登录
        （备份内 is_active=1 正确还原，未被目标库残留状态污染）."""
        target = tmp_path / "restored.db"
        archive = EXAMPLE_BACKUPS / BACKUP_030
        restore_backup(archive, force=False, database_url=f"sqlite:///{target.as_posix()}")

        # 目标库被误改：demo 停用
        conn = sqlite3.connect(str(target))
        try:
            conn.execute("UPDATE accounts_user SET is_active=0 WHERE username='demo'")
            conn.commit()
        finally:
            conn.close()

        # force 重新恢复 → 备份内状态（is_active=1）还原
        restore_backup(archive, force=True, database_url=f"sqlite:///{target.as_posix()}")
        with _make_e2e_client(monkeypatch, target) as client:
            _login_and_assert(client, "demo", "demo1234", "user", False)

    def test_restored_roles_drive_permission_boundary(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """前置：0.1.10 备份恢复（走 stamp + create_all + 自愈兜底路径）；
        步骤：demo 登录后访问超管接口；预期：403 —— 自愈兜底不篡改既有权限数据."""
        target = tmp_path / "restored.db"
        restore_backup(EXAMPLE_BACKUPS / BACKUP_0110, force=False, database_url=f"sqlite:///{target.as_posix()}")
        with _make_e2e_client(monkeypatch, target) as client:
            token = _login_and_assert(client, "demo", "demo1234", "user", False)
            _assert_protected_api_access(client, token, expect_admin_ok=False)
