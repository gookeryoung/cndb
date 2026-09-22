"""Coverage: links.py + ddl.py + records.py missing lines."""

from __future__ import annotations

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl, links


def _make_table(db, ws_id, name="t_x"):
    tbl = DataTable(workspace_id=ws_id, name=name)
    tbl.ensure_db_name()
    db.add(tbl)
    db.commit()
    db.refresh(tbl)
    return tbl


class TestDDLBuildSaTable:
    def test_skip_trashed_field(self, db_engine, db):
        from sqlalchemy import MetaData

        tbl = _make_table(db, 1, "t_ddl1")
        f1 = DataField(table_id=tbl.id, name="visible", field_type="text", order=0)
        f1.ensure_db_name()
        f2 = DataField(table_id=tbl.id, name="hidden", field_type="text", order=1, trashed=True)
        f2.ensure_db_name()
        db.add_all([f1, f2])
        db.commit()
        db.refresh(tbl)
        md = MetaData()
        sa_table = ddl.build_sa_table(md, tbl, include_trashed=False)
        col_names = {c.name for c in sa_table.columns}
        assert f1.db_column_name in col_names
        assert f2.db_column_name not in col_names

    def test_skip_unknown_field_type(self, db_engine, db):
        from sqlalchemy import MetaData

        tbl = _make_table(db, 1, "t_ddl2")
        f1 = DataField(table_id=tbl.id, name="good", field_type="text", order=0)
        f1.ensure_db_name()
        f2 = DataField(table_id=tbl.id, name="bad", field_type="weird_xyz_type", order=1)
        f2.ensure_db_name()
        db.add_all([f1, f2])
        db.commit()
        db.refresh(tbl)
        md = MetaData()
        sa_table = ddl.build_sa_table(md, tbl)
        col_names = {c.name for c in sa_table.columns}
        assert f1.db_column_name in col_names
        assert f2.db_column_name not in col_names

    def test_skip_link_field_no_physical_column(self, db_engine, db):
        from sqlalchemy import MetaData

        tbl = _make_table(db, 1, "t_ddl3")
        f1 = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f1.ensure_db_name()
        f2 = DataField(
            table_id=tbl.id,
            name="rel",
            field_type="link",
            order=1,
            config={"target_table_id": 1, "multiple": True},
        )
        f2.ensure_db_name()
        db.add_all([f1, f2])
        db.commit()
        db.refresh(tbl)
        md = MetaData()
        sa_table = ddl.build_sa_table(md, tbl)
        col_names = {c.name for c in sa_table.columns}
        assert f1.db_column_name in col_names
        assert f2.db_column_name not in col_names

    def test_unknown_field_type_graceful(self, db_engine, db):
        tbl = _make_table(db, 1, "t_ddl4")
        f = DataField(table_id=tbl.id, name="weird", field_type="does_not_exist_xyz", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)
        assert ddl.table_exists(db_engine, tbl.db_table_name)

    def test_get_engine_sqlite(self):
        eng = ddl.get_engine("sqlite:///:memory:")
        assert eng is not None
        eng.dispose()


def _create_link_scenario(client, auth_headers):
    ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_links"})
    wid = ws.json()["id"]
    tb = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "targets"})
    tid_b = tb.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_b}/fields",
        headers=auth_headers,
        json={"name": "name", "field_type": "text", "order": 0},
    )
    for _n in ["t1", "t2", "t3"]:
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_b}/records", headers=auth_headers, json={"values": {"name": _n}}
        )
    ta = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "sources"})
    tid_a = ta.json()["id"]
    client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid_a}/fields",
        headers=auth_headers,
        json={"name": "name", "field_type": "text", "order": 0},
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


