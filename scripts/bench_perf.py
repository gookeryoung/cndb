"""cndb 性能基准（可复现）—— 启动 / API / SQL / 导入 / 迁移.

用法::

    uv run python scripts/bench_perf.py --rows 50000 --out .workbuddy/perf_baseline.json

设计要点：
- 数据集规模、随机种子固定，同一命令可重复跑出可比数字；
- 每个场景先清对应进程内缓存再计时（cold），另给 warm 命中耗时；
- 所有物理数据用 executemany 直接写入，避免用被测导入路径预热器自身；
- 输出 JSON + 控制台表格，便于前后对比（同机同口径）。

注意：脚本会在系统临时目录建独立 sqlite 文件，不触碰 data/cndb.db。
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, round((p / 100) * (len(ordered) - 1)))
    return ordered[idx]


def _summarize(name: str, samples: list[float], size: int | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "n": len(samples),
        "p50_ms": round(statistics.median(samples) * 1000, 2),
        "p95_ms": round(_pct(samples, 95) * 1000, 2),
        "mean_ms": round(statistics.fmean(samples) * 1000, 2),
        "max_ms": round(max(samples) * 1000, 2) if samples else 0.0,
        "bytes": size,
    }


def _env_info(db_path: Path) -> dict[str, Any]:
    return {
        "python": sys.version.split()[0],
        "sqlite": sqlite3.sqlite_version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_count": os.cpu_count(),
        "db": str(db_path),
        "pid": os.getpid(),
    }


# ── 启动 / 迁移（子进程，冷导入口径） ─────────────────


def _run_py(code: str, env: dict[str, str]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(ROOT),
        timeout=600,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"子进程失败:\n{proc.stdout}\n{proc.stderr}")
    line = proc.stdout.strip().splitlines()[-1]
    return json.loads(line)


def bench_startup(tmp: Path) -> dict[str, Any]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SRC)
    env["DATABASE_URL"] = f"sqlite:///{(tmp / 'startup.db').as_posix()}"
    env["AUTH_ENABLED"] = "false"

    import_code = (
        "import json,time;"
        "t0=time.perf_counter();"
        "import cndb.app;"
        "t1=time.perf_counter();"
        "print(json.dumps({'import_app_s': round(t1-t0,4)}))"
    )
    imports = [_run_py(import_code, env)["import_app_s"] for _ in range(3)]

    detail_code = (
        "import json,time;"
        "from fastapi import FastAPI;"
        "from cndb.core.plugin_registry import plugin_registry;"
        "t0=time.perf_counter(); plugin_registry.discover_and_load(); t1=time.perf_counter();"
        "app=FastAPI(); plugin_registry.mount_routes(app); t2=time.perf_counter();"
        "print(json.dumps({'discover_s': round(t1-t0,4), 'mount_s': round(t2-t1,4), "
        "'plugins': len(getattr(plugin_registry, 'plugins', []) or [])}))"
    )
    detail = _run_py(detail_code, env)

    migration_code = (
        "import json,time;"
        "from cndb.core.migrations import ensure_db_migrated;"
        "t0=time.perf_counter(); ensure_db_migrated(); t1=time.perf_counter();"
        "print(json.dumps({'migrate_empty_s': round(t1-t0,4)}))"
    )
    migrate = _run_py(migration_code, env)
    return {
        "import_app_median_s": round(statistics.median(imports), 4),
        "import_app_runs_s": [round(v, 4) for v in imports],
        **detail,
        **migrate,
    }


# ── 数据集 ───────────────────────────────────────────


def _seed_dataset(rows: int, small_rows: int, targets: int) -> dict[str, Any]:
    import cndb.app  # noqa: F401 - 先注册全部插件模型，Base.metadata 才完整
    from cndb.core.database import SessionLocal, engine
    from cndb.models.base import Base
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core.ddl import create_table, get_reflected_table
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    Base.metadata.create_all(engine)
    rng = random.Random(20261111)

    db = SessionLocal()
    try:
        user = User(username="perf", nickname="perf", hashed_password="x", is_active=True, token_version=0)
        db.add(user)
        db.flush()
        ws = Workspace(name="perf-ws", created_by_id=user.id)
        db.add(ws)
        db.flush()
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=WorkspaceRole.OWNER))
        db.commit()
        user_id, ws_id = user.id, ws.id
    finally:
        db.close()

    def _mk_table(name: str, db_name: str) -> int:
        db = SessionLocal()
        try:
            t = DataTable(workspace_id=ws_id, owner_id=user_id, name=name, db_table_name=db_name)
            db.add(t)
            db.flush()
            db.commit()
            return t.id
        finally:
            db.close()

    def _mk_field(table_id: int, name: str, ftype: str, order: int, config: dict | None = None) -> int:
        db = SessionLocal()
        try:
            f = DataField(
                table_id=table_id,
                name=name,
                field_type=ftype,
                db_column_name=f"field_{table_id}_{order}",
                config=config or {},
                order=order,
            )
            db.add(f)
            db.flush()
            db.commit()
            return f.id
        finally:
            db.close()

    # 目标表（lookup 源）
    target_id = _mk_table("目标表", "bench_target")
    target_name_fid = _mk_field(target_id, "名称", "text", 0)
    _mk_field(target_id, "分数", "number", 1)

    # 大表（无 lookup，测分页 / 排序 / 搜索）
    big_id = _mk_table("大表", "bench_big")
    _mk_field(big_id, "名称", "text", 0)
    _mk_field(big_id, "分组", "select", 1, {"options": [f"G{i}" for i in range(10)]})
    _mk_field(big_id, "分数", "number", 2)
    _mk_field(big_id, "日期", "date", 3)
    _mk_field(big_id, "备注", "text", 4)

    # 关联 + lookup 表（保持低于默认扫描上限，测 lookup 语义路径）
    lk_id = _mk_table("关联表", "bench_lookup")
    _mk_field(lk_id, "名称", "text", 0)
    _mk_field(lk_id, "分数", "number", 1)
    link_fid = _mk_field(
        lk_id,
        "目标",
        "link",
        2,
        {
            "target_table_id": target_id,
            "display_field_id": target_name_fid,
            "match_field_id": target_name_fid,
            "multiple": False,
        },
    )
    _mk_field(
        lk_id,
        "目标名称",
        "lookup",
        3,
        {
            "via_link_field_id": link_fid,
            "source_field_id": target_name_fid,
            "source_field_type": "text",
            "target_table_id": target_id,
        },
    )

    # 物理表 + 元数据全量加载
    db = SessionLocal()
    try:
        tables = {t.id: t for t in db.query(DataTable).all()}
        for t in tables.values():
            create_table(engine, t)
    finally:
        db.close()

    def _col_map(table_name: str) -> dict[str, str]:
        db = SessionLocal()
        try:
            t = db.query(DataTable).filter(DataTable.db_table_name == table_name).one()
            return {f.name: f.db_column_name for f in t.active_fields()}
        finally:
            db.close()

    target_cols = _col_map("bench_target")
    big_cols = _col_map("bench_big")
    lk_cols = _col_map("bench_lookup")

    target_sa = get_reflected_table(engine, "bench_target")
    big_sa = get_reflected_table(engine, "bench_big")
    lk_sa = get_reflected_table(engine, "bench_lookup")

    t0 = time.perf_counter()
    with engine.begin() as conn:
        conn.execute(
            target_sa.insert(),
            [
                {
                    "id": i,
                    target_cols["名称"]: f"目标-{i:05d}",
                    target_cols["分数"]: rng.randint(0, 1000),
                    "_trashed": False,
                }
                for i in range(1, targets + 1)
            ],
        )
    target_seed_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    chunk = 5000
    for start in range(1, rows + 1, chunk):
        stop = min(rows + 1, start + chunk)
        with engine.begin() as conn:
            conn.execute(
                big_sa.insert(),
                [
                    {
                        "id": i,
                        big_cols["名称"]: f"项目-{i:06d}",
                        big_cols["分组"]: f"G{i % 10}",
                        big_cols["分数"]: i % 1000,
                        big_cols["日期"]: date(2026, (i % 12) + 1, (i % 28) + 1),
                        big_cols["备注"]: f"备注内容 {i} 关键字-{i % 97}",
                        "_trashed": False,
                    }
                    for i in range(start, stop)
                ],
            )
    big_seed_s = time.perf_counter() - t0

    t0 = time.perf_counter()
    db = SessionLocal()
    try:
        link_table_name = db.get(DataField, link_fid).link_table_name
    finally:
        db.close()
    for start in range(1, small_rows + 1, chunk):
        stop = min(small_rows + 1, start + chunk)
        with engine.begin() as conn:
            conn.execute(
                lk_sa.insert(),
                [
                    {
                        "id": i,
                        lk_cols["名称"]: f"记录-{i:06d}",
                        lk_cols["分数"]: i % 500,
                        "_trashed": False,
                    }
                    for i in range(start, stop)
                ],
            )
            link_table = get_reflected_table(engine, link_table_name)
            conn.execute(
                link_table.insert(),
                [{"row_id": i, "target_row_id": (i % targets) + 1} for i in range(start, stop)],
            )
    lk_seed_s = time.perf_counter() - t0

    # lookup 冗余列回填（ADR 0131）：物理数据由 executemany 直写，绕过写入路径同步，
    # 因此用回填补齐；关闭冗余列时跳过（旧内存路径不需要）。
    from cndb.core.config import settings as _settings
    from cndb.plugins.tables.services.core.lookup_sync import backfill_lookup_columns

    backfill: dict[str, Any] = {}
    if bool(getattr(_settings, "LOOKUP_COLUMNS_ENABLED", True)):
        db = SessionLocal()
        try:
            lk_table = db.get(DataTable, lk_id)
            t0 = time.perf_counter()
            processed = backfill_lookup_columns(engine, lk_table, db=db)
            db.commit()
            elapsed = time.perf_counter() - t0
            backfill = {
                "rows": processed,
                "elapsed_s": round(elapsed, 3),
                "rows_per_s": round(processed / elapsed, 1) if elapsed else None,
            }
        finally:
            db.close()

    return {
        "user_id": user_id,
        "workspace_id": ws_id,
        "big_table_id": big_id,
        "lookup_table_id": lk_id,
        "target_table_id": target_id,
        "rows": rows,
        "small_rows": small_rows,
        "targets": targets,
        "seed_s": {
            "target": round(target_seed_s, 3),
            "big": round(big_seed_s, 3),
            "lookup": round(lk_seed_s, 3),
        },
        "lookup_backfill": backfill,
    }


# ── API 基准 ─────────────────────────────────────────


def _count_queries(engine, fn):
    from sqlalchemy import event

    counter = {"n": 0}

    def _before(*_args: Any) -> None:
        counter["n"] += 1

    event.listen(engine, "before_cursor_execute", _before)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before)
    return result, counter["n"]


def bench_api(ds: dict[str, Any], repeats: int, warm_repeats: int) -> dict[str, Any]:
    from fastapi.testclient import TestClient

    from cndb.app import app
    from cndb.core.cache import list_cache, meta_cache, search_cache
    from cndb.core.database import engine
    from cndb.core.security import create_access_token

    token = create_access_token(ds["user_id"], token_version=0)
    headers = {"Authorization": f"Bearer {token}"}
    ws = ds["workspace_id"]
    big = ds["big_table_id"]
    lk = ds["lookup_table_id"]
    base = f"/api/v1/workspaces/{ws}/tables"

    client = TestClient(app)
    out: dict[str, Any] = {}

    def _call(path: str, method: str = "GET", **kwargs: Any):
        fn = client.get if method == "GET" else client.post
        return fn(path, headers=headers, **kwargs)

    def _measure(name: str, fn, *, cold: bool = True) -> dict[str, Any]:
        # 预热一次（建立反射表缓存等一次性成本），避免把首次反射算进稳态
        fn()
        samples: list[float] = []
        last = None
        for _ in range(repeats):
            if cold:
                list_cache.clear("records")
                list_cache.clear("workspace-stats")
                meta_cache.clear()
                search_cache.clear()
            t0 = time.perf_counter()
            resp = fn()
            samples.append(time.perf_counter() - t0)
            last = resp
        size = len(last.content) if hasattr(last, "content") else None
        summary = _summarize(name, samples, size)
        if hasattr(last, "status_code"):
            summary["status"] = last.status_code
        return summary

    def _measure_warm(name: str) -> dict[str, Any]:
        samples: list[float] = []
        last = None
        for _ in range(warm_repeats):
            t0 = time.perf_counter()
            last = _call(f"{base}/{big}/records", params={"limit": 50})
            samples.append(time.perf_counter() - t0)
        return _summarize(name + " [warm]", samples, len(last.content) if last is not None else None)

    url = f"{base}/{big}/records"
    out["list_default"] = _measure("GET records limit=50", lambda: _call(url, params={"limit": 50}))
    out["list_warm"] = _measure_warm("GET records limit=50")
    out["list_sorted"] = _measure(
        "GET records sorts=score desc",
        lambda: _call(url, params={"limit": 50, "sorts": json.dumps([{"field_name": "分数", "direction": "desc"}])}),
    )
    out["list_filter"] = _measure(
        "GET records filter grp=G3",
        lambda: _call(
            url,
            params={"limit": 50, "filters": json.dumps([{"field_name": "分组", "op": "=", "value": "G3"}])},
        ),
    )
    out["list_contains"] = _measure(
        "GET records contains 备注",
        lambda: _call(
            url,
            params={
                "limit": 50,
                "filters": json.dumps([{"field_name": "备注", "op": "contains", "value": "关键字-7"}]),
            },
        ),
    )
    out["list_deep_offset"] = _measure(
        "GET records offset=40000",
        lambda: _call(url, params={"limit": 50, "offset": 40000}),
    )
    out["detail"] = _measure("GET record detail", lambda: _call(f"{url}/12345"))
    out["lookup_list"] = _measure(
        "GET lookup records (attach)",
        lambda: _call(f"{base}/{lk}/records", params={"limit": 50}),
    )
    out["lookup_filter"] = _measure(
        "POST lookup filter",
        lambda: _call(
            f"{base}/{lk}/records/list",
            method="POST",
            json={"filters": [{"field_name": "目标名称", "op": "contains", "value": "目标-0001"}], "limit": 50},
        ),
    )
    out["lookup_sort"] = _measure(
        "POST lookup sort asc",
        lambda: _call(
            f"{base}/{lk}/records/list",
            method="POST",
            json={"filters": [], "sorts": [{"field_name": "目标名称", "direction": "asc"}], "limit": 50},
        ),
    )
    out["search"] = _measure(
        "GET workspace search",
        lambda: _call(f"/api/v1/workspaces/{ws}/search", params={"q": "关键字-7", "limit": 10}),
    )
    out["tables_list"] = _measure("GET tables list", lambda: _call(f"/api/v1/workspaces/{ws}/tables"))
    out["workspace_detail"] = _measure("GET workspace detail", lambda: _call(f"/api/v1/workspaces/{ws}"))

    # 查询次数（N+1 探测）：同一请求内的 cursor execute 次数
    for name, call in (
        ("q_list_default", lambda: _call(url, params={"limit": 50})),
        (
            "q_list_sorted",
            lambda: _call(
                url, params={"limit": 50, "sorts": json.dumps([{"field_name": "分数", "direction": "desc"}])}
            ),
        ),
        ("q_detail", lambda: _call(f"{url}/12345")),
        ("q_lookup_list", lambda: _call(f"{base}/{lk}/records", params={"limit": 50})),
        (
            "q_lookup_filter",
            lambda: _call(
                f"{base}/{lk}/records/list",
                method="POST",
                json={"filters": [{"field_name": "目标名称", "op": "contains", "value": "目标-0001"}], "limit": 50},
            ),
        ),
        ("q_workspace_detail", lambda: _call(f"/api/v1/workspaces/{ws}")),
        ("q_tables_list", lambda: _call(f"/api/v1/workspaces/{ws}/tables")),
    ):
        list_cache.clear()
        meta_cache.clear()
        _, queries = _count_queries(engine, call)
        out[name] = {"queries": queries}

    # 响应反序列化 / 序列化开销
    resp = _call(url, params={"limit": 500})
    body = resp.content
    t0 = time.perf_counter()
    for _ in range(10):
        resp.json()
    out["json_parse_500"] = _summarize("json parse 500 rows", [(time.perf_counter() - t0) / 10], len(body))
    raw_rows = resp.json().get("rows") or []
    t0 = time.perf_counter()
    for _ in range(10):
        json.dumps(raw_rows, ensure_ascii=False)
    out["json_dump_500"] = _summarize("json dump 500 rows", [(time.perf_counter() - t0) / 10], len(body))
    return out


def bench_query_plans(ds: dict[str, Any]) -> list[dict[str, Any]]:
    from sqlalchemy import text

    from cndb.core.database import SessionLocal, engine
    from cndb.plugins.tables.models import DataTable

    db = SessionLocal()
    try:
        t = db.query(DataTable).filter(DataTable.id == ds["big_table_id"]).one()
        cols = {f.name: f.db_column_name for f in t.active_fields()}
        table_name = t.db_table_name
    finally:
        db.close()
    score_col = cols["分数"]
    grp_col = cols["分组"]
    note_col = cols["备注"]

    plans: dict[str, str] = {
        "count_all": f'SELECT COUNT(*) FROM "{table_name}" WHERE _trashed = 0',
        "page_default": f'SELECT * FROM "{table_name}" WHERE _trashed = 0 LIMIT 50 OFFSET 0',
        "page_deep": f'SELECT * FROM "{table_name}" WHERE _trashed = 0 LIMIT 50 OFFSET 40000',
        "filter_eq": f'SELECT * FROM "{table_name}" WHERE _trashed = 0 AND "{grp_col}" = \'G3\' LIMIT 50',
        "sort_score": f'SELECT * FROM "{table_name}" WHERE _trashed = 0 ORDER BY "{score_col}" DESC LIMIT 50',
        "contains_note": f'SELECT * FROM "{table_name}" WHERE _trashed = 0 AND "{note_col}" LIKE \'%关键字-7%\' LIMIT 50',
    }
    out: list[dict[str, Any]] = []
    with engine.connect() as conn:
        for name, sql in plans.items():
            rows = conn.execute(text("EXPLAIN QUERY PLAN " + sql)).all()
            samples: list[float] = []
            for _ in range(5):
                t0 = time.perf_counter()
                if sql.startswith("SELECT COUNT"):
                    conn.execute(text(sql)).scalar()
                else:
                    conn.execute(text(sql)).all()
                samples.append(time.perf_counter() - t0)
            out.append(
                {
                    "name": name,
                    "sql": sql,
                    "plan": " | ".join(str(r[-1]) for r in rows),
                    **_summarize(name, samples),
                }
            )
    return out


def bench_import(ds: dict[str, Any], import_rows: int) -> dict[str, Any]:
    from sqlalchemy import text

    from cndb.core.database import SessionLocal, engine
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core.ddl import create_table
    from cndb.plugins.tables.services.transfer import import_rows_from_json

    db = SessionLocal()
    try:
        t = DataTable(
            workspace_id=ds["workspace_id"],
            owner_id=ds["user_id"],
            name="导入表",
            db_table_name="bench_import",
        )
        db.add(t)
        db.flush()
        for order, (name, ftype) in enumerate((("名称", "text"), ("分数", "number"), ("备注", "text"))):
            db.add(
                DataField(
                    table_id=t.id,
                    name=name,
                    field_type=ftype,
                    db_column_name=f"field_import_{order}",
                    config={},
                    order=order,
                )
            )
        db.commit()
        table_id = t.id
        create_table(engine, db.get(DataTable, table_id))
        table = db.get(DataTable, table_id)
        payload = json.dumps(
            [{"名称": f"导入-{i:05d}", "分数": i % 1000, "备注": f"批量 {i}"} for i in range(import_rows)],
            ensure_ascii=False,
        )
        plain_samples: list[float] = []
        for _ in range(3):
            t0 = time.perf_counter()
            ids = import_rows_from_json(engine, table, payload, db=db)
            elapsed = time.perf_counter() - t0
            db.commit()
            plain_samples.append(elapsed)
        plain_elapsed = statistics.median(plain_samples)
        plain_count = db.execute(text(f'SELECT COUNT(*) FROM "{table.db_table_name}"')).scalar()
        plain = {
            "rows": len(ids),
            "elapsed_s": round(plain_elapsed, 3),
            "rows_per_s": round(len(ids) / plain_elapsed, 1) if plain_elapsed else None,
            "row_count": plain_count,
            "json_bytes": len(payload.encode("utf-8")),
        }

        # 带 link 列的导入：覆盖目标校验 / 唯一校验 / 关联写入路径（N+1 敏感区）
        linked = DataTable(
            workspace_id=ds["workspace_id"],
            owner_id=ds["user_id"],
            name="导入关联表",
            db_table_name="bench_import_link",
        )
        db.add(linked)
        db.flush()
        db.add(
            DataField(
                table_id=linked.id,
                name="名称",
                field_type="text",
                db_column_name="field_impl_0",
                config={},
                order=0,
            )
        )
        db.add(
            DataField(
                table_id=linked.id,
                name="目标",
                field_type="link",
                db_column_name="field_impl_1",
                config={"target_table_id": ds["target_table_id"], "multiple": True},
                order=1,
            )
        )
        db.commit()
        create_table(engine, db.get(DataTable, linked.id))
        linked_table = db.get(DataTable, linked.id)
        linked_n = min(import_rows, 2000)
        linked_payload = json.dumps(
            [{"名称": f"关联导入-{i:05d}", "目标": str((i % ds["targets"]) + 1)} for i in range(linked_n)],
            ensure_ascii=False,
        )
        linked_samples: list[float] = []
        for _ in range(3):
            t0 = time.perf_counter()
            linked_ids = import_rows_from_json(engine, linked_table, linked_payload, db=db)
            linked_elapsed = time.perf_counter() - t0
            db.commit()
            linked_samples.append(linked_elapsed)
        linked_elapsed = statistics.median(linked_samples)
        return {
            "plain": plain,
            "linked": {
                "rows": len(linked_ids),
                "elapsed_s": round(linked_elapsed, 3),
                "rows_per_s": round(len(linked_ids) / linked_elapsed, 1) if linked_elapsed else None,
                "row_count": db.execute(text(f'SELECT COUNT(*) FROM "{linked_table.db_table_name}"')).scalar(),
            },
        }
    finally:
        db.close()


# ── 主流程 ───────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=50000, help="大表行数")
    parser.add_argument("--small-rows", type=int, default=15000, help="lookup 表行数（低于默认扫描上限 20000）")
    parser.add_argument("--targets", type=int, default=1000, help="lookup 目标表行数")
    parser.add_argument("--import-rows", type=int, default=5000)
    parser.add_argument("--repeats", type=int, default=10, help="每个场景 cold 采样次数")
    parser.add_argument("--warm-repeats", type=int, default=30)
    parser.add_argument("--skip-startup", action="store_true")
    parser.add_argument("--skip-import", action="store_true")
    parser.add_argument(
        "--no-lookup-columns",
        action="store_true",
        help="关闭 lookup 冗余列（ADR 0131），用旧内存路径跑同一基准做 A/B",
    )
    parser.add_argument("--keep-db", action="store_true")
    parser.add_argument("--out", type=str, default="")
    args = parser.parse_args()

    if args.no_lookup_columns:
        # 必须在 import cndb 之前设置：settings 在模块导入时实例化
        os.environ["LOOKUP_COLUMNS_ENABLED"] = "false"

    tmp = Path(tempfile.mkdtemp(prefix="cndb-perf-"))
    db_path = tmp / "bench.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path.as_posix()}"
    os.environ["PYTHONPATH"] = str(SRC)
    os.environ.setdefault("AUTH_ENABLED", "true")
    os.environ["DEBUG"] = "false"  # 关掉 SQL echo，避免日志污染耗时
    sys.path.insert(0, str(SRC))

    report: dict[str, Any] = {"env": _env_info(db_path), "args": vars(args)}
    t_start = time.perf_counter()

    if not args.skip_startup:
        print("[1/5] 启动 / 插件 / 迁移 ...")
        report["startup"] = bench_startup(tmp)

    print("[2/5] 构建数据集 ...")
    ds = _seed_dataset(args.rows, args.small_rows, args.targets)
    report["dataset"] = ds

    print("[3/5] 查询计划 ...")
    report["query_plans"] = bench_query_plans(ds)

    print("[4/5] API 端到端 ...")
    report["api"] = bench_api(ds, args.repeats, args.warm_repeats)

    if not args.skip_import:
        print("[5/5] 导入路径 ...")
        report["import"] = bench_import(ds, args.import_rows)

    report["total_elapsed_s"] = round(time.perf_counter() - t_start, 2)

    print("\n=== startup ===")
    for k, v in report.get("startup", {}).items():
        if k.endswith("_s"):
            print(f"  {k:24s} {v}")
    print("\n=== query plans (cold sql) ===")
    for item in report.get("query_plans", []):
        print(f"  {item['name']:16s} {item['p50_ms']:8.2f}ms  {item['plan']}")
    print("\n=== api ===")
    for k, v in report["api"].items():
        if isinstance(v, dict) and "p50_ms" in v:
            status = v.get("status", "")
            print(f"  {k:20s} p50={v['p50_ms']:8.2f}ms p95={v['p95_ms']:8.2f}ms bytes={v['bytes']} status={status}")
        elif isinstance(v, dict) and "queries" in v:
            print(f"  {k:20s} queries={v['queries']}")
    if report["dataset"].get("lookup_backfill"):
        print(f"\n=== lookup backfill === {json.dumps(report['dataset']['lookup_backfill'], ensure_ascii=False)}")
    if "import" in report:
        print(f"\n=== import === {json.dumps(report['import'], ensure_ascii=False)}")

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入 {out_path}")

    if args.keep_db:
        print(f"数据库保留在 {db_path}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
