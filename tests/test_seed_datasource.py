"""数据同步任务种子（datasource.json）测试.

覆盖：
- 单任务多标的（entrant_keys）注入，目标表名解析为 table_id
- 幂等：重复注入不重复建
- 目标表 / 字段引用不存在时打印告警并跳过（不阻断其它任务）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cndb.cli.seed.datasource import _seed_datasource, _validate_job_fields

WEATHER_CSV = """城市,日期,最高气温,最低气温,平均气温,降水量
北京,2026-07-01,33.2,24.1,28.4,0
北京,2026-07-02,34.6,25.3,29.8,0
上海,2026-07-01,31.5,26.7,28.9,12.4
"""

WEATHER_JOB = {
    "name": "天气每日同步（通用 HTTP）",
    "provider": "http_json",
    "table": "天气每日",
    "request_spec": {"url_template": "https://example/weather?city={city}&date={date}"},
    "entrant_param": "city",
    "entrant_keys": ["北京", "上海", "广州"],
    "match_keys": ["城市", "日期"],
    "field_mapping": {
        "city": {"name": "城市", "field_type": "text"},
        "date": {"name": "日期", "field_type": "date"},
        "temp_high": {"name": "最高气温", "field_type": "float"},
        "temp_low": {"name": "最低气温", "field_type": "float"},
        "temp_avg": {"name": "平均气温", "field_type": "float"},
        "rain": {"name": "降水量", "field_type": "float"},
    },
    "cursor": {"strategy": "date", "field": "日期", "backfill_start": "2026-01-01"},
    "schedule": {"mode": "daily", "at": "07:00"},
    "enabled": True,
    "rate_limit_ms": 200,
}


def _build_datasets_dir(tmp_path: Path, jobs: list[dict]) -> Path:
    """构建仅含「同步示例」workspace 的临时 datasets 目录."""
    ws_dir = tmp_path / "datasets" / "工作区-同步示例"
    ws_dir.mkdir(parents=True)
    (ws_dir / "天气每日.csv").write_text(WEATHER_CSV, encoding="utf-8-sig")
    (ws_dir / "datasource.json").write_text(json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "datasets"


@pytest.fixture
def datasource_seed(db, db_engine, tmp_path):
    """端到端 fixture：建表 + 注入数据源任务，返回 (tables_map, ws_map, user, datasets_dir)."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User

    user = User(username="ds_seed", email="ds_seed@example.com", nickname="数据源种子测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path, [WEATHER_JOB])
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        yield tables_map, ws_map, user, datasets_dir
    finally:
        seed_paths._get_datasets_dir = original


def test_seed_datasource_injects_multi_entrant_job(datasource_seed, db):
    """单任务多参数注入：table_id 解析、entrant_keys / match_keys / 字段映射原样落库."""
    from cndb.plugins.datasource.models import DatasourceSyncJob

    tables_map, ws_map, user, datasets_dir = datasource_seed
    created = _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    assert created == 1

    job = db.query(DatasourceSyncJob).filter(DatasourceSyncJob.name == WEATHER_JOB["name"]).one()
    target = tables_map["同步示例"]["天气每日"]
    assert job.table_id == target.id
    assert job.provider == "http_json"
    assert job.entrant_param == "city"
    assert job.entrant_keys == ["北京", "上海", "广州"]
    assert job.match_keys == ["城市", "日期"]
    assert job.field_mapping["temp_avg"]["name"] == "平均气温"
    assert job.enabled is True


def test_seed_datasource_persists_entrant_source(datasource_seed, db):
    """entrant_source 声明（ADR 0034 D3）原样落库：动态标的任务种子可表达."""
    from cndb.plugins.datasource.models import DatasourceSyncJob

    tables_map, ws_map, user, datasets_dir = datasource_seed
    dynamic = {
        **WEATHER_JOB,
        "name": "动态标的任务",
        "entrant_keys": [],
        "entrant_source": {"table": "天气每日", "field": "城市", "prefix_in": ["北"]},
    }
    ws_dir = Path(datasets_dir) / "工作区-同步示例"
    (ws_dir / "datasource.json").write_text(json.dumps({"jobs": [dynamic]}, ensure_ascii=False), encoding="utf-8")
    created = _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    assert created == 1

    job = db.query(DatasourceSyncJob).filter(DatasourceSyncJob.name == "动态标的任务").one()
    assert job.entrant_source == {"table": "天气每日", "field": "城市", "prefix_in": ["北"]}
    assert job.entrant_keys == []


def test_seed_datasource_idempotent(datasource_seed, db):
    """幂等：同名任务重复注入只建一次."""
    from cndb.plugins.datasource.models import DatasourceSyncJob

    tables_map, ws_map, user, datasets_dir = datasource_seed
    _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    second = _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    assert second == 0
    count = db.query(DatasourceSyncJob).filter(DatasourceSyncJob.name == WEATHER_JOB["name"]).count()
    assert count == 1


def test_seed_datasource_unknown_table_skipped(db, db_engine, tmp_path):
    """目标表名解析失败 → 打印告警并跳过，不抛异常、不建任务."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User
    from cndb.plugins.datasource.models import DatasourceSyncJob

    user = User(username="ds_bad", email="ds_bad@example.com", nickname="坏表测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    bad_job = {**WEATHER_JOB, "table": "不存在的表"}
    datasets_dir = _build_datasets_dir(tmp_path, [bad_job])
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        created = _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    finally:
        seed_paths._get_datasets_dir = original

    assert created == 0
    assert db.query(DatasourceSyncJob).count() == 0


def test_seed_datasource_invalid_field_skipped(datasource_seed, db):
    """字段映射目标列不存在 → 跳过该任务，不阻断其它."""
    from cndb.plugins.datasource.models import DatasourceSyncJob

    tables_map, ws_map, user, datasets_dir = datasource_seed
    bad = {**WEATHER_JOB, "name": "坏字段映射", "field_mapping": {"rain": {"name": "不存在列", "field_type": "float"}}}
    ws_dir = Path(datasets_dir) / "工作区-同步示例"
    (ws_dir / "datasource.json").write_text(
        json.dumps({"jobs": [WEATHER_JOB, bad]}, ensure_ascii=False), encoding="utf-8"
    )
    created = _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    assert created == 1  # 仅合法任务落库
    names = {j.name for j in db.query(DatasourceSyncJob).all()}
    assert names == {WEATHER_JOB["name"]}


def test_seed_datasource_missing_dir_returns_zero(db):
    """datasets 目录缺失 → 返回 0，优雅降级."""
    assert _seed_datasource(db, None, {}, {}, None) == 0


def test_validate_job_fields_accepts_drop_and_detects_missing():
    """字段校验：丢弃项（None）放行；match_keys / 映射目标列不在表内则拒绝."""
    valid = {"城市", "日期"}
    assert _validate_job_fields({"match_keys": ["城市"], "field_mapping": {"raw": None}}, valid, "w", "t")
    assert not _validate_job_fields({"match_keys": ["不存在"], "field_mapping": {}}, valid, "w", "t")
    assert not _validate_job_fields(
        {"match_keys": [], "field_mapping": {"rain": {"name": "不存在", "field_type": "float"}}}, valid, "w", "t"
    )
