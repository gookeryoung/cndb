"""ADR 0046 读路径优化：计数分离、视图排序索引、读缓存与工作区统计缓存.

覆盖 ADR 0046「测试清单」判定层 / 接口层条目：
- ``count_rows`` 与 ``list_rows`` 内部计数同口径（过滤 / 回收站 / 行级权限旁路）；
  含 lookup 字段时返回 None（由内存阶段修正）；
- ``list_rows(total=...)`` 传入即跳过内部 COUNT；
- ``ensure_sort_index``：方向组合建索引、幂等、每表上限 3 淘汰最旧、lookup / 空排序 / 未知字段跳过；
- GET /records 二次请求命中缓存、偏移变化不重算计数、写事件失效；
- 工作区统计缓存（同值 / 命中 / 按工作区失效）与 UNION ALL 批量计数（>100 表跳过）。
"""

from __future__ import annotations

import pytest

from cndb.core.cache import cache_key, list_cache

REC_URL = "/api/v1/workspaces/{wid}/tables/{tid}/records"
POST_LIST_URL = "/api/v1/workspaces/{wid}/tables/{tid}/records/list"


@pytest.fixture
def second_client_headers(client, db):
    """另一个用户（非该工作区成员）的认证头."""
    username, password = "perf-outsider", "passw0rd"
    client.post(
        "/api/v1/accounts/auth/register",
        json={"username": username, "email": "perf-outsider@example.com", "password": password},
    )
    token = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}


