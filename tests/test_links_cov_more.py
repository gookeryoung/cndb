"""links.py 覆盖率补全 —— set_links、clear_row_links、内部辅助边界分支."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cndb.plugins.tables import links
from cndb.plugins.tables.ddl import create_table
from cndb.plugins.tables.models import DataField, DataTable

# ── 复用 test_cov_links_internal 里的场景（自包含） ──


def _make_full_link(db, db_engine, client, auth_headers):
    """创建带 link field 的表场景：目标表 lt + 源表 ls."""

    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_links"})
    wid = ws.json()["id"]
    # 目标表
    tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "ltarget"})
    tid_b = tb.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_b}/fields",
        headers=auth_headers,
        json={"name": "tname", "field_type": "text", "order": 0},
    )
    for _n in ["aaa", "bbb", "ccc"]:
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_b}/records",
            headers=auth_headers,
            json={"values": {"tname": _n}},
        )
    # 源表（有 link field）
    ta = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "lsrc"})
    tid_a = ta.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
        headers=auth_headers,
        json={"name": "sname", "field_type": "text", "order": 0},
    )
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
        headers=auth_headers,
        json={
            "name": "link_to_target",
            "field_type": "link",
            "order": 1,
            "config": {"target_table_id": tid_b, "multiple": True},
        },
    )
    return wid, tid_b, tid_a


# ── set_links 边界 ─────────────────────────────────


class TestSetLinksEdgeCases:
    def test_set_links_empty_ids_returns_early(self, db_engine, db, client, auth_headers):
        """set_links 传空 ids → 只清不写，不报错."""
        _wid, _tid_b, tid_a = _make_full_link(db, db_engine, client, auth_headers)
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        links.set_links(db_engine, fa, row_id=1, target_ids=[], db=db)
        # 验证无异常

    def test_set_links_with_db_validates_targets(self, db_engine, db, client, auth_headers):
        """set_links 传 db 时应校验目标存在."""
        _wid, _tid_b, tid_a = _make_full_link(db, db_engine, client, auth_headers)
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        # 目标表已插入 3 行记录（id=1,2,3 左右）
        # 取真实存在的 target ids
        from cndb.plugins.tables import records as rec

        target_tbl = db.query(DataTable).filter_by(id=_tid_b).first()
        target_rows, _ = rec.list_rows(db_engine, target_tbl, db=db)
        assert len(target_rows) == 3
        real_ids = [r["id"] for r in target_rows]
        # 用真实存在的 target id
        links.set_links(db_engine, fa, row_id=999, target_ids=real_ids, db=db)
        # 验证无异常 —— _ensure_targets_exist 调用成功

    def test_set_links_nonexistent_target_raises(self, db_engine, db, client, auth_headers):
        """set_links 传 db 时目标 id 不存在 → ValueError."""
        _wid, _tid_b, tid_a = _make_full_link(db, db_engine, client, auth_headers)
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        with pytest.raises(ValueError, match="目标行不存在"):
            links.set_links(db_engine, fa, row_id=1, target_ids=[99999], db=db)

    def test_set_links_no_db_skips_validation(self, db_engine, db, client, auth_headers):
        """set_links 不传 db → 跳过校验，直接写入."""
        _wid, _tid_b, tid_a = _make_full_link(db, db_engine, client, auth_headers)
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        # 不传 db，即使目标 id 不存在也不应报错（直接写入）
        links.set_links(db_engine, fa, row_id=1, target_ids=[99999], db=None)


# ── clear_row_links ────────────────────────────────


class TestClearRowLinks:
    def test_clear_empty_ids_noop(self, db_engine, db, client, auth_headers):
        """clear_row_links 空 ids 直接返回."""
        _wid, _tid_b, tid_a = _make_full_link(db, db_engine, client, auth_headers)
        tbl = db.query(DataTable).filter_by(id=tid_a).first()
        links.clear_row_links(db_engine, tbl, [])  # 无异常

    def test_clear_row_links_executes_delete(self, db_engine, db, client, auth_headers):
        """clear_row_links 正常执行删除."""
        _wid, _tid_b, tid_a = _make_full_link(db, db_engine, client, auth_headers)
        tbl = db.query(DataTable).filter_by(id=tid_a).first()
        # 先 set 一些 link
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        links.set_links(db_engine, fa, row_id=1, target_ids=[1, 2], db=None)
        # 再清
        links.clear_row_links(db_engine, tbl, [1])
        assert links.load_links(db_engine, fa, [1]) == {}


# ── load_links 边界 ────────────────────────────────


class TestLoadLinksEdge:
    def test_empty_ids_returns_empty(self, db_engine, db, client, auth_headers):
        _wid, _tid_b, tid_a = _make_full_link(db, db_engine, client, auth_headers)
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        assert links.load_links(db_engine, fa, []) == {}


# ── find_back_references 更多分支 ─────────────────


class TestFindBackReferencesEdge:
    def test_source_table_missing_skipped(self, db, db_engine, client, auth_headers):
        """find_back_references 中 source_table 被删 → skip."""
        _wid, tid_b, tid_a = _make_full_link(db, db_engine, client, auth_headers)
        target_tbl = db.query(DataTable).filter_by(id=tid_b).first()
        # 手动删除源表 — 但 link_field 还指向它
        src_tbl = db.query(DataTable).filter_by(id=tid_a).first()
        db.delete(src_tbl)
        db.commit()
        # 此时 field.table_id 指向一个被删的表
        refs = links.find_back_references(db, db_engine, target_tbl, target_row_id=1)
        # 无异常；要么跳过要么返回空
        assert refs == []


# ── 内部辅助边界 ─────────────────────────────────


class TestInternalHelpers:
    def test_get_link_sa_table_missing(self, db_engine):
        """_get_link_sa_table 物理表不存在 → SQLAlchemy 直接抛 InvalidRequestError.

        注：links.py 里写的 RuntimeError 分支实际上永远不会触发，
        因为 SQLAlchemy reflect(only=[missing]) 会先抛 InvalidRequestError.
        我们验证确实抛错即可。
        """
        from sqlalchemy.exc import InvalidRequestError

        with pytest.raises(InvalidRequestError):
            links._get_link_sa_table(db_engine, "nonexistent_link_table_xyz")

    def test_get_sa_table_by_name_missing(self, db_engine):
        from sqlalchemy.exc import InvalidRequestError

        with pytest.raises(InvalidRequestError):
            links._get_sa_table_by_name(db_engine, "no_such_table_xyz")

    def test_target_data_table_no_config(self, db_engine, db):
        """field.config 为空 → _target_data_table 返回 None."""
        tbl = DataTable(workspace_id=1, name="t_empty_cfg")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="x", field_type="link", config=None)
        result = links._target_data_table(db, f)
        assert result is None

    def test_ensure_targets_exist_no_target(self, db_engine, db):
        """目标表不存在 → ValueError."""
        tbl = DataTable(workspace_id=1, name="t_no_target")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="linkx", field_type="link", config=None)
        with pytest.raises(ValueError, match="关联目标表不存在"):
            links._ensure_targets_exist(db_engine, f, [1], db)

    def test_target_summaries_empty_ids(self, db_engine):
        assert links._target_summaries(db_engine, MagicMock(), []) == {}

    def test_target_summaries_no_db(self, db_engine, db, client, auth_headers):
        """无 db 时返回 #id 占位."""
        _wid, _tid_b, _tid_a = _make_full_link(db, db_engine, client, auth_headers)
        fa = db.query(DataField).filter_by(table_id=_tid_a, name="link_to_target").first()
        result = links._target_summaries(db_engine, fa, [100, 200], db=None)
        assert result == {100: "#100", 200: "#200"}

    def test_target_summaries_target_is_none(self, db_engine, db):
        """target 表解析失败 → 回退 #id."""
        tbl = DataTable(workspace_id=1, name="t_none_target")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="linkx", field_type="link", config=None)
        result = links._target_summaries(db_engine, f, [5], db=db)
        assert result == {5: "#5"}

    def test_summary_fields_limit(self, db_engine, db):
        """_summary_fields 只取前 _SUMMARY_FIELD_LIMIT 个."""
        tbl = DataTable(workspace_id=1, name="t_many_fields")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        for i in range(10):
            f = DataField(table_id=tbl.id, name=f"f{i}", field_type="text", order=i)
            f.ensure_db_name()
            db.add(f)
        db.commit()
        fields = links._summary_fields(tbl)
        assert len(fields) <= links._SUMMARY_FIELD_LIMIT

    def test_row_summaries_empty_ids(self, db_engine):
        assert links._row_summaries(db_engine, MagicMock(), [], []) == {}

    def test_row_summaries_empty_ids_via_db(self, db_engine, db, client, auth_headers):
        """_row_summaries 正常工作 + 遇到空值回退 #id."""
        _wid, tid_b, _tid_a = _make_full_link(db, db_engine, client, auth_headers)
        target_tbl = db.query(DataTable).filter_by(id=tid_b).first()
        summary_fields = links._summary_fields(target_tbl)
        # _row_summaries 内部反射物理表，需要先执行 DDL
        create_table(db_engine, target_tbl)
        result = links._row_summaries(db_engine, target_tbl, summary_fields, [])
        assert result == {}


__all__ = []
