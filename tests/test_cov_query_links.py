"""Coverage: query.py _compile_link_condition + _is_link_field + compile_filters empty field_name + count_rows where_clauses."""

from __future__ import annotations

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table

from cndb.plugins.tables.services.core import query
from cndb.plugins.tables.models import DataField, DataTable


def _make_table_with_link(db, ws_id, target_table_id, link_name="rel"):
    tbl = DataTable(workspace_id=ws_id, name="t_query")
    tbl.ensure_db_name()
    db.add(tbl)
    db.flush()
    f1 = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
    f1.ensure_db_name()
    db.add(f1)
    db.flush()
    f2 = DataField(
        table_id=tbl.id,
        name=link_name,
        field_type="link",
        order=1,
        config={"target_table_id": target_table_id, "multiple": True},
    )
    f2.ensure_db_name()
    db.add(f2)
    db.commit()
    db.refresh(tbl)
    return tbl


class TestCompileLinkCondition:
    def test_is_null(self, db):
        tbl = _make_table_with_link(db, 1, 1, link_name="rel_n")
        f_link = tbl.fields[1]
        sa_t = Table("dummy", MetaData(), Column("id", Integer), Column("name", String))
        expr = query._compile_link_condition(sa_t, f_link, "rel_n", "is_null", None)
        assert expr is not None

    def test_has_any(self, db):
        tbl = _make_table_with_link(db, 1, 1, link_name="rel_a")
        f_link = tbl.fields[1]
        sa_t = Table("dummy", MetaData(), Column("id", Integer))
        expr = query._compile_link_condition(sa_t, f_link, "rel_a", "has_any", [1, 2])
        assert expr is not None

    def test_has_all(self, db):
        tbl = _make_table_with_link(db, 1, 1, link_name="rel_all")
        f_link = tbl.fields[1]
        sa_t = Table("dummy", MetaData(), Column("id", Integer))
        expr = query._compile_link_condition(sa_t, f_link, "rel_all", "has_all", [1, 2])
        assert expr is not None

    def test_unsupported_op_raises(self, db):
        tbl = _make_table_with_link(db, 1, 1, link_name="rel_bad")
        f_link = tbl.fields[1]
        sa_t = Table("dummy", MetaData(), Column("id", Integer))
        with pytest.raises(ValueError):
            query._compile_link_condition(sa_t, f_link, "rel_bad", "=", "x")

    def test_has_any_empty_value_raises(self, db):
        tbl = _make_table_with_link(db, 1, 1, link_name="rel_empty")
        f_link = tbl.fields[1]
        sa_t = Table("dummy", MetaData(), Column("id", Integer))
        with pytest.raises(ValueError):
            query._compile_link_condition(sa_t, f_link, "rel_empty", "has_any", [])


class TestIsLinkFieldEdgeCases:
    def test_field_not_found_returns_none(self, db):
        """Field not in table's fields list."""
        tbl = DataTable(workspace_id=1, name="t_empty_fields")
        tbl.ensure_db_name()
        db.add(tbl)
        db.commit()
        db.refresh(tbl)
        assert query._is_link_field(tbl, "nonexistent") is None

    def test_non_link_field_returns_none(self, db):
        """Text field -> not a link field."""
        tbl = DataTable(workspace_id=1, name="t_plain")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="plain", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        assert query._is_link_field(tbl, "plain") is None


class TestCompileFilters:
    def test_empty_field_name_skipped(self, db):
        tbl = DataTable(workspace_id=1, name="t_skip")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        sa_t = Table("dummy", MetaData(), Column("id", Integer), Column("name", String))
        result = query.compile_filters(tbl, sa_t, [{"op": "=", "value": "x"}])
        assert result is None

    def test_has_any_on_non_link_field_raises(self, db):
        tbl = DataTable(workspace_id=1, name="t_nl")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        sa_t = Table("dummy", MetaData(), Column("id", Integer), Column("name", String))
        with pytest.raises(ValueError):
            query.compile_filters(tbl, sa_t, [{"field_name": "name", "op": "has_any", "value": [1]}])

    def test_physical_column_missing_skipped(self, db):
        tbl = DataTable(workspace_id=1, name="t_nocol")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="nofield", field_type="text", order=0)
        f.db_column_name = "this_column_does_not_exist"
        db.add(f)
        db.commit()
        db.refresh(tbl)
        sa_t = Table("dummy", MetaData(), Column("id", Integer))
        result = query.compile_filters(tbl, sa_t, [{"field_name": "nofield", "op": "=", "value": "x"}])
        assert result is None


class TestCompileSorts:
    def test_empty_field_name_skipped(self, db):
        tbl = DataTable(workspace_id=1, name="t_sskip")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="name", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()
        db.refresh(tbl)
        sa_t = Table("dummy", MetaData(), Column("id", Integer), Column("name", String))
        result = query.compile_sorts(tbl, sa_t, [{"direction": "desc"}])
        assert result == []

    def test_field_no_physical_col_skipped(self, db):
        tbl = DataTable(workspace_id=1, name="t_nosortcol")
        tbl.ensure_db_name()
        db.add(tbl)
        db.flush()
        f = DataField(table_id=tbl.id, name="x", field_type="text", order=0)
        f.db_column_name = "missing_col_sort"
        db.add(f)
        db.commit()
        db.refresh(tbl)
        sa_t = Table("dummy", MetaData(), Column("id", Integer))
        result = query.compile_sorts(tbl, sa_t, [{"field_name": "x", "direction": "asc"}])
        assert result == []


class TestCountRows:
    def test_with_where_clauses(self):
        sa_t = Table("dummy", MetaData(), Column("id", Integer))
        where = [sa_t.c.id == 1]
        q = query.count_rows(None, sa_t, where)
        sql = str(q)
        assert "WHERE" in sql.upper()
