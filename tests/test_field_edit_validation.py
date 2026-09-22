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
