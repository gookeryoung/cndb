"""性能基准 — 10k 行导入 / 查询吞吐."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / ".." / "src"))

from sqlalchemy import MetaData, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from cndb.core.config import settings
from cndb.models.base import Base
from cndb.plugins.tables import transfer
from cndb.plugins.tables.ddl import create_table
from cndb.plugins.tables.models import DataField, DataTable


def setup_db() -> tuple[Any, Any]:
    """创建临时 SQLite 数据库 + 表结构."""
    db_path = Path(tempfile.gettempdir()) / "cndb_bench.db"
    if db_path.exists():
        db_path.unlink()
    settings.DATABASE_URL = f"sqlite:///{db_path}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, str(db_path)


def create_bench_table(engine: Any) -> Any:
    """建一个带 text/number/boolean/date 字段的表."""
    SessionLocal = sessionmaker(bind=engine)
    db: Session = SessionLocal()
    try:
        dt = DataTable(workspace_id=1, name="bench", description="benchmark table")
        dt.ensure_db_name()
        db.add(dt)
        db.commit()
        db.refresh(dt)

        field_specs = [
            ("name", "text"),
            ("category", "select"),
            ("score", "number"),
            ("active", "boolean"),
        ]
        for idx, (fname, ftype) in enumerate(field_specs):
            f = DataField(
                table_id=dt.id,
                name=fname,
                field_type=ftype,
                config={"options": ["A", "B", "C"]} if ftype == "select" else {},
                order=idx,
                required=False,
            )
            f.ensure_db_name()
            db.add(f)
        db.commit()
        create_table(engine, dt)
        return dt
    finally:
        db.close()


def bench_import(engine: Any, dt: Any, rows: list[dict[str, Any]]) -> None:
    """10k 行 JSON 导入."""
    json_text = json.dumps(rows)
    t0 = time.perf_counter()
    ids = transfer.import_rows_from_json(engine, dt, json_text)
    elapsed = time.perf_counter() - t0
    rate = len(ids) / elapsed if elapsed > 0 else float("inf")
    print(f"  import_json: {elapsed:.3f}s ({rate:.0f} rows/s) — {len(ids)} rows")


def bench_queries(engine: Any, dt: Any) -> None:
    """查询吞吐：limit(100) x N + count + filter."""
    md = MetaData()
    md.reflect(bind=engine, only=[dt.db_table_name])
    sa_tbl = md.tables[dt.db_table_name]

    # 1. limit(100) x 100
    t0 = time.perf_counter()
    for _ in range(100):
        with engine.connect() as conn:
            conn.execute(select(sa_tbl).limit(100)).all()
    elapsed = time.perf_counter() - t0
    print(f"  query_limit100_x100: {elapsed:.3f}s ({100 / elapsed:.1f} q/s)")

    # 2. count
    t0 = time.perf_counter()
    with engine.connect() as conn:
        n = conn.execute(select(sa_tbl.c.id)).all()
    elapsed = time.perf_counter() - t0
    print(f"  full_scan: {elapsed:.3f}s ({len(n)} rows)")


def main() -> None:
    parser = argparse.ArgumentParser(description="cndb 性能基准")
    parser.add_argument("--rows", type=int, default=10000, help="导入行数（默认 10000）")
    parser.add_argument("--skip-import", action="store_true", help="跳过导入（表已存在时）")
    args = parser.parse_args()

    print(f"== cndb benchmark  rows={args.rows} ==")
    engine, db_path = setup_db()

    if args.skip_import:
        # 假设表已存在，只跑查询
        from sqlalchemy.orm import sessionmaker

        S = sessionmaker(bind=engine)
        db = S()
        dt = db.query(DataTable).filter_by(name="bench").first()
        if dt is None:
            print("  ERROR: skip-import 但 bench 表不存在")
            sys.exit(1)
        db.close()
        bench_queries(engine, dt)
        return

    dt = create_bench_table(engine)

    # 生成数据
    categories = ["A", "B", "C"]
    rows = [
        {
            "name": f"row_{i}",
            "category": categories[i % 3],
            "score": i * 7 % 1000,
            "active": i % 2 == 0,
        }
        for i in range(args.rows)
    ]

    print(f"  db: {db_path}")
    bench_import(engine, dt, rows)
    bench_queries(engine, dt)
    print("== done ==")


if __name__ == "__main__":
    main()