class TestLinksEdgeCases:
    def test_set_links_dedupes(self, db_engine, db, client, auth_headers):
        wid, _tid_b, tid_a = _create_link_scenario(client, auth_headers)
        ra = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid_a}/records",
            headers=auth_headers,
            json={"values": {"name": "src", "link_to_target": [1, 1, 2]}},
        )
        row_id = ra.json()["id"]
        fa = db.query(DataField).filter_by(table_id=tid_a, name="link_to_target").first()
        assert fa is not None
        mapping = links.load_links(db_engine, fa, [row_id])
        assert mapping[row_id] == [1, 2]

    def test_clear_row_links_empty_ids(self, db_engine):
        tbl = DataTable(name="t_cl", db_table_name="t_cl_clearlinks999")
        assert links.clear_row_links(db_engine, tbl, []) is None

    def test_link_fields_helper(self, db_engine, db, client, auth_headers):
        _wid, _tid_b, tid_a = _create_link_scenario(client, auth_headers)
        tbl = db.query(DataTable).filter_by(id=tid_a).first()
        assert tbl is not None
        lfs = links.link_fields(tbl)
        assert len(lfs) == 1
        assert lfs[0].name == "link_to_target"


# ── 第二轮增强：is_unique 物理索引 + 列重建 + reorder ──


class TestDDLUniqueConstraint:
    """add_unique_constraint / drop_unique_constraint 幂等 + 索引创建."""

    def test_add_and_drop_unique(self, db_engine, db):
        tbl = _make_table(db, 1, "t_uniq1")
        f = DataField(table_id=tbl.id, name="email", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)

        # 加唯一约束
        ddl.add_unique_constraint(db_engine, tbl, f)
        # 幂等再调一次
        ddl.add_unique_constraint(db_engine, tbl, f)

        insp = __import__("sqlalchemy", fromlist=["inspect"]).inspect(db_engine)
        idx_names = {idx["name"] for idx in insp.get_indexes(tbl.db_table_name)}
        assert any("u_" in n for n in idx_names)

        # 删除
        ddl.drop_unique_constraint(db_engine, tbl, f)
        # 幂等再调一次
        ddl.drop_unique_constraint(db_engine, tbl, f)

    def test_unique_on_link_field_skipped(self, db_engine, db):
        """link 等无物理列字段不支持唯一约束（静默跳过）."""
        tbl = _make_table(db, 1, "t_uniq2")
        f = DataField(table_id=tbl.id, name="link_x", field_type="link", order=0, config={"target_table_id": 1})
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)
        # 不应抛异常
        ddl.add_unique_constraint(db_engine, tbl, f)