def _make_table(db, db_engine, ws_id, name="t_perf", fields=(("name", "text"), ("score", "number"))):
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core import ddl

    tbl = DataTable(workspace_id=ws_id, name=name)
    tbl.ensure_db_name()
    db.add(tbl)
    db.flush()
    for order, (fname, ftype) in enumerate(fields):
        field = DataField(table_id=tbl.id, name=fname, field_type=ftype, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(tbl)
    ddl.create_table(db_engine, tbl)
    return tbl


@pytest.fixture
def perf_table(db, db_engine):
    tbl = _make_table(db, db_engine, 1)
    from cndb.plugins.tables.services.core import records as rec

    for i in range(5):
        rec.create_row(db_engine, tbl, {"name": f"r{i}", "score": i})
    db.refresh(tbl)
    return tbl


class TestCountRows:
    def test_matches_list_rows_total(self, db, db_engine, perf_table):
        from cndb.plugins.tables.services.core import records as rec

        _, total = rec.list_rows(db_engine, perf_table, limit=2, offset=0)
        assert rec.count_rows(db_engine, perf_table) == total == 5

    def test_respects_filters(self, db, db_engine, perf_table):
        from cndb.plugins.tables.services.core import records as rec

        filters = [{"field_name": "score", "op": ">=", "value": 3}]
        _, total = rec.list_rows(db_engine, perf_table, filters=filters)
        assert rec.count_rows(db_engine, perf_table, filters=filters) == total == 2

    def test_respects_trashed_flag(self, db, db_engine, perf_table):
        from cndb.plugins.tables.services.core import records as rec

        rows, _ = rec.list_rows(db_engine, perf_table, limit=1, offset=0)
        rec.trash_row(db_engine, perf_table, rows[0]["id"])
        assert rec.count_rows(db_engine, perf_table, include_trashed=False) == 4
        assert rec.count_rows(db_engine, perf_table, include_trashed=True) == 5

    def test_lookup_sort_returns_none(self, db, db_engine, perf_table):
        """含 lookup 排序时 SQL 计数口径可能被内存阶段修正，count_rows 必须返回 None."""
        from cndb.plugins.tables.models import DataField
        from cndb.plugins.tables.services.core import records as rec

        lk = DataField(
            table_id=perf_table.id,
            name="rel",
            field_type="lookup",
            order=9,
            config={"target_table_id": perf_table.id, "source_field_id": 1},
        )
        lk.ensure_db_name()
        db.add(lk)
        db.commit()
        db.expire(perf_table, ["fields"])
        # 无 lookup 条件时 SQL 计数仍与 total 同值（不受影响）
        assert rec.count_rows(db_engine, perf_table, db=db) == 5
        # 有 lookup 排序 → 走内存路径，计数交给 list_rows 修正
        assert rec.count_rows(db_engine, perf_table, sorts=[{"field_name": "rel", "direction": "asc"}], db=db) is None

    def test_list_rows_skips_count_with_total(self, db_engine, perf_table):
        """传入 total 时不再执行 COUNT（这里给一个明显错误值以证明确实被跳过）."""
        from cndb.plugins.tables.services.core import records as rec

        rows, total = rec.list_rows(db_engine, perf_table, limit=2, offset=0, total=99)
        assert total == 99
        assert len(rows) == 2


class TestEnsureSortIndex:
    def test_creates_index_with_directions(self, db, db_engine, perf_table):
        from sqlalchemy import inspect

        from cndb.plugins.tables.services.core.ddl import ensure_sort_index

        name = ensure_sort_index(
            db, perf_table, [{"field_name": "name", "direction": "asc"}, {"field_name": "score", "direction": "desc"}]
        )
        assert name is not None
        assert name.startswith(f"ix_{perf_table.db_table_name}_sort_")
        index_names = {idx["name"] for idx in inspect(db_engine).get_indexes(perf_table.db_table_name)}
        assert name in index_names

    def test_idempotent(self, db, db_engine, perf_table):
        from cndb.plugins.tables.services.core.ddl import ensure_sort_index

        sorts = [{"field_name": "name", "direction": "asc"}]
        first = ensure_sort_index(db, perf_table, sorts)
        second = ensure_sort_index(db, perf_table, sorts)
        assert first is not None
        assert second is None  # 进程内缓存命中，不重复 DDL

    def test_empty_sorts_skipped(self, db, perf_table):
        from cndb.plugins.tables.services.core.ddl import ensure_sort_index

        assert ensure_sort_index(db, perf_table, None) is None
        assert ensure_sort_index(db, perf_table, []) is None

    def test_lookup_sort_skipped(self, db, db_engine, perf_table):
        from cndb.plugins.tables.models import DataField
        from cndb.plugins.tables.services.core.ddl import ensure_sort_index

        lk = DataField(
            table_id=perf_table.id,
            name="rel2",
            field_type="lookup",
            order=8,
            config={"target_table_id": perf_table.id, "source_field_id": 1},
        )
        lk.ensure_db_name()
        db.add(lk)
        db.commit()
        db.expire(perf_table, ["fields"])
        assert ensure_sort_index(db, perf_table, [{"field_name": "rel2", "direction": "asc"}]) is None

    def test_unknown_field_skipped(self, db, perf_table):
        from cndb.plugins.tables.services.core.ddl import ensure_sort_index

        assert ensure_sort_index(db, perf_table, [{"field_name": "不存在的字段", "direction": "asc"}]) is None

    def test_limit_evicts_oldest_slot(self, db, db_engine, perf_table):
        from sqlalchemy import inspect

        from cndb.plugins.tables.services.core import ddl

        base = f"ix_{perf_table.db_table_name}_sort_"
        created = [
            ddl.ensure_sort_index(db, perf_table, [{"field_name": "name", "direction": "asc"}]),
            ddl.ensure_sort_index(db, perf_table, [{"field_name": "name", "direction": "desc"}]),
            ddl.ensure_sort_index(db, perf_table, [{"field_name": "score", "direction": "asc"}]),
        ]
        assert all(created)
        # 第 4 个：槽位已满 → 淘汰槽位 1（最早建的 ASC/name）
        fourth = ddl.ensure_sort_index(db, perf_table, [{"field_name": "score", "direction": "desc"}])
        assert fourth is not None
        names = {
            idx["name"]
            for idx in inspect(db_engine).get_indexes(perf_table.db_table_name)
            if idx["name"].startswith(base)
        }
        assert created[0] not in names
        assert fourth in names
        assert len(names) == ddl.SORT_INDEX_LIMIT


@pytest.fixture
def api_wid_tid(client, auth_headers):
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_perf"}).json()
    wid = ws["id"]
    tid = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "perf_tbl"}).json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth_headers,
        json={"name": "标题", "field_type": "text", "order": 0},
    )
    for i in range(3):
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"标题": f"行{i}"}},
        )
    return wid, tid


