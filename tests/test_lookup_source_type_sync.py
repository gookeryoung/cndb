"""lookups.sync_dependent_lookups_on_source_type_change 单元测试.

覆盖矩阵：
┌──────────────────────────────────────────┬─────────────────────────────┐
│ 场景                                      │ 关键断言                     │
├──────────────────────────────────────────┼─────────────────────────────┤
│ 源字段 text→select（跨表多个引用）         │ 全部刷新类型且 broken=False  │
│ 已 broken 的引用遇可读类型                 │ 自愈为 broken=False          │
│ 源字段→link/lookup（无物理列）             │ broken=True                  │
│ 未知类型（registry 无注册）                │ 视为不可读 → broken=True     │
│ 引用其它字段 / 已回收的 lookup             │ 原样不动                     │
│ 无实际变化                                 │ 返回 0 且不重复 commit       │
└──────────────────────────────────────────┴─────────────────────────────┘
"""

from __future__ import annotations

from cndb.plugins.tables.models import DataField, DataTable, generate_db_column_name
from cndb.plugins.tables.services.core.lookups import (
    mark_dependent_lookups_broken,
    sync_dependent_lookups_on_source_type_change,
)

# ── 辅助 ──────────────────────────────────────────────


def _table(db, name: str) -> DataTable:
    tbl = DataTable(workspace_id=1, name=name)
    tbl.ensure_db_name()
    db.add(tbl)
    db.flush()
    return tbl


def _field(db, table: DataTable, name: str, field_type: str, config: dict | None = None) -> DataField:
    f = DataField(
        table_id=table.id,
        name=name,
        field_type=field_type,
        db_column_name=generate_db_column_name(),
        config=config or {},
        order=0,
    )
    db.add(f)
    db.flush()
    return f


def _make_env(db) -> tuple[DataField, DataField, DataField, list[DataField]]:
    """建源表字段 + 两个引用它的 lookup（分属两张表），返回上下文."""
    src_table = _table(db, "t_sync_src")
    src_field = _field(db, src_table, "status", "text")

    dst_a = _table(db, "t_sync_dst_a")
    link_a = _field(db, dst_a, "关联", "link", {"target_table_id": src_table.id})
    lookup_a = _field(
        db,
        dst_a,
        "status",
        "lookup",
        {
            "source_table_id": src_table.id,
            "source_field_id": src_field.id,
            "via_link_field_id": link_a.id,
            "source_field_type": "text",
        },
    )

    dst_b = _table(db, "t_sync_dst_b")
    link_b = _field(db, dst_b, "关联", "link", {"target_table_id": src_table.id})
    lookup_b = _field(
        db,
        dst_b,
        "status",
        "lookup",
        {
            "source_table_id": src_table.id,
            "source_field_id": src_field.id,
            "via_link_field_id": link_b.id,
            "source_field_type": "text",
        },
    )
    db.commit()
    return src_field, lookup_a, lookup_b, [lookup_a, lookup_b]


# ── 可读类型：类型跟随 + 自愈 ──────────────────────────


class TestSyncReadableType:
    def test_sync_updates_all_cross_table_lookups(self, db):
        """源字段 text→select：跨表全部引用字段同步类型且不清空可读标记."""
        src_field, lookup_a, lookup_b, _ = _make_env(db)
        src_field.field_type = "select"
        db.commit()

        assert sync_dependent_lookups_on_source_type_change(db, src_field) == 2

        for lookup in (lookup_a, lookup_b):
            db.refresh(lookup)
            assert lookup.config["source_field_type"] == "select"
            assert lookup.config["broken"] is False

    def test_readable_type_clears_previous_broken(self, db):
        """引用字段此前被标记失效，源字段回到可读类型后应自愈."""
        src_field, lookup_a, _lookup_b, _ = _make_env(db)
        assert mark_dependent_lookups_broken(db, src_field.id) == 2

        src_field.field_type = "number"
        db.commit()
        assert sync_dependent_lookups_on_source_type_change(db, src_field) == 2

        db.refresh(lookup_a)
        assert lookup_a.config["source_field_type"] == "number"
        assert lookup_a.config["broken"] is False

    def test_second_sync_is_noop(self, db):
        """无实际变化时返回 0，不产生多余写入."""
        src_field, _a, _b, _ = _make_env(db)
        src_field.field_type = "select"
        db.commit()
        assert sync_dependent_lookups_on_source_type_change(db, src_field) == 2
        assert sync_dependent_lookups_on_source_type_change(db, src_field) == 0


# ── 不可读类型：标记失效 ───────────────────────────────


class TestSyncUnreadableType:
    def test_link_type_marks_broken(self, db):
        """源字段改为 link（无物理列）：引用字段标记失效并保留类型快照."""
        src_field, lookup_a, _b, _ = _make_env(db)
        src_field.field_type = "link"
        db.commit()

        assert sync_dependent_lookups_on_source_type_change(db, src_field) == 2
        db.refresh(lookup_a)
        assert lookup_a.config["source_field_type"] == "link"
        assert lookup_a.config["broken"] is True

    def test_lookup_type_marks_broken(self, db):
        """源字段改为 lookup：引用字段同样标记失效（禁止递归取值）."""
        src_field, lookup_a, _b, _ = _make_env(db)
        src_field.field_type = "lookup"
        db.commit()

        assert sync_dependent_lookups_on_source_type_change(db, src_field) == 2
        db.refresh(lookup_a)
        assert lookup_a.config["broken"] is True

    def test_unknown_type_treated_unreadable(self, db):
        """registry 未注册的类型无法确认物理列 → 保守标记失效."""
        src_field, lookup_a, _b, _ = _make_env(db)
        src_field.field_type = "mystery"
        db.commit()

        assert sync_dependent_lookups_on_source_type_change(db, src_field) == 2
        db.refresh(lookup_a)
        assert lookup_a.config["source_field_type"] == "mystery"
        assert lookup_a.config["broken"] is True


# ── 隔离性：只动匹配的未回收引用 ───────────────────────


class TestSyncIsolation:
    def test_other_source_and_trashed_lookup_untouched(self, db):
        """引用其它源字段的 lookup、以及已回收的 lookup 都不受影响."""
        src_field, lookup_a, lookup_b, _ = _make_env(db)

        other_src = _field(db, src_field.table, "other", "text")
        other_lookup = _field(
            db,
            lookup_a.table,
            "other_ref",
            "lookup",
            {
                "source_table_id": src_field.table_id,
                "source_field_id": other_src.id,
                "via_link_field_id": 0,
                "source_field_type": "text",
            },
        )
        trashed = _field(
            db,
            lookup_a.table,
            "trashed_ref",
            "lookup",
            {
                "source_table_id": src_field.table_id,
                "source_field_id": src_field.id,
                "via_link_field_id": 0,
                "source_field_type": "text",
            },
        )
        trashed.trashed = True
        db.commit()

        src_field.field_type = "select"
        db.commit()
        assert sync_dependent_lookups_on_source_type_change(db, src_field) == 2

        db.refresh(lookup_a)
        db.refresh(lookup_b)
        assert lookup_a.config["source_field_type"] == "select"
        assert lookup_b.config["source_field_type"] == "select"
        db.refresh(other_lookup)
        assert other_lookup.config["source_field_type"] == "text"
        assert other_lookup.config.get("broken", False) is False
        db.refresh(trashed)
        assert trashed.config["source_field_type"] == "text"
        assert trashed.config.get("broken", False) is False
