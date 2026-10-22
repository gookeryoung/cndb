"""datasource M2：迁移 0a1b2c3d4e5f 往返测试（建表 / 幂等 / downgrade）."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command

from cndb.core.migrations import _build_config

REVISION = "1b2c3d4e5f60"
PREVIOUS = "e7f8a9b0c1d2"
SYNC_REVISION = "0a1b2c3d4e5f"
JOB_TABLE = "datasource_sync_job"
RUN_TABLE = "datasource_sync_run"
SESSION_TABLE = "datasource_session"
# ADR 0019：大模型连接（工作区级 → 个人级，当前提交基线 head 是 5e6f7a8b9c01）
LLM_CONFIG_REVISION = "5e6f7a8b9c01"
LLM_CONFIG_DOWN = "2c3d4e5f6a70"
LLM_CONFIG_TABLE = "datasource_llm_config"
USER_LLM_REVISION = "6a7b8c9d0e1f"
USER_LLM_TABLE = "datasource_user_llm_config"


def _upgrade(url: str, revision: str = REVISION) -> None:
    command.upgrade(_build_config(url), revision)


def _downgrade(url: str, revision: str) -> None:
    command.downgrade(_build_config(url), revision)


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        conn.close()


def _indexes(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA index_list({table})").fetchall()}  # nosec B608 - 测试内部常量
    finally:
        conn.close()


def _unique_indexes(db_path: Path, table: str) -> dict[str, int]:
    """PRAGMA index_list：索引名 → unique 标志（1=唯一索引）."""
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1]: int(row[2]) for row in conn.execute(f"PRAGMA index_list({table})").fetchall()}  # nosec B608 - 测试内部常量
    finally:
        conn.close()


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量
    finally:
        conn.close()


class TestMigration:
    def test_upgrade_creates_tables_and_indexes(self, tmp_path: Path):
        db_path = tmp_path / "mig.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)

        tables = _tables(db_path)
        assert {JOB_TABLE, RUN_TABLE} <= tables
        assert f"ix_{JOB_TABLE}_workspace_id" in _indexes(db_path, JOB_TABLE)
        assert f"ix_{JOB_TABLE}_lease_until" in _indexes(db_path, JOB_TABLE)
        assert f"ix_{RUN_TABLE}_job_id" in _indexes(db_path, RUN_TABLE)

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.datasource.models import DatasourceSyncJob, DatasourceSyncRun

        db_path = tmp_path / "mig_model.db"
        _upgrade(f"sqlite:///{db_path}")
        assert _columns(db_path, JOB_TABLE) == {column.name for column in DatasourceSyncJob.__table__.columns}
        assert _columns(db_path, RUN_TABLE) == {column.name for column in DatasourceSyncRun.__table__.columns}

    def test_downgrade_removes_tables(self, tmp_path: Path):
        db_path = tmp_path / "mig_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        tables = _tables(db_path)
        assert JOB_TABLE not in tables
        assert RUN_TABLE not in tables

    def test_reupgrade_after_downgrade(self, tmp_path: Path):
        db_path = tmp_path / "mig_round.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, PREVIOUS)
        _upgrade(url)
        assert {JOB_TABLE, RUN_TABLE} <= _tables(db_path)

    def test_upgrade_idempotent_when_tables_exist(self, tmp_path: Path):
        """create_all 时代已建过表的库：stamp 到上一版再 upgrade，迁移跳过建表不报错."""
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.datasource.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "mig_idempotent.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), PREVIOUS)
        _upgrade(url)
        assert {JOB_TABLE, RUN_TABLE} <= _tables(db_path)


class TestSessionMigration:
    def test_upgrade_adds_session_table_and_job_columns(self, tmp_path: Path):
        db_path = tmp_path / "mig_session.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)

        assert SESSION_TABLE in _tables(db_path)
        job_columns = _columns(db_path, JOB_TABLE)
        assert {"session_id", "rate_limit_ms"} <= job_columns
        assert f"ix_{JOB_TABLE}_session_id" in _indexes(db_path, JOB_TABLE)

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.datasource.models import DatasourceSession

        db_path = tmp_path / "mig_session_model.db"
        _upgrade(f"sqlite:///{db_path}")
        assert _columns(db_path, SESSION_TABLE) == {column.name for column in DatasourceSession.__table__.columns}

    def test_downgrade_removes_session_artifacts(self, tmp_path: Path):
        db_path = tmp_path / "mig_session_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url)
        _downgrade(url, SYNC_REVISION)

        assert SESSION_TABLE not in _tables(db_path)
        job_columns = _columns(db_path, JOB_TABLE)
        assert "session_id" not in job_columns
        assert "rate_limit_ms" not in job_columns

    def test_upgrade_idempotent_after_create_all(self, tmp_path: Path):
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.datasource.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "mig_session_idempotent.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), SYNC_REVISION)
        _upgrade(url)
        assert SESSION_TABLE in _tables(db_path)


class TestLlmConfigMigration:
    """历史迁移 5e6f7a8b9c01：工作区级连接表（已由个人配置迁移取代，但升级链仍要能重放）."""

    def test_upgrade_creates_table_and_indexes(self, tmp_path: Path):
        db_path = tmp_path / "mig_llm.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, LLM_CONFIG_REVISION)

        assert LLM_CONFIG_TABLE in _tables(db_path)
        indexes = _indexes(db_path, LLM_CONFIG_TABLE)
        assert f"ix_{LLM_CONFIG_TABLE}_workspace_id" in indexes
        assert f"ix_{LLM_CONFIG_TABLE}_created_by" in indexes

    def test_schema_matches_historical_columns(self, tmp_path: Path):
        db_path = tmp_path / "mig_llm_model.db"
        _upgrade(f"sqlite:///{db_path}", LLM_CONFIG_REVISION)
        assert _columns(db_path, LLM_CONFIG_TABLE) == {
            "id",
            "created_at",
            "updated_at",
            "workspace_id",
            "created_by",
            "base_url",
            "model",
            "api_key",
            "system_prompt",
        }

    def test_downgrade_removes_table(self, tmp_path: Path):
        db_path = tmp_path / "mig_llm_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, LLM_CONFIG_REVISION)
        _downgrade(url, LLM_CONFIG_DOWN)
        assert LLM_CONFIG_TABLE not in _tables(db_path)

    def test_reupgrade_after_downgrade(self, tmp_path: Path):
        db_path = tmp_path / "mig_llm_round.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, LLM_CONFIG_REVISION)
        _downgrade(url, LLM_CONFIG_DOWN)
        _upgrade(url, LLM_CONFIG_REVISION)
        assert LLM_CONFIG_TABLE in _tables(db_path)

    def test_upgrade_idempotent_after_create_all(self, tmp_path: Path):
        """create_all 时代已建过表的库：stamp 到上一版再 upgrade，迁移跳过建表不报错."""
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.datasource.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "mig_llm_idempotent.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), LLM_CONFIG_DOWN)
        _upgrade(url, LLM_CONFIG_REVISION)
        assert LLM_CONFIG_TABLE in _tables(db_path)


class TestUserLlmConfigMigration:
    """ADR 0019：大模型连接从工作区级改为个人级（建表 / 数据搬迁 / downgrade / 幂等）."""

    def _insert_old_row(
        self,
        db_path: Path,
        *,
        workspace_id: int,
        created_by: int | None,
        base_url: str,
        model: str,
        api_key: str = "",
        system_prompt: str = "",
    ) -> None:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO datasource_llm_config "
                "(workspace_id, created_by, base_url, model, api_key, system_prompt) VALUES (?, ?, ?, ?, ?, ?)",
                (workspace_id, created_by, base_url, model, api_key, system_prompt),
            )
            conn.commit()
        finally:
            conn.close()

    def test_upgrade_creates_table_with_unique_user_index(self, tmp_path: Path):
        db_path = tmp_path / "mig_user_llm.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, USER_LLM_REVISION)

        assert USER_LLM_TABLE in _tables(db_path)
        assert LLM_CONFIG_TABLE not in _tables(db_path)
        indexes = _unique_indexes(db_path, USER_LLM_TABLE)
        assert indexes.get(f"ix_{USER_LLM_TABLE}_user_id") == 1

    def test_schema_matches_models(self, tmp_path: Path):
        from cndb.plugins.llm.models import LlmUserConfig as UserLlmConfig

        db_path = tmp_path / "mig_user_llm_model.db"
        _upgrade(f"sqlite:///{db_path}", USER_LLM_REVISION)
        assert _columns(db_path, USER_LLM_TABLE) == {column.name for column in UserLlmConfig.__table__.columns}

    def test_migrates_old_rows_by_created_by(self, tmp_path: Path):
        """旧表按 created_by 搬到新表；同一用户多行取 id 最小一条，created_by 为空丢弃."""
        db_path = tmp_path / "mig_user_llm_data.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, LLM_CONFIG_REVISION)
        # 用户 7 有两条旧连接（第二条应被忽略）、用户 8 一条、无归属一条
        self._insert_old_row(db_path, workspace_id=1, created_by=7, base_url="https://a", model="model-a")
        self._insert_old_row(
            db_path,
            workspace_id=2,
            created_by=7,
            base_url="https://b",
            model="model-b",
            api_key="enc:v1:keep",
            system_prompt="自定义",
        )
        self._insert_old_row(db_path, workspace_id=3, created_by=8, base_url="https://c", model="model-c")
        self._insert_old_row(db_path, workspace_id=4, created_by=None, base_url="https://orphan", model="model-x")

        _upgrade(url, USER_LLM_REVISION)

        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT user_id, base_url, model, api_key, system_prompt FROM datasource_user_llm_config ORDER BY user_id"
            ).fetchall()
        finally:
            conn.close()
        assert rows == [
            (7, "https://a", "model-a", "", ""),
            (8, "https://c", "model-c", "", ""),
        ]
        assert LLM_CONFIG_TABLE not in _tables(db_path)

    def test_downgrade_recreates_old_table(self, tmp_path: Path):
        db_path = tmp_path / "mig_user_llm_down.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, USER_LLM_REVISION)
        _downgrade(url, LLM_CONFIG_REVISION)

        assert USER_LLM_TABLE not in _tables(db_path)
        assert LLM_CONFIG_TABLE in _tables(db_path)
        indexes = _unique_indexes(db_path, LLM_CONFIG_TABLE)
        assert indexes.get(f"ix_{LLM_CONFIG_TABLE}_workspace_id") == 1
        # 数据不可逆：downgrade 后旧表为空（注释已说明）
        assert _columns(db_path, LLM_CONFIG_TABLE) >= {
            "workspace_id",
            "created_by",
            "base_url",
            "model",
            "api_key",
            "system_prompt",
        }

    def test_reupgrade_after_downgrade(self, tmp_path: Path):
        db_path = tmp_path / "mig_user_llm_round.db"
        url = f"sqlite:///{db_path}"
        _upgrade(url, USER_LLM_REVISION)
        _downgrade(url, LLM_CONFIG_REVISION)
        _upgrade(url, USER_LLM_REVISION)
        assert USER_LLM_TABLE in _tables(db_path)
        assert LLM_CONFIG_TABLE not in _tables(db_path)

    def test_upgrade_idempotent_after_create_all(self, tmp_path: Path):
        """create_all 时代已建过新表的库：stamp 到上一版再 upgrade，迁移跳过建表不报错."""
        from sqlalchemy import create_engine

        import cndb.core.events
        import cndb.plugins.accounts.models
        import cndb.plugins.datasource.models
        import cndb.plugins.tables.models
        import cndb.plugins.workspaces.models  # noqa: F401
        from cndb.models.base import Base

        db_path = tmp_path / "mig_user_llm_idempotent.db"
        url = f"sqlite:///{db_path}"
        engine = create_engine(url)
        Base.metadata.create_all(engine)
        engine.dispose()

        command.stamp(_build_config(url), LLM_CONFIG_REVISION)
        _upgrade(url, USER_LLM_REVISION)
        assert USER_LLM_TABLE in _tables(db_path)