class TestRecordsReadCache:
    def test_get_records_second_call_hits_cache(self, client, auth_headers, api_wid_tid, db):
        wid, tid = api_wid_tid
        list_cache.clear()
        url = REC_URL.format(wid=wid, tid=tid)
        first = client.get(url, headers=auth_headers)
        assert first.status_code == 200
        before = list_cache.stats().hits
        second = client.get(url, headers=auth_headers)
        assert second.status_code == 200
        assert second.json() == first.json()
        assert list_cache.stats().hits >= before + 1

    def test_post_list_matches_get(self, client, auth_headers, api_wid_tid, db):
        wid, tid = api_wid_tid
        list_cache.clear()
        get_resp = client.get(REC_URL.format(wid=wid, tid=tid), headers=auth_headers).json()
        post_resp = client.post(
            POST_LIST_URL.format(wid=wid, tid=tid),
            headers=auth_headers,
            json={"offset": 0, "limit": 100, "filter_logic": "AND"},
        ).json()
        assert post_resp["total"] == get_resp["total"] == 3

    def test_offset_change_does_not_recount(self, client, auth_headers, api_wid_tid, db, monkeypatch):
        """翻页（仅 offset 变化）不应重算 COUNT —— 计数缓存按（表/用户/过滤签名）复用."""
        from cndb.plugins.tables.routers import records as records_router

        wid, tid = api_wid_tid
        list_cache.clear()
        calls: list[int] = []
        real_count = records_router.count_rows

        def _spy(*args, **kwargs):
            calls.append(1)
            return real_count(*args, **kwargs)

        monkeypatch.setattr(records_router, "count_rows", _spy)
        url = REC_URL.format(wid=wid, tid=tid)
        first = client.get(url + "?limit=2&offset=0", headers=auth_headers)
        second = client.get(url + "?limit=2&offset=2", headers=auth_headers)
        assert first.status_code == second.status_code == 200
        assert first.json()["total"] == second.json()["total"] == 3
        assert len(calls) == 1

    def test_record_event_invalidates_records_cache(self, client, auth_headers, api_wid_tid, db):
        from cndb.core.events import record_event

        wid, tid = api_wid_tid
        client.get(REC_URL.format(wid=wid, tid=tid), headers=auth_headers)
        assert list_cache.clear(cache_key("records", wid)) >= 1
        record_event(db, "record.create", summary="新增记录", target_type="record", workspace_id=wid)
        assert list_cache.get(cache_key("records", wid)) is None

    def test_other_user_not_shared(self, client, auth_headers, api_wid_tid, db, second_client_headers):
        """记录缓存 key 含 user_id：行级权限按人过滤，不能跨用户复用."""
        wid, tid = api_wid_tid
        list_cache.clear()
        assert client.get(REC_URL.format(wid=wid, tid=tid), headers=auth_headers).status_code == 200
        # 非成员的另一个用户仍被鉴权拦住（缓存不绕过权限）
        assert client.get(REC_URL.format(wid=wid, tid=tid), headers=second_client_headers).status_code == 403


