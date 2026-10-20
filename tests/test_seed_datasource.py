"""数据源同步任务种子（datasource.json）测试.

覆盖：
- 单任务多标的（entrant_keys）注入，目标表名解析为 table_id
- 幂等：重复注入不重复建
- 目标表 / 字段引用不存在时打印告警并跳过（不阻断其它任务）
- 真实 examples/datasets/工作区-数据源示例/datasource.json 结构合法性
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cndb.cli.seed.datasource import _seed_datasource, _validate_job_fields

STOCK_CSV = """股票代码,股票名称,交易日,开盘价,最高价,最低价,收盘价,成交量
sh600519,贵州茅台,2026-07-01,1416.38,1446.29,1412.86,1442.9,3549800
sh600519,贵州茅台,2026-07-02,1417.36,1470.05,1410.59,1446.76,2524400
sz000001,平安银行,2026-07-01,11.97,12.09,11.56,11.6,85098000
"""

STOCK_JOB = {
    "name": "股市日线同步（腾讯前复权）",
    "provider": "tencent_kline",
    "table": "股市日线",
    "request_spec": {"url_template": "https://example/param={symbol},day,{start},{end},320,qfq"},
    "entrant_param": "symbol",
    "entrant_keys": ["sh600519", "sz000001", "sz300750"],
    "match_keys": ["股票代码", "交易日"],
    "field_mapping": {
        "symbol": {"name": "股票代码", "field_type": "text"},
        "trade_date": {"name": "交易日", "field_type": "date"},
        "open": {"name": "开盘价", "field_type": "float"},
        "close": {"name": "收盘价", "field_type": "float"},
        "high": {"name": "最高价", "field_type": "float"},
        "low": {"name": "最低价", "field_type": "float"},
        "volume": {"name": "成交量", "field_type": "int"},
    },
    "cursor": {"strategy": "date", "field": "交易日", "backfill_start": "2026-01-01"},
    "schedule": {"mode": "daily", "at": "17:30"},
    "enabled": True,
    "rate_limit_ms": 200,
}


def _build_datasets_dir(tmp_path: Path, jobs: list[dict]) -> Path:
    """构建仅含「数据源示例」workspace 的临时 datasets 目录."""
    ws_dir = tmp_path / "datasets" / "工作区-数据源示例"
    ws_dir.mkdir(parents=True)
    (ws_dir / "股市日线.csv").write_text(STOCK_CSV, encoding="utf-8-sig")
    (ws_dir / "datasource.json").write_text(json.dumps({"jobs": jobs}, ensure_ascii=False), encoding="utf-8")
    return tmp_path / "datasets"


@pytest.fixture
def stocked_seed(db, db_engine, tmp_path):
    """端到端 fixture：建表 + 注入数据源任务，返回 (tables_map, ws_map, user, datasets_dir)."""
    from cndb.cli.seed import _seed_datasets
    from cndb.cli.seed import paths as seed_paths
    from cndb.plugins.accounts.models import User

    user = User(username="ds_seed", email="ds_seed@example.com", nickname="数据源种子测试")
    user.set_password("pass1234")
    db.add(user)
    db.commit()
    db.refresh(user)

    datasets_dir = _build_datasets_dir(tmp_path, [STOCK_JOB])
    original = seed_paths._get_datasets_dir
    seed_paths._get_datasets_dir = lambda: datasets_dir
    try:
        _, ws_map, tables_map = _seed_datasets(db, db_engine, user)
        yield tables_map, ws_map, user, datasets_dir
    finally:
        seed_paths._get_datasets_dir = original


def test_seed_datasource_injects_multi_entrant_job(stocked_seed, db):
    """单任务多标的注入：table_id 解析、entrant_keys / match_keys / 字段映射原样落库."""
    from cndb.plugins.datasource.models import DatasourceSyncJob

    tables_map, ws_map, user, datasets_dir = stocked_seed
    created = _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    assert created == 1

    job = db.query(DatasourceSyncJob).filter(DatasourceSyncJob.name == STOCK_JOB["name"]).one()
    target = tables_map["数据源示例"]["股市日线"]
    assert job.table_id == target.id
    assert job.provider == "tencent_kline"
    assert job.entrant_param == "symbol"
    assert job.entrant_keys == ["sh600519", "sz000001", "sz300750"]
    assert job.match_keys == ["股票代码", "交易日"]
    assert job.field_mapping["close"]["name"] == "收盘价"
    assert job.enabled is True


def test_seed_datasource_idempotent(stocked_seed, db):
    """幂等：同名任务重复注入只建一次."""
    from cndb.plugins.datasource.models import DatasourceSyncJob

    tables_map, ws_map, user, datasets_dir = stocked_seed
    _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    second = _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    assert second == 0
    count = db.query(DatasourceSyncJob).filter(DatasourceSyncJob.name == STOCK_JOB["name"]).count()
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

    bad_job = {**STOCK_JOB, "table": "不存在的表"}
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


def test_seed_datasource_invalid_field_skipped(stocked_seed, db):
    """字段映射目标列不存在 → 跳过该任务，不阻断其它."""
    from cndb.plugins.datasource.models import DatasourceSyncJob

    tables_map, ws_map, user, datasets_dir = stocked_seed
    bad = {**STOCK_JOB, "name": "坏字段映射", "field_mapping": {"close": {"name": "不存在列", "field_type": "float"}}}
    ws_dir = Path(datasets_dir) / "工作区-数据源示例"
    (ws_dir / "datasource.json").write_text(
        json.dumps({"jobs": [STOCK_JOB, bad]}, ensure_ascii=False), encoding="utf-8"
    )
    created = _seed_datasource(db, user, ws_map, tables_map, datasets_dir)
    assert created == 1  # 仅合法任务落库
    names = {j.name for j in db.query(DatasourceSyncJob).all()}
    assert names == {STOCK_JOB["name"]}


def test_seed_datasource_missing_dir_returns_zero(db):
    """datasets 目录缺失 → 返回 0，优雅降级."""
    assert _seed_datasource(db, None, {}, {}, None) == 0


def test_validate_job_fields_accepts_drop_and_detects_missing():
    """字段校验：丢弃项（None）放行；match_keys / 映射目标列不在表内则拒绝."""
    valid = {"股票代码", "交易日"}
    assert _validate_job_fields({"match_keys": ["股票代码"], "field_mapping": {"raw": None}}, valid, "w", "t")
    assert not _validate_job_fields({"match_keys": ["不存在"], "field_mapping": {}}, valid, "w", "t")
    assert not _validate_job_fields(
        {"match_keys": [], "field_mapping": {"close": {"name": "不存在", "field_type": "float"}}}, valid, "w", "t"
    )


def test_real_datasource_json_is_valid():
    """真实 examples 配置：三个 provider 的任务结构合法、目标表与映射列引用自洽."""
    path = Path(__file__).resolve().parents[1] / "examples" / "datasets" / "工作区-数据源示例" / "datasource.json"
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    jobs = cfg["jobs"]
    assert len(jobs) == 7

    tencent = [j for j in jobs if j["provider"] == "tencent_kline"]
    assert len(tencent) == 1
    job = tencent[0]
    assert job["table"] == "股市日线"
    assert len(job["entrant_keys"]) >= 2
    assert job["match_keys"] == ["股票代码", "交易日"]
    # 标的前缀与 CSV 表内取值口径一致（sh/sz 前缀）
    assert all(k[:2] in ("sh", "sz") for k in job["entrant_keys"])
    # 映射目标列名与 CSV 表头一致
    targets = {t["name"] for t in job["field_mapping"].values() if t}
    assert targets <= {"股票代码", "交易日", "开盘价", "收盘价", "最高价", "最低价", "成交量"}

    # eastmoney_kline：一只股一行，按周期/复权分 job 写不同 JSON 列
    stock_cols = {
        "股票代码",
        "股票名称",
        "市场",
        "行业",
        "是否自选",
        "最新价",
        "涨跌幅",
        "最新交易日",
        "成交量",
        "成交额",
        "日线前复权",
        "日线后复权",
        "日线不复权",
        "周线前复权",
        "月线前复权",
        "更新时间",
    }
    eastmoney = [j for j in jobs if j["provider"] == "eastmoney_kline"]
    assert len(eastmoney) == 5
    kline_targets: list[str] = []
    for job in eastmoney:
        assert job["table"] == "自选股"
        assert job["entrant_param"] == "symbol"
        assert job["match_keys"] == ["股票代码"]
        assert all(k[:2] in ("sh", "sz", "hk", "us") for k in job["entrant_keys"])
        for target in job["field_mapping"].values():
            assert target["name"] in stock_cols, f"映射到不存在的列 {target['name']}"
        kline_targets.extend(
            target["name"] for target in job["field_mapping"].values() if target["field_type"] == "json"
        )
    # 5 个 job 各写一列，互不重复（配合 partial upsert 不互相清空）
    assert sorted(kline_targets) == sorted(["日线前复权", "日线后复权", "日线不复权", "周线前复权", "月线前复权"])

    # eastmoney_symbols：全市场标的发现（P1），默认停用 + 分页拉取 + 只写代码/名称/市场
    symbols_jobs = [j for j in jobs if j["provider"] == "eastmoney_symbols"]
    assert len(symbols_jobs) == 1
    symbols_job = symbols_jobs[0]
    assert symbols_job["table"] == "自选股"
    assert symbols_job["entrant_param"] == "market"
    assert symbols_job["match_keys"] == ["股票代码"]
    assert symbols_job["enabled"] is False, "全市场发现默认停用，避免 seed 后意外联网"
    paging = symbols_job["request_spec"]["paging"]
    assert paging["mode"] == "page"
    assert paging["page_size"] <= 100
    assert paging["max_pages"] >= 50
    assert "{page}" in symbols_job["request_spec"]["url_template"]
    assert "{fs}" in symbols_job["request_spec"]["url_template"]
    # 不映射「是否自选」：新行由字段默认值落 false，已有自选行不被覆盖；K 线列留空
    mapped = {target["name"] for target in symbols_job["field_mapping"].values()}
    assert mapped == {"股票代码", "股票名称", "市场"}