class TestDDLColumnRebuild:
    """_column_needs_rebuild 检测 + rebuild_column 实际执行."""

    def test_needs_rebuild_type_change(self, db_engine, db):
        old = DataField(name="x", field_type="text", db_column_name="field_old", required=False)
        new = DataField(name="x", field_type="float", db_column_name="field_old", required=False)
        assert ddl._column_needs_rebuild(old, new) is True

    def test_needs_rebuild_required_true(self, db_engine, db):
        old = DataField(name="x", field_type="text", db_column_name="field_old", required=False)
        new = DataField(name="x", field_type="text", db_column_name="field_old", required=True)
        assert ddl._column_needs_rebuild(old, new) is True

    def test_no_rebuild_when_same(self, db_engine, db):
        old = DataField(name="x", field_type="text", db_column_name="field_old", required=True)
        new = DataField(name="x", field_type="text", db_column_name="field_old", required=True)
        assert ddl._column_needs_rebuild(old, new) is False

    def test_rebuild_column(self, db_engine, db):
        """实际执行列重建：text → float，数据丢失（不可转换）."""
        tbl = _make_table(db, 1, "t_rebuild1")
        f = DataField(table_id=tbl.id, name="score", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)

        # 先加一行文本数据
        from cndb.plugins.tables.services.core import records as rec

        rec.create_row(db_engine, tbl, {"score": "hello"}, db=db)

        # 重建为 float（需要先把 unique 去掉，因为列名没变）
        f2 = DataField(
            name="score",
            field_type="float",
            db_column_name=f.db_column_name,
            required=False,
        )
        ddl.rebuild_column(db_engine, tbl, f, f2)

        # 验证新类型：尝试写入 float 应该成功
        rec.create_row(db_engine, tbl, {"score": 99.5}, db=db)

    def test_rebuild_link_field_raises(self, db_engine, db):
        """link→text 重建：旧字段 link 无物理列，抛 ValueError."""
        tbl = _make_table(db, 1, "t_rebuild2")
        f = DataField(table_id=tbl.id, name="link_x", field_type="link", order=0, config={"target_table_id": 1})
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)

        f2 = DataField(name="link_x", field_type="text", db_column_name=f.db_column_name, required=False)
        import pytest

        with pytest.raises(ValueError, match="无物理列"):
            ddl.rebuild_column(db_engine, tbl, f, f2)

    def test_rebuild_new_link_raises(self, db_engine, db):
        """text→link 重建：新字段 link 无物理列，抛 ValueError."""
        tbl = _make_table(db, 1, "t_rebuild3")
        f = DataField(table_id=tbl.id, name="x", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)

        f2 = DataField(name="x", field_type="link", db_column_name=f.db_column_name, config={"target_table_id": 1})
        import pytest

        with pytest.raises(ValueError, match="无物理列"):
            ddl.rebuild_column(db_engine, tbl, f, f2)

    def test_add_column_with_default(self, db_engine, db):
        """add_column 时带 default_value."""
        tbl = _make_table(db, 1, "t_def1")
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)

        f = DataField(table_id=tbl.id, name="score", field_type="number", order=0, default_value=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        ddl.add_column(db_engine, tbl, f)
        # 不抛异常就行

    def test_drop_unique_on_link_field_skip(self, db_engine, db):
        """link 字段 drop_unique_constraint 静默跳过."""
        tbl = _make_table(db, 1, "t_uniq_skip")
        f = DataField(table_id=tbl.id, name="link_x", field_type="link", order=0, config={"target_table_id": 1})
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        ddl.create_table(db_engine, tbl)
        # 不应抛异常
        ddl.drop_unique_constraint(db_engine, tbl, f)


class TestUniqueIndexName:
    """_unique_index_name 截断."""

    def test_normal(self):
        name = ddl._unique_index_name("table_abc123", "field_xyz789")
        assert name.startswith("idx_u_")
        assert len(name) <= 64

    def test_long_truncation(self):
        long_tbl = "table_" + "x" * 50
        long_col = "field_" + "y" * 50
        name = ddl._unique_index_name(long_tbl, long_col)
        assert len(name) <= 60


class TestFieldsReorderAPI:
    """POST /reorder 字段排序."""

    def test_reorder_via_api(self, client, auth_headers, db):
        # 先建 workspace + 表
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_reorder"})
        wid = ws.json()["id"]
        r = client.post(f"/api/v1/workspaces/{wid}/tables", json={"name": "t_reorder_test"}, headers=auth_headers)
        assert r.status_code == 201
        tid = r.json()["id"]

        # 建三个字段
        for i, fname in enumerate(["a", "b", "c"]):
            client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
                json={"name": fname, "field_type": "text", "order": i},
                headers=auth_headers,
            )

        # 调整顺序: c, a, b
        r2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/reorder",
            json={"field_ids": [3, 1, 2]},
            headers=auth_headers,
        )
        assert r2.status_code == 200
        reordered = r2.json()
        names = [f["name"] for f in reordered]
        assert names == ["c", "a", "b"]


