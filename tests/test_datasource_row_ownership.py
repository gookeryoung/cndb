"""datasource ADR 0043 P0：行所有权边界与就地改写单测.

覆盖：

- ``to_records`` 保证每行独立 dict；
- ``fill_entrant`` 默认仍复制（公共语义不变），``inplace=True`` 时就地改写且返回入参同一对象；
- ``run_pipeline`` 流式回调的每批行互不共享同一 dict（跨批不污染）；
- ``_StreamingState.on_batch`` 不再复制行 dict（只做浅列表拷贝）。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from cndb.plugins.datasource.providers.base import RequestSpec, SyncJobSpec
from cndb.plugins.datasource.services import runner
from cndb.plugins.datasource.services.cursor import CursorConfig
from cndb.plugins.datasource.services.pipeline import (
    fill_entrant,
    run_pipeline,
    to_records,
)
from cndb.plugins.datasource.services.write import WriteOutcome


def _job(**request_kwargs: Any) -> SyncJobSpec:
    return SyncJobSpec(
        request=RequestSpec(url_template="https://api.example.com/w", **request_kwargs),
        entrant_param="symbol",
    )


class TestDefaultCopySemantics:
    """默认路径必须保持「返回新 dict」的既有公共语义."""

    def test_to_records_returns_independent_dicts(self):
        source = {"symbol": "sh600519", "v": 1}
        rows = to_records([source])
        assert rows[0] == source
        assert rows[0] is not source

    def test_fill_entrant_copies_by_default(self):
        row = {"v": 1}
        assert fill_entrant([row], "symbol", "sh600519")[0] is not row

    def test_source_row_not_mutated_by_default(self):
        row = {"v": 1}
        fill_entrant([row], "symbol", "sh600519")
        assert row == {"v": 1}


class TestInplaceSemantics:
    """``inplace=True``：就地改写、保持同一对象，``setdefault`` 口径不变."""

    def test_fill_entrant_inplace(self):
        rows = [{"symbol": "sh600519", "v": 1}, {"v": 2}]
        filled = fill_entrant(rows, "symbol", "sz000001", inplace=True)
        assert [id(row) for row in filled] == [id(row) for row in rows]
        assert filled[0]["symbol"] == "sh600519"  # 自带值优先
        assert filled[1]["symbol"] == "sz000001"

    def test_fill_entrant_inplace_no_param_is_passthrough(self):
        rows = [{"v": 1}]
        filled = fill_entrant(rows, None, "sh600519", inplace=True)
        assert filled[0] is rows[0]


class TestPipelineRowOwnership:
    """管线交出的行每批都是独立 dict，批间不共享."""

    def test_batches_do_not_share_row_objects(self):
        batches: list[list[dict[str, Any]]] = []

        def fetch(_config: Any) -> list[dict[str, Any]]:
            return [{"symbol": "sh600519", "v": i} for i in range(4)]

        run_pipeline(
            _job(),
            fetch=fetch,
            on_batch=lambda batch: batches.append(list(batch)),
            batch_size=2,
        )
        first, second = batches
        assert [row["v"] for row in first] == [0, 1]
        assert [row["v"] for row in second] == [2, 3]
        ids = {id(row) for batch in batches for row in batch}
        assert len(ids) == 4

    def test_inplace_chain_fills_entrant(self):
        """就地链路下 setdefault 口径不变（响应自带值优先）."""
        batches: list[list[dict[str, Any]]] = []

        run_pipeline(
            SyncJobSpec(
                request=RequestSpec(url_template="https://api.example.com/w"),
                entrant_param="symbol",
                entrant_values=("sh600519",),
            ),
            fetch=lambda _config: [{"close": 1.0}],
            on_batch=lambda batch: batches.append(list(batch)),
            batch_size=10,
        )
        assert batches == [[{"close": 1.0, "symbol": "sh600519"}]]


class TestStreamingOnBatchNoCopy:
    """ADR 0043 D2：``on_batch`` 只做浅列表拷贝，行对象沿用管线交出对象."""

    def test_on_batch_forwards_same_row_objects(self, db, monkeypatch):
        captured: list[list[dict[str, Any]]] = []

        def fake_persist(_db, _job, rows, **_kwargs):
            captured.append(rows)
            return WriteOutcome(fetched=len(rows))

        monkeypatch.setattr(runner, "_persist_rows", fake_persist)
        job = SimpleNamespace(entrant_param=None, field_mapping={}, id=1)
        state = runner._StreamingState(
            db,
            job,
            CursorConfig(strategy="none"),
            user=None,
            lease=None,
        )
        rows = [{"v": 1}, {"v": 2}]
        state.on_batch(rows)

        assert captured[0] is not rows  # 列表仍是新对象（保留 list 契约）
        assert [id(row) for row in captured[0]] == [id(row) for row in rows]
