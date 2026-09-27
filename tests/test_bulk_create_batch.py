"""bulk_create 批量插入路径回归.

覆盖 records.bulk_create 的双通道写入：
- 无 link 值的连续段走 RETURNING 批量插入（SQLite insertmanyvalues，id 与输入顺序一一对应）；
- 有 link 值的行走逐行插入 + set_links（需要 lastrowid 立即写关联表）；
- 两类行在单次调用中穿插时返回 ids 仍与输入行严格同序。
"""

import pytest

from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl, links
from cndb.plugins.tables.services.core import records as rec


@pytest.fixture
def ws(db):
    from cndb.plugins.workspaces.models import Workspace

    w = Workspace(name="ws_bulk_batch")
    db.add(w)
    db.commit()
    db.refresh(w)
    return w


def _build_table(db, db_engine, ws, name, field_specs):
    """建表元数据 + 物理表（link 字段同时建关联物理表），返回 DataTable."""
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for i, (fname, ftype, cfg) in enumerate(field_specs):
        f = DataField(table_id=dt.id, name=fname, field_type=ftype, order=i, config=cfg)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db_engine, dt)
    for f in dt.fields:
        if f.field_type == "link":
            ddl.create_link_table(db_engine, f)
    return dt


def _name_by_id(db_engine, dt, row_ids):
    """按物理行 id 读回「名称」列值，用于断言 ids 与输入行同序."""
    ids_list = list(row_ids)
    placeholders = ",".join("?" for _ in ids_list)
    col = next(f.db_column_name for f in dt.fields if f.name == "名称")
    sql = f'SELECT id, "{col}" FROM {dt.db_table_name} WHERE id IN ({placeholders})'
    with db_engine.connect() as conn:
        rows = conn.exec_driver_sql(sql, tuple(ids_list)).all()
    return dict(rows)


class TestBulkCreateBatchPath:
    def test_pure_batch_ids_match_input_order(self, db, db_engine, ws):
        """全无 link 行（含空 values 行）走批量段：ids 唯一且与输入行内容一一对应."""
        dt = _build_table(db, db_engine, ws, "批量纯文本", [("名称", "text", None)])
        rows = [{"名称": "第一行"}, {}, {"名称": "第三行"}]
        ids = rec.bulk_create(db_engine, dt, rows)

        assert len(ids) == 3
        assert len(set(ids)) == 3
        assert all(i is not None for i in ids)
        names = _name_by_id(db_engine, dt, ids)
        assert names[ids[0]] == "第一行"
        assert names[ids[2]] == "第三行"

    def test_mixed_link_and_batch_segments_same_order(self, db, db_engine, ws):
        """批量-逐行-批量穿插：ids 与输入行严格同序，link 关联只落在目标行."""
        target = _build_table(db, db_engine, ws, "批量目标表", [("名称", "text", None)])
        target_ids = rec.bulk_create(db_engine, target, [{"名称": "t1"}, {"名称": "t2"}])

        dt = _build_table(
            db,
            db_engine,
            ws,
            "批量混合表",
            [("名称", "text", None), ("关联", "link", {"target_table_id": target.id})],
        )
        link_field = next(f for f in dt.fields if f.field_type == "link")
        rows = [
            {"名称": "批量段-前"},  # 批量段
            {"名称": "关联行", "关联": [target_ids[1]]},  # 逐行段
            {"名称": "批量段-后"},  # 批量段
        ]
        ids = rec.bulk_create(db_engine, dt, rows)

        assert len(ids) == 3 and all(i is not None for i in ids)
        names = _name_by_id(db_engine, dt, ids)
        assert names[ids[0]] == "批量段-前"
        assert names[ids[1]] == "关联行"
        assert names[ids[2]] == "批量段-后"
        # link 只写在中间行：load_links 按 row_id 精确对应
        mapping = links.load_links(db_engine, link_field, ids)
        assert mapping == {ids[1]: [target_ids[1]]}

    def test_link_only_row_uses_row_path(self, db, db_engine, ws):
        """空物理值 + link 值的行走逐行通道：_trashed 兜底列 + 关联正确落库."""
        target = _build_table(db, db_engine, ws, "批量目标表2", [("名称", "text", None)])
        target_ids = rec.bulk_create(db_engine, target, [{"名称": "t1"}])

        dt = _build_table(
            db,
            db_engine,
            ws,
            "批量仅关联表",
            [("关联", "link", {"target_table_id": target.id})],
        )
        link_field = next(f for f in dt.fields if f.field_type == "link")
        ids = rec.bulk_create(db_engine, dt, [{"关联": [target_ids[0]]}])

        assert len(ids) == 1 and ids[0] is not None
        assert links.load_links(db_engine, link_field, ids) == {ids[0]: [target_ids[0]]}
