"""field_mapping 性能基准 — 大表场景耗时."""

from __future__ import annotations

import pytest

from cndb.plugins.tables.models import DataField
from cndb.plugins.tables.services.importing.field_mapping import (
    apply_gap_filling,
    remap_row,
    suggest_mapping,
)


def _mkf(name: str, ft: str = "text") -> DataField:
    return DataField(name=name, field_type=ft)


@pytest.mark.slow
class TestSuggestMappingPerf:
    """suggest_mapping 在不同规模下的耗时不应超过经验阈值."""

    @pytest.mark.skipif(__import__("os").environ.get("CI", "") != "", reason="CI 并行模式下耗时不稳定")
    def test_small_10x10(self):
        src = [_mkf(f"src_{i}", "text") for i in range(10)]
        dst = [_mkf(f"dst_{i}", "text") for i in range(10)]
        import time

        t = time.perf_counter()
        for _ in range(10):
            suggest_mapping(src, dst)
        elapsed = time.perf_counter() - t
        # 10x10 匹配 10 次 → 应 < 30ms（单次 3ms — 含 SequenceMatcher 开销）
        assert elapsed < 0.030, f"10x10x10 took {elapsed * 1000:.1f}ms"

    @pytest.mark.skipif(__import__("os").environ.get("CI", "") != "", reason="CI 并行模式下耗时不稳定")
    def test_medium_100x100(self):
        src = [_mkf(f"field_{i}", "text") for i in range(100)]
        dst = [_mkf(f"field_{i}", "text") for i in range(100)]
        import time

        t = time.perf_counter()
        suggest_mapping(src, dst)
        elapsed = time.perf_counter() - t
        # 100x100 (10k pair) 应 < 500ms — SequenceMatcher 逐对比较
        assert elapsed < 0.500, f"100x100 took {elapsed * 1000:.1f}ms"

    @pytest.mark.skipif(__import__("os").environ.get("CI", "") != "", reason="CI 并行模式下耗时不稳定")
    def test_large_500x500(self):
        src = [_mkf(f"col_{i}", "text") for i in range(500)]
        dst = [_mkf(f"col_{i}", "text") for i in range(500)]
        import time

        t = time.perf_counter()
        suggest_mapping(src, dst)
        elapsed = time.perf_counter() - t
        # 500x500 (250k pair) 应 < 10s — 极端场景，实际表字段数很少过 100
        assert elapsed < 10.0, f"500x500 took {elapsed * 1000:.0f}ms"


@pytest.mark.slow
class TestRemapRowPerf:
    """remap_row + apply_gap_filling 在大数据量下的耗时."""

    @pytest.mark.skipif(__import__("os").environ.get("CI", "") != "", reason="CI 并行模式下耗时不稳定")
    def test_remap_10k_rows_20_cols(self):
        mapping = {f"src_{i}": f"dst_{i}" for i in range(20)}
        rows = [{f"src_{i}": i for i in range(20)} for _ in range(10_000)]
        import time

        t = time.perf_counter()
        for row in rows:
            remap_row(row, mapping)
        elapsed = time.perf_counter() - t
        # 10k x 20 cols → 应 < 100ms
        assert elapsed < 0.100, f"remap 10k rows took {elapsed * 1000:.1f}ms"

    @pytest.mark.skipif(__import__("os").environ.get("CI", "") != "", reason="CI 并行模式下耗时不稳定")
    def test_gap_fill_10k_rows_20_cols(self):
        target_field_map = {f"dst_{i}": _mkf(f"dst_{i}", "text") for i in range(20)}
        rows = [{f"dst_{i}": i for i in range(15)} for _ in range(10_000)]
        missing = [f"dst_{i}" for i in range(15, 20)]
        import time

        t = time.perf_counter()
        for row in rows:
            apply_gap_filling(row, missing, target_field_map, strategy="empty")
        elapsed = time.perf_counter() - t
        assert elapsed < 0.100, f"gap_filling 10k rows took {elapsed * 1000:.1f}ms"


# 如果不关心具体阈值，只是想看看大概量级，用 -s 跑这个
@pytest.mark.skip(reason="手工测试")
def test_perf_probe():
    """打印不同规模的 suggest_mapping 耗时 — 人工观察用."""
    import time

    for n in [10, 50, 100, 200, 500]:
        src = [_mkf(f"s{i}", "text") for i in range(n)]
        dst = [_mkf(f"d{i}", "text") for i in range(n)]
        t = time.perf_counter()
        suggest_mapping(src, dst)
        print(f"  suggest_mapping {n:4d}x{n:<4d}: {(time.perf_counter() - t) * 1000:7.2f}ms")
