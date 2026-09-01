"""行数据服务层压测基准：批量插入/读取/过滤/分页吞吐统计.

标记 slow：`make check` 排除，单独运行：
`uv run pytest tests/test_bench_rows.py -m slow -s --no-cov`
"""

from __future__ import annotations

from decimal import Decimal
from time import perf_counter
from typing import Any

import pytest
from django.db import connection

from cndb.tables import query, records, services
from cndb.tables.models import DataTable
from cndb.workspaces.models import Workspace

# 基准数据量与批量规格
TOTAL_ROWS = 1000
BATCH_SIZE = 200


@pytest.mark.slow
@pytest.mark.django_db
def test_row_pipeline_benchmark(workspace: Workspace) -> None:
    """批量插入/全量读/过滤/排序分页四段吞吐基准（结果打印，不断言耗时上限）."""
    table = services.create_table(
        workspace=workspace,  # type: ignore[arg-type]
        name="压测表",
        field_defs=[
            {"name": "标题", "field_type": "text"},
            {"name": "数量", "field_type": "number"},
            {"name": "状态", "field_type": "single_select", "config": {"choices": ["待办", "完成"]}},
        ],
    )
    raw_rows: list[dict[str, Any]] = [
        {"标题": f"记录-{index}", "数量": Decimal(index), "状态": "待办" if index % 2 == 0 else "完成"}
        for index in range(TOTAL_ROWS)
    ]

    # 批量插入（clean_row + insert_rows，每批 BATCH_SIZE 行）
    start = perf_counter()
    for offset in range(0, TOTAL_ROWS, BATCH_SIZE):
        batch = [records.clean_row(table, row, partial=True) for row in raw_rows[offset : offset + BATCH_SIZE]]
        records.insert_rows(table, batch)
    insert_seconds = perf_counter() - start

    # 全量读取
    start = perf_counter()
    all_rows = records.fetch_rows(table, query.RowQuery())
    fetch_seconds = perf_counter() - start
    assert len(all_rows) == TOTAL_ROWS

    # 过滤查询（等值匹配一半行）
    where, params = query.compile_filters(table, [{"field": "状态", "op": "eq", "value": "待办"}], "AND")
    start = perf_counter()
    filtered = records.fetch_rows(table, query.RowQuery(where=where, params=params))
    filter_seconds = perf_counter() - start
    assert len(filtered) == TOTAL_ROWS // 2

    # 排序分页读（按数量降序取一页 50 条）
    order = query.compile_sortings(table, [{"field": "数量", "desc": True}])
    start = perf_counter()
    page = records.fetch_rows(table, query.RowQuery(order=order, limit=50, offset=0))
    page_seconds = perf_counter() - start
    assert len(page) == 50

    print(
        f"\n基准结果（{TOTAL_ROWS} 行，SQLite 内存库）:\n"
        f"  批量插入  {TOTAL_ROWS / insert_seconds:>10.0f} 行/秒（总耗时 {insert_seconds:.3f}s）\n"
        f"  全量读取  {TOTAL_ROWS / fetch_seconds:>10.0f} 行/秒（总耗时 {fetch_seconds:.3f}s）\n"
        f"  过滤查询  {len(filtered) / filter_seconds:>10.0f} 行/秒（命中 {len(filtered)} 行，总耗时 {filter_seconds:.3f}s）\n"
        f"  排序分页  {len(page) / page_seconds:>10.0f} 行/秒（总耗时 {page_seconds:.3f}s）"
    )

    # 清理物理表，避免测试库残留
    with connection.cursor() as cursor:
        cursor.execute(f'DROP TABLE IF EXISTS "{table.db_table_name}"')
    DataTable.objects.filter(pk=table.pk).delete()
