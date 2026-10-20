"""datasource：``cndb sync batch-kline`` 批量建任务 CLI 单测.

策略：临时 SQLite + 真实「自选股」表（复用 seed 建表），直接调用 ``cli.sync`` 的
函数（不联网）；覆盖分批切片 / 只取自选 / 市场前缀过滤 / 上限收敛 / 错峰调度 /
幂等更新 / 旧批次裁剪 / dry-run 不写库 / 缺表缺列报错。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from cndb.cli.seed.stock_quotes import _seed_stock_quotes
from cndb.cli.sync import (
    KLINE_SERIES,
    MAX_BATCH_SIZE,
    _parse_series,
    _print_batch_kline,
    _series_mapping,
    _staggered_at,
    cmd_batch_kline,
)
from cndb.core.config import settings

META = [
    {"股票代码": "sh600519", "股票名称": "贵州茅台", "市场": "A股", "行业": "食品饮料", "是否自选": True},
    {"股票代码": "sz000001", "股票名称": "平安银行", "市场": "A股", "行业": "银行", "是否自选": True},
    {"股票代码": "sh601398", "股票名称": "工商银行", "市场": "A股", "行业": "银行", "是否自选": False},
    {"股票代码": "hk00700", "股票名称": "腾讯控股", "市场": "港股", "行业": "互联网", "是否自选": True},
    {"股票代码": "usAAPL", "股票名称": "苹果", "市场": "美股", "行业": "硬件", "是否自选": True},
]


def _ns(**kwargs: Any) -> argparse.Namespace:
    base: dict[str, Any] = {
        "workspace": "数据源示例",
        "table": "自选股",
        "market": "ALL",
        "batch_size": MAX_BATCH_SIZE,
        "series": "day_qfq",
        "include_unselected": False,
        "prefix": "自选股K线",
        "schedule": "daily",
        "at": "17:30",
        "stagger_minutes": 2,
        "rate_limit_ms": 400,
        "prune": False,
        "dry_run": False,
        "json": False,
    }
    base.update(kwargs)
    return argparse.Namespace(**base)


@pytest.fixture
def batch_env(tmp_path: Path, monkeypatch) -> dict[str, Any]:
    """临时库 + 用户 / 工作区 / 自选股表（含 5 行，3 只自选 A 股等）."""
    import cndb.plugins.accounts.models
    import cndb.plugins.datasource.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401
    from cndb.models.base import Base
    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import Workspace

    db_path = tmp_path / "batch.db"
    monkeypatch.setattr(settings, "DATABASE_URL", f"sqlite:///{db_path}")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    db: Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)()
    try:
        user = User(username="batch_cli", email="batch_cli@example.com", nickname="分批 CLI 测试")
        user.set_password("pass1234")
        db.add(user)
        db.commit()
        db.refresh(user)

        ws = Workspace(name="数据源示例", created_by_id=user.id)
        db.add(ws)
        db.commit()
        db.refresh(ws)

        datasets = tmp_path / "datasets" / "工作区-数据源示例"
        datasets.mkdir(parents=True)
        (datasets / "自选股.json").write_text(json.dumps(META, ensure_ascii=False), encoding="utf-8")
        created, dt = _seed_stock_quotes(db, engine, ws, user.id, tmp_path / "datasets")
        assert created == 1 and dt is not None

        yield {"db": db, "engine": engine, "ws": ws, "table": dt, "user": user}
    finally:
        db.close()
        engine.dispose()


def _jobs(db: Session) -> list[Any]:
    from cndb.plugins.datasource.models import DatasourceSyncJob

    db.expire_all()
    return list(db.execute(select(DatasourceSyncJob).order_by(DatasourceSyncJob.name)).scalars())


class TestHelpers:
    def test_parse_series_dedupes_and_rejects_unknown(self):
        assert _parse_series("day_qfq, week_qfq,day_qfq") == ["day_qfq", "week_qfq"]
        with pytest.raises(SystemExit, match="未知序列"):
            _parse_series("day_qfq,bogus")
        with pytest.raises(SystemExit, match="未知序列"):
            _parse_series(" ")

    def test_staggered_at_wraps_midnight(self):
        assert _staggered_at("17:30", 0) == "17:30"
        assert _staggered_at("17:30", 2) == "17:32"
        assert _staggered_at("23:59", 2) == "00:01"
        with pytest.raises(SystemExit, match="HH:MM"):
            _staggered_at("1730", 0)
        with pytest.raises(SystemExit, match="超出范围"):
            _staggered_at("99:00", 0)

    def test_series_mapping_targets_kline_column(self):
        assert len(KLINE_SERIES) == 5
        day = _series_mapping("day_qfq")
        assert day["kline"] == {"name": "日线前复权", "field_type": "json"}
        assert day["latest_close"]["name"] == "最新价"
        week = _series_mapping("week_qfq")
        assert set(week) == {"symbol", "kline"}
        assert week["kline"]["name"] == "周线前复权"


class TestBatchKline:
    def test_creates_batches_for_selected_symbols(self, batch_env):
        payload = cmd_batch_kline(_ns(market="A", batch_size=2))
        assert payload["total_symbols"] == 2  # 只取 是否自选=true 的 A 股
        assert payload["batches"] == 1
        assert payload["created"] == 1
        assert payload["updated"] == 0
        assert payload["dry_run"] is False

        jobs = _jobs(batch_env["db"])
        assert len(jobs) == 1
        job = jobs[0]
        assert job.name == "自选股K线-A股-日线前复权-001"
        assert job.provider == "eastmoney_kline"
        assert job.table_id == batch_env["table"].id
        assert job.entrant_param == "symbol"
        assert job.entrant_keys == ["sh600519", "sz000001"]
        assert job.match_keys == ["股票代码"]
        assert job.cursor == {"strategy": "none"}
        assert job.enabled is True
        assert "klt=101&fqt=1" in job.request_spec["url_template"]
        assert job.field_mapping["kline"]["name"] == "日线前复权"
        assert job.field_mapping["latest_close"]["name"] == "最新价"
        assert job.schedule["mode"] == "daily"
        assert job.schedule["at"] == "17:30"

    def test_batch_cap_and_staggered_schedule(self, batch_env):
        payload = cmd_batch_kline(_ns(market="ALL", include_unselected=True, batch_size=200, series="day_qfq,week_qfq"))
        assert payload["batch_size"] == MAX_BATCH_SIZE  # 超过上限收敛
        assert payload["total_symbols"] == 5
        assert payload["batches"] == 1
        assert len(payload["jobs"]) == 2  # 2 个序列 × 1 批

        jobs = {job.name: job for job in _jobs(batch_env["db"])}
        assert set(jobs) == {
            "自选股K线-全市场-日线前复权-001",
            "自选股K线-全市场-周线前复权-001",
        }
        # 错峰：第二个任务晚 2 分钟
        assert jobs["自选股K线-全市场-日线前复权-001"].schedule["at"] == "17:30"
        assert jobs["自选股K线-全市场-周线前复权-001"].schedule["at"] == "17:32"
        week = jobs["自选股K线-全市场-周线前复权-001"]
        assert "klt=102&fqt=1" in week.request_spec["url_template"]
        assert set(week.field_mapping) == {"symbol", "kline"}

    def test_idempotent_update_and_prune(self, batch_env):
        from cndb.plugins.tables.services.core.ddl import get_reflected_table

        first = cmd_batch_kline(_ns(market="ALL", include_unselected=True, batch_size=2))
        assert first["created"] == 3  # 5 只 → 2+2+1 三批
        assert first["batches"] == 3

        # 把 3 只（含港股）取消自选 → 第二次只剩 usAAPL 一批，并裁剪旧批次
        engine = batch_env["engine"]
        fields = {f.name: f for f in batch_env["table"].fields}
        sa_table = get_reflected_table(engine, batch_env["table"].db_table_name)
        with engine.begin() as conn:
            conn.execute(
                sa_table.update()
                .where(sa_table.c[fields["股票代码"].db_column_name].in_(["sh600519", "sz000001", "hk00700"]))
                .values({fields["是否自选"].db_column_name: False})
            )

        second = cmd_batch_kline(_ns(market="ALL", batch_size=2, prune=True))
        assert second["total_symbols"] == 1
        assert second["created"] == 0
        assert second["updated"] == 1
        assert len(second["pruned"]) == 2
        names = {job.name for job in _jobs(batch_env["db"])}
        assert names == {"自选股K线-全市场-日线前复权-001"}

    def test_dry_run_writes_nothing(self, batch_env):
        payload = cmd_batch_kline(_ns(market="A", batch_size=1, dry_run=True))
        assert payload["dry_run"] is True
        assert payload["created"] == 0 and payload["updated"] == 0
        assert payload["jobs"][0]["action"] == "planned"
        assert _jobs(batch_env["db"]) == []

    def test_print_reports_batches(self, batch_env, capsys):
        payload = cmd_batch_kline(_ns(market="A", batch_size=2, dry_run=True))
        _print_batch_kline(payload)
        out = capsys.readouterr().out
        assert "自选股K线-A股-日线前复权-001" in out
        assert "dry-run" in out

        real = cmd_batch_kline(_ns(market="A", batch_size=2))
        _print_batch_kline(real)
        out = capsys.readouterr().out
        assert "新建 1，更新 0" in out

    def test_manual_schedule_has_no_at(self, batch_env):
        payload = cmd_batch_kline(_ns(market="HK", schedule="manual"))
        assert payload["created"] == 1
        job = _jobs(batch_env["db"])[0]
        assert job.schedule == {"mode": "manual"}
        assert job.entrant_keys == ["hk00700"]

    def test_unknown_table_exits(self, batch_env):
        with pytest.raises(SystemExit, match="不存在数据表名称"):
            cmd_batch_kline(_ns(table="不存在的表"))

    def test_missing_target_columns_exits(self, batch_env):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table

        db = batch_env["db"]
        dt = DataTable(workspace_id=batch_env["ws"].id, name="裸表", description="")
        dt.ensure_db_name()
        db.add(dt)
        db.commit()
        db.refresh(dt)
        field = DataField(table_id=dt.id, name="股票代码", field_type="text", config={}, order=0, required=True)
        field.ensure_db_name()
        db.add(field)
        db.commit()
        db.refresh(dt)
        create_table(batch_env["engine"], dt)

        with pytest.raises(SystemExit, match="缺少 K 线目标列"):
            cmd_batch_kline(_ns(table="裸表", market="ALL", include_unselected=True))

    def test_missing_selected_field_exits(self, batch_env):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table

        db = batch_env["db"]
        dt = DataTable(workspace_id=batch_env["ws"].id, name="无自选列", description="")
        dt.ensure_db_name()
        db.add(dt)
        db.commit()
        db.refresh(dt)
        field = DataField(table_id=dt.id, name="股票代码", field_type="text", config={}, order=0, required=True)
        field.ensure_db_name()
        db.add(field)
        db.commit()
        db.refresh(dt)
        create_table(batch_env["engine"], dt)

        with pytest.raises(SystemExit, match="缺少字段: 是否自选"):
            cmd_batch_kline(_ns(table="无自选列"))
