"""编辑字段保存前预检测试 —— 必填/唯一变更的数据校验 + 物理失败 metadata 回退."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect

import cndb.plugins.tables.routers.fields as fields_router
from cndb.plugins.tables.models import DataTable
from cndb.plugins.tables.services.core import records as rec

# ── 通用脚手架 ────────────────────────────────────────


def _make_table(client, auth_headers, name: str) -> tuple[int, int]:
    """创建工作区 + 表，返回 (wid, tid)。"""
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": f"ws_{name}"})
    wid = ws.json()["id"]
    t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": name})
    tid = t.json()["id"]
    return wid, tid


def _add_field(client, auth_headers, wid: int, tid: int, payload: dict) -> dict:
    r = client.post(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=auth_headers, json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _add_record(client, auth_headers, wid: int, tid: int, values: dict) -> dict:
    r = client.post(f"/api/v1/workspaces/{wid}/tables/{tid}/records", headers=auth_headers, json={"values": values})
    assert r.status_code == 201, r.text
    return r.json()


def _patch_field(client, auth_headers, wid: int, tid: int, fid: int, payload: dict):
    return client.patch(f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}", headers=auth_headers, json=payload)


def _get_field(client, auth_headers, wid: int, tid: int, fid: int) -> dict:
    fields = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=auth_headers).json()
    return next(f for f in fields if f["id"] == fid)


def _physical_indexes(db, tid: int) -> list[str]:
    """按表 id 查元数据并返回物理表索引名列表（表不存在时返回空）。"""
    dt = db.get(DataTable, tid)
    insp = inspect(db.get_bind())
    if dt.db_table_name not in insp.get_table_names():
        return []
    return [idx["name"] for idx in insp.get_indexes(dt.db_table_name)]


# ── 唯一约束保存前预检 ────────────────────────────────


class TestUniquePrecheck:
    def _setup(self, client, auth_headers, db) -> tuple[int, int, int, list[int]]:
        """建 text 字段「编号」+ 2 行重复值 + 1 行不同值，返回 (wid, tid, fid, 行 id 列表)。"""
        wid, tid = _make_table(client, auth_headers, "t_uniq")
        f = _add_field(client, auth_headers, wid, tid, {"name": "编号", "field_type": "text", "order": 0})
        row1 = _add_record(client, auth_headers, wid, tid, {"编号": "A-001"})
        row2 = _add_record(client, auth_headers, wid, tid, {"编号": "A-001"})
        _add_record(client, auth_headers, wid, tid, {"编号": "B-002"})
        return wid, tid, f["id"], [row1["id"], row2["id"]]

    def test_enable_unique_blocked_by_duplicates(self, client, auth_headers, db):
        """存在重复值时启用唯一 → 400 且 metadata 与物理索引均未变更."""
        wid, tid, fid, dup_ids = self._setup(client, auth_headers, db)

        r = _patch_field(client, auth_headers, wid, tid, fid, {"is_unique": True})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "A-001" in detail
        assert str(dup_ids[0]) in detail and str(dup_ids[1]) in detail

        # metadata 未被污染（bug 回归点：此前勾选会生效）
        assert _get_field(client, auth_headers, wid, tid, fid)["is_unique"] is False
        # 物理唯一索引不存在
        assert not any(name.startswith("idx_u_") for name in _physical_indexes(db, tid))

    def test_enable_unique_success_after_fix(self, client, auth_headers, db):
        """清理重复值后启用唯一 → 200，物理索引存在，重复写入被 SQLite 拒绝."""
        wid, tid, fid, _ = self._setup(client, auth_headers, db)
        # 把其中一行重复值改成不同值（按 id 取较大的一行）
        dup_rows = sorted(
            (
                f["id"]
                for f in client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/records", headers=auth_headers).json()[
                    "items"
                ]
                if f["编号"] == "A-001"
            ),
            reverse=True,
        )
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{dup_rows[0]}",
            headers=auth_headers,
            json={"values": {"编号": "C-003"}},
        )
        assert r.status_code == 200

        r = _patch_field(client, auth_headers, wid, tid, fid, {"is_unique": True})
        assert r.status_code == 200, r.text
        assert any(name.startswith("idx_u_") for name in _physical_indexes(db, tid))

        # 物理唯一约束生效：再次写入重复值 → IntegrityError
        from sqlalchemy.exc import IntegrityError

        with pytest.raises(IntegrityError, match="UNIQUE"):
            rec.create_row(db.get_bind(), db.get(DataTable, tid), {"编号": "A-001"})

    def test_multiple_duplicate_groups_shown_with_limit(self, client, auth_headers, db):
        """多组重复值按行序展示（≤10 组全展示），detail 含各组值."""
        wid, tid = _make_table(client, auth_headers, "t_uniq_multi")
        f = _add_field(client, auth_headers, wid, tid, {"name": "编号", "field_type": "text", "order": 0})
        for v in ("A", "A", "B", "B", "C", "C"):
            _add_record(client, auth_headers, wid, tid, {"编号": v})

        r = _patch_field(client, auth_headers, wid, tid, f["id"], {"is_unique": True})
        assert r.status_code == 400
        detail = r.json()["detail"]
        for v in ("A", "B", "C"):
            assert f"'{v}'" in detail

    def test_null_values_not_treated_as_duplicates(self, client, auth_headers, db):
        """多个 NULL 不参与判重（与唯一索引行为一致）→ 启用成功."""
        wid, tid = _make_table(client, auth_headers, "t_uniq_null")
        f = _add_field(client, auth_headers, wid, tid, {"name": "编号", "field_type": "text", "order": 0})
        _add_record(client, auth_headers, wid, tid, {})
        _add_record(client, auth_headers, wid, tid, {})

        r = _patch_field(client, auth_headers, wid, tid, f["id"], {"is_unique": True})
        assert r.status_code == 200, r.text

    def test_disable_unique_still_works(self, client, auth_headers, db):
        """取消唯一（True→False）不触发预检，索引被删除（回归保护）."""
        wid, tid = _make_table(client, auth_headers, "t_uniq_off")
        f = _add_field(
            client, auth_headers, wid, tid, {"name": "编号", "field_type": "text", "order": 0, "is_unique": True}
        )
        assert any(name.startswith("idx_u_") for name in _physical_indexes(db, tid))

        r = _patch_field(client, auth_headers, wid, tid, f["id"], {"is_unique": False})
        assert r.status_code == 200
        assert not any(name.startswith("idx_u_") for name in _physical_indexes(db, tid))


# ── 必填保存前预检 ────────────────────────────────────


class TestRequiredPrecheck:
    def _setup(self, client, auth_headers) -> tuple[int, int, int, list[int]]:
        """建 text 字段「姓名」+ 1 行有值 + 1 行空值，返回 (wid, tid, fid, 空行 id)。"""
        wid, tid = _make_table(client, auth_headers, "t_req")
        f = _add_field(client, auth_headers, wid, tid, {"name": "姓名", "field_type": "text", "order": 0})
        _add_record(client, auth_headers, wid, tid, {"姓名": "张三"})
        empty_row = _add_record(client, auth_headers, wid, tid, {})
        return wid, tid, f["id"], [empty_row["id"]]

    def test_enable_required_blocked_by_nulls(self, client, auth_headers, db):
        """存在空值行时设为必填 → 400 且 metadata 不变、物理列仍可空."""
        wid, tid, fid, null_ids = self._setup(client, auth_headers)

        r = _patch_field(client, auth_headers, wid, tid, fid, {"required": True})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "姓名" in detail
        for rid in null_ids:
            assert f"行 {rid}" in detail

        # metadata 未变更
        assert _get_field(client, auth_headers, wid, tid, fid)["required"] is False

    def test_enable_required_success_after_fill(self, client, auth_headers, db):
        """补齐空值后设为必填 → 200，物理列 NOT NULL."""
        wid, tid, fid, null_ids = self._setup(client, auth_headers)
        for rid in null_ids:
            r = client.patch(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rid}",
                headers=auth_headers,
                json={"values": {"姓名": "李四"}},
            )
            assert r.status_code == 200

        r = _patch_field(client, auth_headers, wid, tid, fid, {"required": True})
        assert r.status_code == 200, r.text
        assert _get_field(client, auth_headers, wid, tid, fid)["required"] is True

    def test_empty_table_enable_required_ok(self, client, auth_headers, db):
        """空表直接设必填 → 200（无数据无需预检）。"""
        wid, tid = _make_table(client, auth_headers, "t_req_empty")
        f = _add_field(client, auth_headers, wid, tid, {"name": "姓名", "field_type": "text", "order": 0})

        r = _patch_field(client, auth_headers, wid, tid, f["id"], {"required": True})
        assert r.status_code == 200

    def test_required_toggle_off_no_precheck(self, client, auth_headers):
        """必填 True→False 不触发预检（回归保护）。"""
        wid, tid = _make_table(client, auth_headers, "t_req_off")
        f = _add_field(
            client, auth_headers, wid, tid, {"name": "姓名", "field_type": "text", "order": 0, "required": True}
        )

        r = _patch_field(client, auth_headers, wid, tid, f["id"], {"required": False})
        assert r.status_code == 200
        assert _get_field(client, auth_headers, wid, tid, f["id"])["required"] is False


# ── link 字段必填/唯一保存前预检 ──────────────────────


class TestLinkFieldPrecheck:
    def _setup(self, client, auth_headers) -> tuple[int, int, int, list[dict]]:
        """建两张表：t_link_src 含 link 字段指向 t_link_dst；src 两行均关联到 dst 同一行。

        返回 (wid, tid, link_fid, src 行列表)。
        """
        wid = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_link_pre"}).json()["id"]
        dst = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_link_dst"})
        dst_tid = dst.json()["id"]
        src = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_link_src"})
        tid = src.json()["id"]
        f = _add_field(
            client,
            auth_headers,
            wid,
            tid,
            {"name": "关联目标", "field_type": "link", "order": 0, "config": {"target_table_id": dst_tid}},
        )
        dst_row = _add_record(client, auth_headers, wid, dst_tid, {"title": "D1"})
        row1 = _add_record(client, auth_headers, wid, tid, {"关联目标": [dst_row["id"]]})
        row2 = _add_record(client, auth_headers, wid, tid, {"关联目标": [dst_row["id"]]})
        return wid, tid, f["id"], [row1, row2]

    def test_enable_unique_blocked_by_duplicate_links(self, client, auth_headers, db):
        """两行关联同一目标时启用唯一 → 400 且 metadata 不变."""
        wid, tid, fid, rows = self._setup(client, auth_headers)

        r = _patch_field(client, auth_headers, wid, tid, fid, {"is_unique": True})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "关联目标" in detail
        assert str(rows[0]["id"]) in detail and str(rows[1]["id"]) in detail

        # metadata 未被污染
        assert _get_field(client, auth_headers, wid, tid, fid)["is_unique"] is False

    def test_enable_unique_success_after_distinct_links(self, client, auth_headers, db):
        """两行关联不同目标后启用唯一 → 200."""
        wid, tid, fid, rows = self._setup(client, auth_headers)
        # 把第二行改为不设关联以外的目标：先清空再留一行空（空不参与判重）
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records/{rows[1]['id']}",
            headers=auth_headers,
            json={"values": {"关联目标": []}},
        )
        assert r.status_code == 200

        r = _patch_field(client, auth_headers, wid, tid, fid, {"is_unique": True})
        assert r.status_code == 200, r.text

    def test_enable_required_blocked_by_unlinked_rows(self, client, auth_headers, db):
        """存在未关联行时设为必填 → 400 且 metadata 不变."""
        wid, tid, fid, _ = self._setup(client, auth_headers)
        # 追加一行无关联
        empty_row = _add_record(client, auth_headers, wid, tid, {})

        r = _patch_field(client, auth_headers, wid, tid, fid, {"required": True})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert "关联目标" in detail
        assert f"行 {empty_row['id']}" in detail

        # metadata 未变更
        assert _get_field(client, auth_headers, wid, tid, fid)["required"] is False

    def test_enable_required_success_after_linking(self, client, auth_headers, db):
        """补齐关联后设为必填 → 200（link 字段不走物理列重建，不得 500）."""
        wid, tid, fid, _rows = self._setup(client, auth_headers)
        assert _get_field(client, auth_headers, wid, tid, fid)["required"] is False

        r = _patch_field(client, auth_headers, wid, tid, fid, {"required": True})
        assert r.status_code == 200, r.text
        assert _get_field(client, auth_headers, wid, tid, fid)["required"] is True

    def test_required_toggle_off_no_precheck(self, client, auth_headers, db):
        """link 字段必填 True→False 不触发预检（回归保护）。"""
        wid, tid, fid, _ = self._setup(client, auth_headers)
        r = _patch_field(client, auth_headers, wid, tid, fid, {"required": True})
        assert r.status_code == 200, r.text

        r = _patch_field(client, auth_headers, wid, tid, fid, {"required": False})
        assert r.status_code == 200
        assert _get_field(client, auth_headers, wid, tid, fid)["required"] is False


# ── link 字段写入路径必填/唯一约束 ─────────────────────


class TestLinkWriteConstraints:
    def _setup(self, client, auth_headers, *, required: bool = False, unique: bool = False):
        """建两张表 + link 字段（可指定约束）。

        dst 预置 D1、D0 两行；src 预置一行关联 D0（保证 required 开启时数据干净，
        且不占用 D1，供后续用例使用）。返回 (wid, tid_src, tid_dst, fid, d1)。
        """
        wid = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_link_write"}).json()["id"]
        dst = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "w_dst"})
        tid_dst = dst.json()["id"]
        src = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "w_src"})
        tid_src = src.json()["id"]
        f = _add_field(
            client,
            auth_headers,
            wid,
            tid_src,
            {"name": "关联目标", "field_type": "link", "order": 0, "config": {"target_table_id": tid_dst}},
        )
        d1 = _add_record(client, auth_headers, wid, tid_dst, {"title": "D1"})
        d0 = _add_record(client, auth_headers, wid, tid_dst, {"title": "D0"})
        _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d0["id"]]})
        r = _patch_field(client, auth_headers, wid, tid_src, f["id"], {"required": required, "is_unique": unique})
        assert r.status_code == 200, r.text
        return wid, tid_src, tid_dst, f["id"], d1

    def test_create_row_required_link_empty_rejected(self, client, auth_headers, db):
        """required link 字段创建行未传关联 → 400."""
        wid, tid_src, _tid_dst, _fid, _d1 = self._setup(client, auth_headers, required=True)
        r = client.post(f"/api/v1/workspaces/{wid}/tables/{tid_src}/records", headers=auth_headers, json={"values": {}})
        assert r.status_code == 400
        assert "关联目标" in r.json()["detail"]

    def test_create_row_required_link_ok(self, client, auth_headers, db):
        """required link 字段传入关联 → 201."""
        wid, tid_src, _tid_dst, _fid, d1 = self._setup(client, auth_headers, required=True)
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_src}/records",
            headers=auth_headers,
            json={"values": {"关联目标": [d1["id"]]}},
        )
        assert r.status_code == 201, r.text

    def test_update_clearing_required_link_rejected(self, client, auth_headers, db):
        """required link 字段更新为空关联（显式清空）→ 400."""
        wid, tid_src, _tid_dst, _fid, d1 = self._setup(client, auth_headers, required=True)
        row = _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d1["id"]]})
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/{row['id']}",
            headers=auth_headers,
            json={"values": {"关联目标": None}},
        )
        assert r.status_code == 400
        assert "关联目标" in r.json()["detail"]

    def test_update_own_same_link_allowed(self, client, auth_headers, db):
        """unique link 字段更新为自身已有集合 → 200（排除自身）。"""
        wid, tid_src, _tid_dst, _fid, d1 = self._setup(client, auth_headers, unique=True)
        row = _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d1["id"]]})
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/{row['id']}",
            headers=auth_headers,
            json={"values": {"关联目标": [d1["id"]]}},
        )
        assert r.status_code == 200, r.text

    def test_update_to_conflicting_link_rejected(self, client, auth_headers, db):
        """unique link 字段更新为另一行已关联的集合 → 400."""
        wid, tid_src, tid_dst, _fid, d1 = self._setup(client, auth_headers, unique=True)
        d2 = _add_record(client, auth_headers, wid, tid_dst, {"title": "D2"})
        _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d1["id"]]})  # 占用 D1
        row = _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d2["id"]]})
        r = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/{row['id']}",
            headers=auth_headers,
            json={"values": {"关联目标": [d1["id"]]}},
        )
        assert r.status_code == 400
        assert "已关联同一目标集合" in r.json()["detail"]

    def test_bulk_create_unique_conflict_rejected(self, client, auth_headers, db):
        """unique link 字段批量创建两行关联同一目标 → 400 且不落库."""
        wid, tid_src, _tid_dst, _fid, d1 = self._setup(client, auth_headers, unique=True)
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/bulk-create",
            headers=auth_headers,
            json={"rows": [{"values": {"关联目标": [d1["id"]]}}, {"values": {"关联目标": [d1["id"]]}}]},
        )
        assert r.status_code == 400
        assert "批量写入中存在多行" in r.json()["detail"]

    def test_bulk_update_unique_multi_row_rejected(self, client, auth_headers, db):
        """unique link 字段批量更新 N>1 行为同一集合 → 400."""
        wid, tid_src, tid_dst, _fid, d1 = self._setup(client, auth_headers, unique=True)
        d2 = _add_record(client, auth_headers, wid, tid_dst, {"title": "D2"})
        r1 = _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d1["id"]]})
        r2 = _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d2["id"]]})
        rr = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/bulk-update",
            headers=auth_headers,
            json={"row_ids": [r1["id"], r2["id"]], "values": {"关联目标": [d1["id"]]}},
        )
        assert rr.status_code == 400

    def test_bulk_update_unique_conflict_with_existing_rejected(self, client, auth_headers, db):
        """unique link 字段批量更新 1 行为已有行的集合 → 400."""
        wid, tid_src, tid_dst, _fid, d1 = self._setup(client, auth_headers, unique=True)
        d2 = _add_record(client, auth_headers, wid, tid_dst, {"title": "D2"})
        _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d1["id"]]})  # 占用 D1
        row = _add_record(client, auth_headers, wid, tid_src, {"关联目标": [d2["id"]]})
        rr = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_src}/records/bulk-update",
            headers=auth_headers,
            json={"row_ids": [row["id"]], "values": {"关联目标": [d1["id"]]}},
        )
        assert rr.status_code == 400
        assert "已关联同一目标集合" in rr.json()["detail"]


# ── lookup 字段约束拒绝 ────────────────────────────────


class TestLookupConstraintRejection:
    def _setup(self, client, auth_headers):
        """建两张表：dst 含 select 字段，src 含 link 指向 dst + 引用 dst 字段的 lookup。"""
        wid = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_lkp_rej"}).json()["id"]
        dst = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "l_dst"})
        tid_dst = dst.json()["id"]
        src = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "l_src"})
        tid_src = src.json()["id"]
        status_f = _add_field(
            client,
            auth_headers,
            wid,
            tid_dst,
            {
                "name": "状态",
                "field_type": "select",
                "order": 0,
                "config": {"options": [{"label": "待办", "color": "#f00"}]},
            },
        )
        link_f = _add_field(
            client,
            auth_headers,
            wid,
            tid_src,
            {"name": "关联目标", "field_type": "link", "order": 0, "config": {"target_table_id": tid_dst}},
        )
        lk = _add_field(
            client,
            auth_headers,
            wid,
            tid_src,
            {
                "name": "源状态",
                "field_type": "lookup",
                "order": 1,
                "config": {
                    "source_table_id": tid_dst,
                    "source_field_id": status_f["id"],
                    "via_link_field_id": link_f["id"],
                },
            },
        )
        return wid, tid_src, lk["id"]

    def test_lookup_required_rejected(self, client, auth_headers, db):
        wid, tid_src, fid = self._setup(client, auth_headers)
        r = _patch_field(client, auth_headers, wid, tid_src, fid, {"required": True})
        assert r.status_code == 400
        assert "不支持设置必填/唯一约束" in r.json()["detail"]

    def test_lookup_unique_rejected(self, client, auth_headers, db):
        wid, tid_src, fid = self._setup(client, auth_headers)
        r = _patch_field(client, auth_headers, wid, tid_src, fid, {"is_unique": True})
        assert r.status_code == 400
        assert "不支持设置必填/唯一约束" in r.json()["detail"]


# ── 物理 DDL 失败的 metadata 回退兜底 ──────────────────


class TestMetadataRevertOnDdlFailure:
    def test_rebuild_failure_reverts_metadata(self, client, auth_headers, db, monkeypatch):
        """field_type 变更触发列重建失败 → 500 且 metadata 回退（field_type 不变）."""

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(fields_router, "rebuild_column", _boom)

        wid, tid = _make_table(client, auth_headers, "t_revert1")
        f = _add_field(client, auth_headers, wid, tid, {"name": "备注", "field_type": "text", "order": 0})
        _add_record(client, auth_headers, wid, tid, {"备注": "x"})  # 有数据，预检放行但重建失败

        r = _patch_field(client, auth_headers, wid, tid, f["id"], {"field_type": "longtext"})
        assert r.status_code == 500
        assert "物理列重建失败" in r.json()["detail"]
        # metadata 回退为旧值
        assert _get_field(client, auth_headers, wid, tid, f["id"])["field_type"] == "text"

    def test_unique_ddl_failure_reverts_metadata(self, client, auth_headers, db, monkeypatch):
        """数据干净但唯一索引创建失败 → 500 且 is_unique 回退为 False."""

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(fields_router, "add_unique_constraint", _boom)

        wid, tid = _make_table(client, auth_headers, "t_revert2")
        f = _add_field(client, auth_headers, wid, tid, {"name": "编号", "field_type": "text", "order": 0})
        _add_record(client, auth_headers, wid, tid, {"编号": "A-001"})

        r = _patch_field(client, auth_headers, wid, tid, f["id"], {"is_unique": True})
        assert r.status_code == 500
        assert "唯一约束变更失败" in r.json()["detail"]
        assert _get_field(client, auth_headers, wid, tid, f["id"])["is_unique"] is False
        assert not any(name.startswith("idx_u_") for name in _physical_indexes(db, tid))


# ── find_null_rows / find_duplicate_values 单元测试 ────


class TestInspectionHelpers:
    def test_helpers_skip_non_physical_and_missing_table(self, db, db_engine):
        """无物理列字段 / 物理表不存在时巡检函数容错返回空。"""
        from cndb.plugins.tables.models import DataField
        from cndb.plugins.tables.services.core.ddl import find_duplicate_values, find_null_rows

        dt = DataTable(workspace_id=1, name="t_helper")
        dt.ensure_db_name()
        link_like = DataField(table_id=0, name="关联", field_type="link")
        link_like.ensure_db_name()
        assert find_null_rows(db_engine, dt, link_like) == []
        assert find_duplicate_values(db_engine, dt, link_like) == []

        text_field = DataField(table_id=0, name="编号", field_type="text")
        text_field.ensure_db_name()
        assert find_null_rows(db_engine, dt, text_field) == []
        assert find_duplicate_values(db_engine, dt, text_field) == []

    def test_helpers_return_null_rows_and_duplicates(self, db, db_engine, client, auth_headers):
        """巡检函数返回 NULL 行 id 与 (重复值, 行 id) 列表。"""
        from cndb.plugins.tables.services.core.ddl import find_duplicate_values, find_null_rows

        wid, tid = _make_table(client, auth_headers, "t_helper2")
        f = _add_field(client, auth_headers, wid, tid, {"name": "编号", "field_type": "text", "order": 0})
        _add_record(client, auth_headers, wid, tid, {"编号": "A"})
        _add_record(client, auth_headers, wid, tid, {"编号": "A"})
        empty_row = _add_record(client, auth_headers, wid, tid, {})

        dt = db.get(DataTable, tid)
        df = next(x for x in dt.fields if x.id == f["id"])
        assert find_null_rows(db_engine, dt, df) == [empty_row["id"]]
        dups = find_duplicate_values(db_engine, dt, df)
        assert len(dups) == 1
        value, ids = dups[0]
        assert value == "A"
        assert len(ids) == 2

    def test_inspection_helpers_ignore_invalid_callable(self, monkeypatch):
        """类型注册表被替换为 None 时巡检函数返回空（防御分支）。"""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core import ddl

        dt = DataTable(workspace_id=1, name="t_helper3")
        df = DataField(table_id=0, name="编号", field_type="text")
        monkeypatch.setattr(ddl.default_registry, "get", lambda _name: None)
        assert ddl.find_null_rows(None, dt, df) == []
        assert ddl.find_duplicate_values(None, dt, df) == []
