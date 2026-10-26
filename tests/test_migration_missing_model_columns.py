"""迁移回归测试 —— f7a8b9c0d1e2（add_missing_model_columns）+ a4b5c6d7e8f9（drop_dataview_public_share）.

背景：accounts_user.role / tables_dataview.is_public / tables_dataview.public_slug /
tables_tablepermission.manage_data_role 四列历史上只加在 ORM 模型上，迁移链从未
覆盖。旧库（典型：恢复 0.2.0 native 备份后 upgrade head）永远缺列，业务查询
报 "no such column"（表现为恢复后所有数据表内容无法显示）→ 由 f7a8b9c0d1e2
一次性补齐。

随后 is_public / public_slug 承载的「视图匿名公开分享」按 ADR 0003 决策 D5
整体移除，由 a4b5c6d7e8f9 在同一链上删除这两列与唯一索引。因此本文件同时钉住
两端语义：

- 历史迁移仍会加列（历史迁移不可改写，升级链要能从头重放）
- head 处这两列不存在（ORM 元数据也不再声明，schema 自愈层不会把它们加回来）

关键约束：
- 幂等加列/删列（旧库可能经 create_all 时代建表，列的存在性不一致）
- 目标表整体不存在时跳过（由启动 create_all 兜底建表）
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic.script import ScriptDirectory

from cndb.core.migrations import _build_config, upgrade_to_head

PRE_REVISION = "e5f6a7b8c9d0"  # f7a8b9c0d1e2 之前的 head（0.2.0 时代 schema）
ADD_COLUMNS_REVISION = "f7a8b9c0d1e2"  # 历史加列迁移：补齐四列
DROP_SHARE_REVISION = "a4b5c6d7e8f9"  # 删列迁移：移除视图匿名公开分享两列
DROP_SHARE_DOWN = "e6a7b8c9d0e1"  # 删列迁移的 down_revision
VISIBILITY_REVISION = "b5c6d7e8f9a0"  # 视图可见性三档迁移
HEAD_REVISION = "c4d5e6f7a8b9"  # 同步运行进度列（ADR 0037，当前 head）


def _upgrade_to(engine_target: str, revision: str) -> None:
    cfg = _build_config(engine_target)
    from alembic import command

    command.upgrade(cfg, revision)


def _downgrade_to(engine_target: str, revision: str) -> None:
    cfg = _build_config(engine_target)
    from alembic import command

    command.downgrade(cfg, revision)


def _current_head() -> str:
    cfg = _build_config("sqlite:///:memory:")
    return str(ScriptDirectory.from_config(cfg).get_current_head())


def _columns(db_path: Path, table: str) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}  # nosec B608 - 测试内部常量表名
    finally:
        conn.close()


def _index_flags(db_path: Path, table: str) -> dict[str, int]:
    """PRAGMA index_list：索引名 → unique 标志（1=唯一索引）."""
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[1]: r[2] for r in conn.execute(f"PRAGMA index_list({table})").fetchall()}  # nosec B608 - 测试内部常量表名
    finally:
        conn.close()


class TestAddMissingModelColumns:
    """历史迁移 f7a8b9c0d1e2：补齐 ORM 有而迁移链缺失的四列."""

    def test_old_schema_db_upgrade_adds_all_columns(self, tmp_path: Path) -> None:
        """0.2.0 时代库（stamp 在 e5f6a7b8c9d0）升到 f7a8b9c0d1e2 时四列全部补齐.

        注意目标 revision 显式停在历史迁移上：head 处 is_public / public_slug
        会被 a4b5c6d7e8f9 删除（见 TestDropDataviewPublicShare），此处只验证
        历史迁移本身的加列语义不被回改。
        """
        db_path = tmp_path / "old.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        for table, col in (
            ("accounts_user", "role"),
            ("tables_dataview", "is_public"),
            ("tables_tablepermission", "manage_data_role"),
        ):
            assert col not in _columns(db_path, table)

        _upgrade_to(url, ADD_COLUMNS_REVISION)

        assert "role" in _columns(db_path, "accounts_user")
        assert {"is_public", "public_slug"} <= _columns(db_path, "tables_dataview")
        assert "manage_data_role" in _columns(db_path, "tables_tablepermission")

    def test_upgrade_is_idempotent_when_columns_preexist(self, tmp_path: Path) -> None:
        """create_all 时代旧库已含部分列 → upgrade head 不报 duplicate column."""
        db_path = tmp_path / "partial.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        # 模拟 create_all 时代已补过其中的列（带各自默认值）
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("ALTER TABLE accounts_user ADD COLUMN role VARCHAR(32) NOT NULL DEFAULT 'user'")
            conn.execute(
                "ALTER TABLE tables_tablepermission ADD COLUMN manage_data_role VARCHAR(16) NOT NULL DEFAULT ''"
            )
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 不抛 duplicate column 即通过

        assert "role" in _columns(db_path, "accounts_user")
        assert "manage_data_role" in _columns(db_path, "tables_tablepermission")
        # 幂等：重复 upgrade 仍成功
        upgrade_to_head(url)

    def test_upgrade_creates_unique_index_when_column_preexists(self, tmp_path: Path) -> None:
        """列已存在但唯一索引缺失 → 升到 f7a8b9c0d1e2 补建 public_slug 唯一索引.

        create_all 时代升级库可能带列无索引（索引历史遗漏），迁移按索引名
        幂等判断，与加列逻辑独立生效；PRAGMA unique 标志为 1。
        """
        db_path = tmp_path / "idx_missing.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("ALTER TABLE tables_dataview ADD COLUMN public_slug VARCHAR(12)")
            conn.commit()
        finally:
            conn.close()

        _upgrade_to(url, ADD_COLUMNS_REVISION)

        flags = _index_flags(db_path, "tables_dataview")
        assert flags["ix_tables_dataview_public_slug"] == 1  # unique=1

    def test_upgrade_skips_missing_tables(self, tmp_path: Path) -> None:
        """目标表整体不存在（legacy 库无业务表）→ 迁移跳过不失败.

        该场景由启动期 create_all 按完整 ORM 元数据兜底建表，本迁移只负责
        存量表的缺列（test_migrations_heal.py 验证自愈层兜住同场景）。
        """
        db_path = tmp_path / "legacy.db"
        url = f"sqlite:///{db_path.as_posix()}"
        # 手工建一个最小库：只有 alembic_version stamp 在 e5f6a7b8c9d0
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            conn.execute("INSERT INTO alembic_version VALUES (?)", (PRE_REVISION,))
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 不抛 no such table 即通过

        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        assert version == _current_head()

    def test_upgrade_preserves_existing_data(self, tmp_path: Path) -> None:
        """加列后存量数据保留，新列取 server_default 值."""
        db_path = tmp_path / "data.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO accounts_user (username, email, nickname, hashed_password, is_active, is_superuser) "
                "VALUES ('legacy', 'legacy@example.com', '旧用户', 'x', 1, 0)"
            )
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)

        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute("SELECT username, role FROM accounts_user").fetchone()
        finally:
            conn.close()
        assert row == ("legacy", "user")

    def test_downgrade_removes_columns(self, tmp_path: Path) -> None:
        """downgrade 回 PRE_REVISION：四列全部消失（幂等，缺列时跳过）."""
        db_path = tmp_path / "down.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        upgrade_to_head(url)

        _downgrade_to(url, PRE_REVISION)

        assert "role" not in _columns(db_path, "accounts_user")
        assert "manage_data_role" not in _columns(db_path, "tables_tablepermission")
        assert "is_public" not in _columns(db_path, "tables_dataview")
        assert "public_slug" not in _columns(db_path, "tables_dataview")

    def test_downgrade_idempotent(self, tmp_path: Path) -> None:
        """已降级的库重复 downgrade 不报错（缺列跳过）."""
        db_path = tmp_path / "down2.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        upgrade_to_head(url)

        _downgrade_to(url, PRE_REVISION)
        _downgrade_to(url, PRE_REVISION)  # 第二次：列已不存在，跳过

        assert "role" not in _columns(db_path, "accounts_user")


class TestDropDataviewPublicShare:
    """删列迁移 a4b5c6d7e8f9：移除视图匿名公开分享所需的列与索引."""

    def test_head_drops_columns_and_index(self, tmp_path: Path) -> None:
        """0.2.0 时代库一路升到 head → 分享两列与唯一索引均不存在，其余列保留."""
        db_path = tmp_path / "head.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)

        upgrade_to_head(url)

        assert "is_public" not in _columns(db_path, "tables_dataview")
        assert "public_slug" not in _columns(db_path, "tables_dataview")
        assert "ix_tables_dataview_public_slug" not in _index_flags(db_path, "tables_dataview")
        # 同批补列不受影响
        assert "role" in _columns(db_path, "accounts_user")
        assert "manage_data_role" in _columns(db_path, "tables_tablepermission")
        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        assert version == _current_head() == HEAD_REVISION

    def test_upgrade_is_idempotent(self, tmp_path: Path) -> None:
        """列本就不存在的库 → 删列跳过，重复 upgrade head 不报错.

        构造：手工建一个只有 a4b5 之上所需最小结构、且 tables_dataview 不含
        is_public/public_slug 的库（模拟 create_all 时代从未有过这两列），
        stamp 在 DROP_SHARE_DOWN 后 upgrade。
        """
        db_path = tmp_path / "idem.db"
        url = f"sqlite:///{db_path.as_posix()}"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            conn.execute("INSERT INTO alembic_version VALUES (?)", (DROP_SHARE_DOWN,))
            conn.execute("CREATE TABLE tables_dataview (id INTEGER PRIMARY KEY, name VARCHAR(255))")
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 两列都不存在 → 全部跳过
        upgrade_to_head(url)  # 重复 upgrade 仍成功

        assert "is_public" not in _columns(db_path, "tables_dataview")
        assert "public_slug" not in _columns(db_path, "tables_dataview")

    def test_downgrade_restores_columns_and_index(self, tmp_path: Path) -> None:
        """downgrade 一步：恢复两列与 public_slug 唯一索引，再 upgrade 可重放."""
        db_path = tmp_path / "restore.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        upgrade_to_head(url)

        _downgrade_to(url, DROP_SHARE_DOWN)

        assert {"is_public", "public_slug"} <= _columns(db_path, "tables_dataview")
        assert _index_flags(db_path, "tables_dataview")["ix_tables_dataview_public_slug"] == 1

        # 幂等 + 可重放：再次 downgrade 跳过（列已存在），再 upgrade 删列成功
        _downgrade_to(url, DROP_SHARE_DOWN)
        upgrade_to_head(url)
        assert "is_public" not in _columns(db_path, "tables_dataview")

    def test_missing_table_is_skipped(self, tmp_path: Path) -> None:
        """无业务表的 legacy 库：升级/降级本迁移均跳过，不抛 no such table."""
        db_path = tmp_path / "legacy_share.db"
        url = f"sqlite:///{db_path.as_posix()}"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            conn.execute("INSERT INTO alembic_version VALUES (?)", (DROP_SHARE_DOWN,))
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 表不存在 → 跳过
        _downgrade_to(url, DROP_SHARE_DOWN)  # 表不存在 → 跳过

        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        finally:
            conn.close()
        assert version == DROP_SHARE_DOWN


class TestAddDataviewVisibility:
    """可见性三档迁移 b5c6d7e8f9a0（ADR 0003 D1/D2/D3）.

    既有二元语义（``owner_id IS NULL`` = 公共）映射为三档：
    存量 → ``table``（继承表权限，零行为变化）、其余 → ``private``（仅创建者）；
    同时换命名空间唯一键、把 owner_id 外键由 CASCADE 改为 SET NULL，
    并新建 ``shared`` 档授权名单表。
    """

    @staticmethod
    def _seed_views(db_path: Path) -> None:
        """造三条存量视图：公共默认 / 他人个人 / 表 owner 个人."""
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute(
                "INSERT INTO accounts_user (id, username, email, nickname, hashed_password, is_active, is_superuser) "
                "VALUES (7, 'u7', 'u7@example.com', 'u7', 'x', 1, 0)"
            )
            cols = (
                "created_at, updated_at, table_id, owner_id, name, view_type, filter_type, "
                'filters, sortings, field_options, field_order, view_options, is_default, "order"'
            )
            rows = [
                (1, "NULL", "全部", 1),
                (2, "7", "我的待办", 0),
                (3, "7", "A的私有视角", 0),
            ]
            for rid, owner, name, is_default in rows:
                conn.execute(
                    f"INSERT INTO tables_dataview (id, {cols}) VALUES "  # nosec B608 - 测试内部常量
                    f"({rid}, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 10, {owner}, '{name}', 'grid', 'AND', "
                    f"'[]', '[]', '{{}}', '[]', '{{}}', {is_default}, {rid})"
                )
            conn.commit()
        finally:
            conn.close()

    def test_existing_views_map_to_three_tiers(self, tmp_path: Path) -> None:
        """存量映射：公共/默认视图 → table（scope 0）；本人视图 → private（scope = owner_id）."""
        db_path = tmp_path / "map.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        self._seed_views(db_path)

        upgrade_to_head(url)

        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute("SELECT id, name, visibility, scope_key FROM tables_dataview ORDER BY id").fetchall()
        finally:
            conn.close()
        assert rows == [
            (1, "全部", "table", 0),
            (2, "我的待办", "private", 7),
            (3, "A的私有视角", "private", 7),
        ]

    def test_unique_key_and_fk_are_rebuilt(self, tmp_path: Path) -> None:
        """唯一键换成 (table_id, scope_key, name)；owner_id 外键改为 SET NULL."""
        db_path = tmp_path / "uq.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        self._seed_views(db_path)
        upgrade_to_head(url)

        conn = sqlite3.connect(str(db_path))
        try:
            ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name='tables_dataview'").fetchone()[0]
            grant_sql = conn.execute("SELECT sql FROM sqlite_master WHERE name='tables_dataviewpermission'").fetchone()[
                0
            ]
        finally:
            conn.close()
        assert "uniq_table_view_scope_name" in ddl
        assert "uniq_table_view_name" not in ddl
        assert "ON DELETE SET NULL" in ddl
        assert grant_sql is not None and "uniq_view_grant_subject" in grant_sql

    def test_deleting_creator_keeps_view_as_orphan(self, tmp_path: Path) -> None:
        """D3：删账号后视图仍在（owner_id 置空 = 孤儿），而不是被级联删除."""
        db_path = tmp_path / "orphan.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        self._seed_views(db_path)
        upgrade_to_head(url)

        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("DELETE FROM accounts_user WHERE id = 7")
            conn.commit()
            rows = conn.execute(
                "SELECT id, visibility, scope_key, owner_id FROM tables_dataview ORDER BY id"
            ).fetchall()
        finally:
            conn.close()
        assert rows == [
            (1, "table", 0, None),
            (2, "private", 7, None),
            (3, "private", 7, None),
        ]

    def test_upgrade_skips_incomplete_stub_table(self, tmp_path: Path) -> None:
        """表存在但非完整业务形状（缺 table_id/owner_id/is_default）→ 只补列与索引.

        这类存根（create_all 前的半成品库、测试夹具）没有 owner_id / table_id，
        映射 UPDATE 与唯一键/外键重建都必须跳过 —— 否则报 no such column。
        """
        db_path = tmp_path / "stub_vis.db"
        url = f"sqlite:///{db_path.as_posix()}"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            conn.execute("INSERT INTO alembic_version VALUES (?)", (DROP_SHARE_REVISION,))
            conn.execute("CREATE TABLE tables_dataview (id INTEGER PRIMARY KEY, name VARCHAR(255))")
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)  # 缺 owner_id → 映射与约束重建跳过，不抛 no such column

        assert {"visibility", "scope_key"} <= _columns(db_path, "tables_dataview")
        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name='tables_dataview'").fetchone()[0]
        finally:
            conn.close()
        assert version == HEAD_REVISION
        assert "uniq_table_view_scope_name" not in ddl  # 未在存根上造引用缺列的约束

        _downgrade_to(url, DROP_SHARE_REVISION)  # 同样跳过约束重建

        assert "visibility" not in _columns(db_path, "tables_dataview")
        assert "scope_key" not in _columns(db_path, "tables_dataview")

    def test_upgrade_is_idempotent(self, tmp_path: Path) -> None:
        """重复 upgrade head 不报 duplicate column / constraint already exists."""
        db_path = tmp_path / "idem_vis.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        self._seed_views(db_path)

        upgrade_to_head(url)
        upgrade_to_head(url)

        assert {"visibility", "scope_key"} <= _columns(db_path, "tables_dataview")

    def test_upgrade_skips_missing_table(self, tmp_path: Path) -> None:
        """无业务表的 legacy 库 → 跳过全部工作，仍能推进版本号."""
        db_path = tmp_path / "legacy_vis.db"
        url = f"sqlite:///{db_path.as_posix()}"
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
            conn.execute("INSERT INTO alembic_version VALUES (?)", (DROP_SHARE_REVISION,))
            conn.commit()
        finally:
            conn.close()

        upgrade_to_head(url)

        conn = sqlite3.connect(str(db_path))
        try:
            version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
            grant = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE name = 'tables_dataviewpermission'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert version == HEAD_REVISION
        assert grant == 0

    def test_downgrade_restores_binary_model(self, tmp_path: Path) -> None:
        """downgrade：列与索引消失、授权表删除、唯一键与外键回退."""
        db_path = tmp_path / "down_vis.db"
        url = f"sqlite:///{db_path.as_posix()}"
        _upgrade_to(url, PRE_REVISION)
        self._seed_views(db_path)
        upgrade_to_head(url)

        _downgrade_to(url, DROP_SHARE_REVISION)

        assert "visibility" not in _columns(db_path, "tables_dataview")
        assert "scope_key" not in _columns(db_path, "tables_dataview")
        conn = sqlite3.connect(str(db_path))
        try:
            grant = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE name = 'tables_dataviewpermission'"
            ).fetchone()[0]
            ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name='tables_dataview'").fetchone()[0]
        finally:
            conn.close()
        assert grant == 0
        assert "uniq_table_view_name" in ddl
        assert "ON DELETE CASCADE" in ddl

        # 幂等 + 可重放
        _downgrade_to(url, DROP_SHARE_REVISION)
        upgrade_to_head(url)
        assert "visibility" in _columns(db_path, "tables_dataview")