class TestUpdateFieldTypeChange:
    """update_field 触发物理列重建."""

    def test_update_field_type_via_api(self, client, auth_headers):
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_upd1"})
        wid = ws.json()["id"]
        # 建表
        r = client.post(f"/api/v1/workspaces/{wid}/tables", json={"name": "t_updtype"}, headers=auth_headers)
        assert r.status_code == 201
        tid = r.json()["id"]

        # 建 text 字段
        r2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            json={"name": "val", "field_type": "text", "config": {}},
            headers=auth_headers,
        )
        assert r2.status_code == 201
        fid = r2.json()["id"]

        # 改 field_type: text → float
        r3 = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
            json={"field_type": "float"},
            headers=auth_headers,
        )
        assert r3.status_code == 200
        assert r3.json()["field_type"] == "float"

    def test_update_field_unique_toggle(self, client, auth_headers, db):
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_upd2"})
        wid = ws.json()["id"]
        r = client.post(f"/api/v1/workspaces/{wid}/tables", json={"name": "t_upduniq"}, headers=auth_headers)
        assert r.status_code == 201
        tid = r.json()["id"]

        # 建 number 字段
        r2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            json={"name": "num", "field_type": "number", "config": {}, "is_unique": False},
            headers=auth_headers,
        )
        assert r2.status_code == 201
        fid = r2.json()["id"]

        # 切 unique=True
        r3 = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
            json={"is_unique": True},
            headers=auth_headers,
        )
        assert r3.status_code == 200
        assert r3.json()["is_unique"] is True

        # 再切 unique=False
        r4 = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
            json={"is_unique": False},
            headers=auth_headers,
        )
        assert r4.status_code == 200
        assert r4.json()["is_unique"] is False

    def test_update_field_type_alias_normalizes(self, client, auth_headers):
        """前端发 decimal 别名 → 后端自动归一化为 float."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_upd3"})
        wid = ws.json()["id"]
        r = client.post(f"/api/v1/workspaces/{wid}/tables", json={"name": "t_alias"}, headers=auth_headers)
        assert r.status_code == 201
        tid = r.json()["id"]

        r2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            json={"name": "num", "field_type": "number", "config": {}},
            headers=auth_headers,
        )
        fid = r2.json()["id"]

        r3 = client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
            json={"field_type": "decimal"},  # 别名
            headers=auth_headers,
        )
        assert r3.status_code == 200
        assert r3.json()["field_type"] == "float"

    def test_create_field_with_is_unique_calls_ddl(self, client, auth_headers, db):
        """create_field 时 is_unique=True → 触发 add_unique_constraint."""
        from unittest.mock import patch

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_uniq_create"})
        wid = ws.json()["id"]
        r = client.post(f"/api/v1/workspaces/{wid}/tables", json={"name": "t_uniq_create"}, headers=auth_headers)
        assert r.status_code == 201
        tid = r.json()["id"]

        with patch("cndb.plugins.tables.routers.fields.add_unique_constraint") as mock_add:
            resp = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
                json={"name": "email", "field_type": "text", "config": {}, "is_unique": True},
                headers=auth_headers,
            )
        assert resp.status_code == 201
        mock_add.assert_called_once()

    def test_update_field_rebuild_exception(self, client, auth_headers, db):
        """update_field 时 rebuild_column 抛异常 → 返回 500."""
        from unittest.mock import patch

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_err1"})
        wid = ws.json()["id"]
        r = client.post(f"/api/v1/workspaces/{wid}/tables", json={"name": "t_err1"}, headers=auth_headers)
        tid = r.json()["id"]

        # 先建 text 字段
        r2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            json={"name": "val", "field_type": "text", "config": {}},
            headers=auth_headers,
        )
        fid = r2.json()["id"]

        with patch("cndb.plugins.tables.routers.fields.rebuild_column", side_effect=RuntimeError("boom")):
            resp = client.patch(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
                json={"field_type": "float"},
                headers=auth_headers,
            )
        assert resp.status_code == 500

    def test_update_field_unique_exception(self, client, auth_headers, db):
        """update_field 时 add_unique_constraint 抛异常 → 返回 500."""
        from unittest.mock import patch

        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_err2"})
        wid = ws.json()["id"]
        r = client.post(f"/api/v1/workspaces/{wid}/tables", json={"name": "t_err2"}, headers=auth_headers)
        tid = r.json()["id"]

        r2 = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            json={"name": "num", "field_type": "number", "config": {}, "is_unique": False},
            headers=auth_headers,
        )
        fid = r2.json()["id"]

        with patch("cndb.plugins.tables.routers.fields.add_unique_constraint", side_effect=RuntimeError("boom")):
            resp = client.patch(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
                json={"is_unique": True},
                headers=auth_headers,
            )
        assert resp.status_code == 500

        # drop 也测一下
        client.patch(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
            json={"is_unique": True},
            headers=auth_headers,
        )
        with patch("cndb.plugins.tables.routers.fields.drop_unique_constraint", side_effect=RuntimeError("boom")):
            resp = client.patch(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
                json={"is_unique": False},
                headers=auth_headers,
            )
        assert resp.status_code == 500