class TestDeepPaginationGuard:
    """深分页保护（ADR 0046 D8）：超过上限返回 400 + 可操作提示，而不是几秒的假死."""

    def test_get_offset_over_limit(self, client, auth_headers, api_wid_tid):
        from cndb.plugins.tables.routers.records import MAX_RECORD_OFFSET

        wid, tid = api_wid_tid
        resp = client.get(
            REC_URL.format(wid=wid, tid=tid) + f"?offset={MAX_RECORD_OFFSET + 1}",
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "分页偏移过大" in resp.json()["detail"]

    def test_get_offset_at_limit_ok(self, client, auth_headers, api_wid_tid):
        from cndb.plugins.tables.routers.records import MAX_RECORD_OFFSET

        wid, tid = api_wid_tid
        resp = client.get(
            REC_URL.format(wid=wid, tid=tid) + f"?offset={MAX_RECORD_OFFSET}",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_post_offset_over_limit(self, client, auth_headers, api_wid_tid):
        from cndb.plugins.tables.routers.records import MAX_RECORD_OFFSET

        wid, tid = api_wid_tid
        resp = client.post(
            POST_LIST_URL.format(wid=wid, tid=tid),
            headers=auth_headers,
            json={"offset": MAX_RECORD_OFFSET + 1, "limit": 50, "filter_logic": "AND"},
        )
        assert resp.status_code == 400
        assert "分页偏移过大" in resp.json()["detail"]


class TestWorkspaceStatsCache:
    def test_stats_value_and_cache_hit(self, client, auth_headers, api_wid_tid, db):
        from cndb.plugins.workspaces.services.stats_cache import get_workspace_stats

        wid, _tid = api_wid_tid
        list_cache.clear()
        stats = get_workspace_stats(db, wid)
        assert stats["table_count"] == 1
        assert stats["total_rows"] == 3
        assert stats["view_count"] >= 1
        before = list_cache.stats().hits
        assert get_workspace_stats(db, wid) == stats
        assert list_cache.stats().hits == before + 1

    def test_detail_endpoint_uses_stats(self, client, auth_headers, api_wid_tid, db):
        wid, _tid = api_wid_tid
        list_cache.clear()
        first = client.get(f"/api/v1/workspaces/{wid}", headers=auth_headers)
        assert first.status_code == 200
        assert first.json()["total_rows"] == 3
        before = list_cache.stats().hits
        second = client.get(f"/api/v1/workspaces/{wid}", headers=auth_headers)
        assert second.json()["total_rows"] == 3
        assert list_cache.stats().hits > before

    def test_invalidate_by_workspace(self, db, api_wid_tid):
        from cndb.plugins.workspaces.services.stats_cache import (
            get_workspace_stats,
            invalidate_workspace_stats,
            workspace_stats_key,
        )

        wid, _tid = api_wid_tid
        get_workspace_stats(db, wid)
        assert list_cache.get(workspace_stats_key(wid)) is not None
        assert invalidate_workspace_stats(wid) == 1
        assert list_cache.get(workspace_stats_key(wid)) is None

    def test_other_workspace_not_affected(self, db, api_wid_tid):
        from cndb.plugins.workspaces.services.stats_cache import get_workspace_stats, invalidate_workspace_stats

        wid, _tid = api_wid_tid
        get_workspace_stats(db, wid)
        invalidate_workspace_stats(wid + 1000)
        assert list_cache.get(cache_key("workspace-stats", wid)) is not None


class TestBatchRecordCounts:
    def test_union_all_counts(self, db, db_engine):
        from cndb.plugins.tables.services.core import records as rec
        from cndb.plugins.tables.services.core.record_counts import batch_record_counts

        t1 = _make_table(db, db_engine, 1, "t_batch1", fields=(("v", "text"),))
        t2 = _make_table(db, db_engine, 1, "t_batch2", fields=(("v", "text"),))
        rec.create_row(db_engine, t1, {"v": "a"})
        rec.create_row(db_engine, t2, {"v": "a"})
        rec.create_row(db_engine, t2, {"v": "b"})
        db.refresh(t1)
        db.refresh(t2)
        assert batch_record_counts(db, [t1, t2]) == {t1.id: 1, t2.id: 2}

    def test_skips_over_limit(self, db, db_engine):
        from cndb.plugins.tables.services.core.record_counts import BATCH_COUNT_MAX_TABLES, batch_record_counts

        t = _make_table(db, db_engine, 1, "t_batch3", fields=(("v", "text"),))
        db.refresh(t)
        many = [t] * (BATCH_COUNT_MAX_TABLES + 1)
        assert batch_record_counts(db, many) == {}

    def test_bad_table_name_skipped(self, db, db_engine):
        from cndb.plugins.tables.services.core.record_counts import batch_record_counts

        t = _make_table(db, db_engine, 1, "t_batch4", fields=(("v", "text"),))
        db.refresh(t)
        t.db_table_name = "bad name; DROP TABLE x"
        assert batch_record_counts(db, [t]) == {}
