"""性能基准 — 重复检测（治理 detect）10 万行 < 60s（plan AC-6）.

用法：
    uv run python scripts/bench_governance_detect.py --rows 100000 --check
    uv run python scripts/bench_governance_detect.py --rows 10000

--check 时检测耗时超过 60s 以非零码退出（用于门禁）。
默认在临时 SQLite 上运行；可用 --db-url 指向 PostgreSQL 等真实库。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent / ".." / "src"))

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from cndb.core.config import settings
from cndb.models.base import Base
from cndb.plugins.tables.models import DataField, DataTable, GovernanceTask
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import bulk_create
from cndb.plugins.tables.services.governance.tasks import execute_governance_task

# AC-6 门槛：10 万行检测 < 60s
BUDGET_SECONDS = 60.0
# 单批插入行数（bulk_create 单批过大易撑爆参数上限）
INSERT_BATCH = 5000


def setup_db(db_url: str | None) -> tuple[Any, str]:
    """创建基准数据库：显式传 --db-url 用真实库，否则临时 SQLite."""
    # 确保所有模型注册到 Base.metadata（create_all 建全量 schema 需要外键目标表就绪）
    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401  -- 副作用导入：注册模型到 Base.metadata

    if db_url:
        settings.DATABASE_URL = db_url
        engine = create_engine(db_url)
        return engine, db_url
    db_path = Path(tempfile.gettempdir()) / "cndb_bench_detect.db"
    if db_path.exists():
        db_path.unlink()
    settings.DATABASE_URL = f"sqlite:///{db_path}"
    engine = create_engine(settings.DATABASE_URL, connect_args={"check_same_thread": False})
    return engine, str(db_path)


def create_bench_table(engine: Any) -> Any:
    """建基准表：单列 name 用于判重."""
    S = sessionmaker(bind=engine)
    db: Session = S()
    try:
        dt = DataTable(workspace_id=1, name="bench_governance")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        f = DataField(table_id=dt.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(dt)
        ddl.create_table(engine, dt)
        return dt
    finally:
        db.close()


def insert_rows(engine: Any, dt: Any, rows: int) -> None:
    """成对生成重复数据：i//2 使每两行一组精确重复."""
    S = sessionmaker(bind=engine)
    db: Session = S()
    try:
        for start in range(0, rows, INSERT_BATCH):
            batch = [{"name": f"name_{(start + j) // 2}"} for j in range(min(INSERT_BATCH, rows - start))]
            bulk_create(engine, dt, batch)
        db.commit()
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="重复检测性能基准")
    parser.add_argument("--rows", type=int, default=100000, help="数据行数（默认 100000）")
    parser.add_argument("--check", action="store_true", help="超过 60s 门槛时以非零码退出")
    parser.add_argument("--db-url", default=None, help="自定义数据库 URL（默认临时 SQLite）")
    args = parser.parse_args()

    print(f"== governance detect benchmark rows={args.rows} ==")
    engine, db_url = setup_db(args.db_url)
    Base.metadata.create_all(engine)
    print(f"  db: {db_url}")

    dt = create_bench_table(engine)
    t_insert = time.perf_counter()
    insert_rows(engine, dt, args.rows)
    print(f"  插入 {args.rows} 行: {time.perf_counter() - t_insert:.2f}s")

    S = sessionmaker(bind=engine)
    db: Session = S()
    try:
        task = GovernanceTask(table_id=dt.id, kind="detect", config={"match_fields": ["name"]})
        db.add(task)
        db.commit()
        db.refresh(task)

        t0 = time.perf_counter()
        execute_governance_task(db, task.id)
        elapsed = time.perf_counter() - t0
        db.refresh(task)
        report = task.report
    finally:
        db.close()

    rate = args.rows / elapsed if elapsed > 0 else float("inf")
    print(f"  detect: {elapsed:.2f}s ({rate:.0f} rows/s) — status={task.status}")
    print(f"  报告字节: {len(report)}")
    engine.dispose()

    if args.check:
        if elapsed > BUDGET_SECONDS:
            print(f"FAIL: {elapsed:.2f}s 超过 {BUDGET_SECONDS}s 门槛")
            sys.exit(1)
        if task.status != "done":
            print(f"FAIL: 任务终态 {task.status} != done")
            sys.exit(1)
        print(f"PASS: {elapsed:.2f}s <= {BUDGET_SECONDS}s")
    print("== done ==")


if __name__ == "__main__":
    main()
