"""Coverage push: TABLES core/fields services — lookups / links / records / field_import.

聚焦此前未被覆盖的内部辅助分支与边界路径，纯函数单元测试 + 最小 DDL/ORM 场景。
不修改任何源码；所有断言针对现有行为。
"""

from __future__ import annotations

import types

import pytest
from sqlalchemy import Column, Integer, MetaData, text
from sqlalchemy import Table as SATable

from cndb.plugins.tables.models import DataField, DataTable, TablePermission, generate_db_column_name
from cndb.plugins.tables.services.core import ddl, links, lookups, records
from cndb.plugins.tables.services.core.lookups import (
    _contains_lookup,
    _group_items,
    _match_link_value,
    _match_physical_value,
    match_row_filters,
    sort_rows_in_memory,
)
from cndb.plugins.tables.services.fields import field_import as fi

# ── 通用辅助 ─────────────────────────────────────────


def _mk_table(db, name: str) -> DataTable:
    t = DataTable(workspace_id=1, name=name)
    t.ensure_db_name()
    db.add(t)
    db.flush()
    return t


def _mk_field(
    db, table: DataTable, name: str, ftype: str, *, config: dict | None = None, order: int = 0, **kw
) -> DataField:
    f = DataField(
        table_id=table.id,
        name=name,
        field_type=ftype,
        db_column_name=generate_db_column_name(),
        config=config or {},
        order=order,
        **kw,
    )
    db.add(f)
    db.flush()
    return f


def _mem_table(fields: list[DataField]) -> DataTable:
    t = DataTable(workspace_id=1, name="mem")
    t.ensure_db_name()
    t.fields = fields
    return t


# ══════════════════════════════════════════════════════
# lookups.py — 纯函数
# ══════════════════════════════════════════════════════


class TestGroupItems:
    def test_dict_with_or_group_key(self):
        """dict 形式的 __or__ / __and__ 键归一为分组项（line 194)."""
        assert _group_items({"__or__": [{"a": 1}]}) == [{"__or__": [{"a": 1}]}]
        assert _group_items({"__and__": [{"a": 1}]}) == [{"__and__": [{"a": 1}]}]

    def test_dict_value_with_op_and_value(self):
        """dict 值本身是 {op, value} 简写时展开为条件项（line 196)."""
        assert _group_items({"num": {"op": ">", "value": 3}}) == [{"field_name": "num", "op": ">", "value": 3}]

    def test_dict_plain_scalar_value(self):
        """dict 值为标量时按等值条件归一（line 198)."""
        assert _group_items({"num": 5}) == [{"field_name": "num", "op": "=", "value": 5}]

    def test_non_list_non_dict_returns_empty(self):
        """非 list / dict 输入返回空列表（line 200)."""
        assert _group_items("garbage") == []
        assert _group_items(123) == []

    def test_list_filters_non_dict_items(self):
        """list 形式只保留 dict 项."""
        assert _group_items([{"a": 1}, "x", 2]) == [{"a": 1}]


class TestContainsLookupNestedBreak:
    def test_nested_group_without_lookup_hits_break(self):
        """嵌套分组内无 lookup 时递归返回 False → 触发内部 break（line 210)."""
        assert _contains_lookup({"lk"}, {"__or__": [{"field_name": "num", "op": "=", "value": 1}]}) is False

    def test_nested_group_with_lookup_returns_true(self):
        assert _contains_lookup({"lk"}, {"__or__": [{"field_name": "lk", "op": "=", "value": 1}]}) is True


class TestMatchLookupValueLe:
    def test_le_operator(self):
        """<= 对聚合列表逐项比较（line 289)."""
        assert lookups.match_lookup_value([1, 3], "<=", 2) is True
        assert lookups.match_lookup_value([5, 7], "<=", 2) is False


class TestMatchPhysicalValueOps:
    @pytest.mark.parametrize(
        ("value", "op", "expected", "result"),
        [
            (None, "is_empty", None, True),
            ("", "is_empty", None, True),
            ("x", "is_empty", None, False),
            ("", "is_not_empty", None, False),
            ("x", "is_not_empty", None, True),
            (None, "is_null", None, True),
            ("x", "is_null", None, False),
            (None, "is_not_null", None, False),
            ("x", "is_not_null", None, True),
        ],
        ids=[
            "empty_none",
            "empty_str",
            "empty_non",
            "not_empty",
            "not_empty2",
            "null",
            "null2",
            "not_null",
            "not_null2",
        ],
    )
    def test_emptiness_predicates(self, value, op, expected, result):
        """is_empty/is_not_empty/is_null/is_not_null 分支（lines 301-307)."""
        assert _match_physical_value(value, op, expected) is result

    def test_null_value_with_other_op(self):
        """值为 None 且非空判定操作符 → 不匹配（line 309)."""
        assert _match_physical_value(None, "=", 1) is False

    @pytest.mark.parametrize(
        ("op", "expected", "result"),
        [
            ("!=", "xyz", True),
            ("in", ["abcd"], True),
            ("not_in", ["z"], True),
            ("contains", "ab", True),
            ("starts_with", "ab", True),
            ("ends_with", "cd", True),
            ("contains_any", ["x", "b"], True),
            ("contains_all", ["b", "c"], True),
        ],
        ids=["neq", "in", "not_in", "contains", "starts_with", "ends_with", "contains_any", "contains_all"],
    )
    def test_scalar_ops(self, op, expected, result):
        """标量操作符分支（lines 313-327)."""
        assert _match_physical_value("abcd", op, expected) is result

    def test_type_error_fallback_to_str(self):
        """类型不可直接比较时回退字符串比较（lines 337-340)."""
        assert _match_physical_value("b", ">", "a") is True
        assert _match_physical_value({"a": 1}, ">", 5) is True  # dict > int raises then str fallback

    def test_between_invalid_expected(self):
        """between/date_range 期望值形状非法 → 不匹配（line 345)."""
        assert _match_physical_value(5, "between", [1]) is False
        assert _match_physical_value(5, "between", 3) is False

    def test_between_valid(self):
        assert _match_physical_value(5, "date_range", [1, 10]) is True

    def test_unknown_op(self):
        """未知操作符按不匹配处理并告警（lines 348-349)."""
        assert _match_physical_value(1, "bogus_op", 1) is False


class TestMatchLinkValue:
    def test_non_list_value_treated_empty(self):
        """非列表 link 值 → ids 为空（lines 355-358)."""
        assert _match_link_value(None, "is_null", None) is True
        assert _match_link_value("x", "is_not_null", None) is False

    def test_null_and_empty_ops(self):
        assert _match_link_value([], "is_null", None) is True
        assert _match_link_value([{"id": 1}], "is_not_empty", None) is True

    def test_has_any(self):
        assert _match_link_value([{"id": 1}, {"id": 2}], "has_any", [2, 9]) is True
        assert _match_link_value([{"id": 1}], "has_any", [9]) is False

    def test_has_any_bad_type_returns_false(self):
        """expected 含不可转 int 值 → 捕获异常返回 False（lines 368-369)."""
        assert _match_link_value([{"id": 1}], "has_any", ["x"]) is False

    def test_has_all(self):
        assert _match_link_value([{"id": 1}, {"id": 2}], "has_all", [1, 2]) is True
        assert _match_link_value([{"id": 1}], "has_all", [1, 2]) is False

    def test_has_all_bad_type_returns_false(self):
        """has_all expected 含不可转 int 值 → 返回 False（lines 374-375)."""
        assert _match_link_value([{"id": 1}], "has_all", ["x"]) is False

    def test_unknown_op(self):
        """未知 link 操作符按不匹配处理（lines 376-377)."""
        assert _match_link_value([{"id": 1}], "bogus", None) is False


class TestMatchRowFiltersLinkBranch:
    @pytest.fixture
    def link_table(self):
        return _mem_table(
            [
                DataField(name="lk", field_type="lookup", order=0, db_column_name="field_a"),
                DataField(name="lnk", field_type="link", order=1, db_column_name="field_b"),
            ]
        )

    def test_link_leaf_routed_to_link_matcher(self, link_table):
        """link 字段条件走 _match_link_value（line 414)."""
        row = {"id": 1, "lnk": [{"id": 1}, {"id": 2}], "lk": None}
        assert match_row_filters(link_table, row, [{"field_name": "lnk", "op": "has_any", "value": [2]}])
        assert not match_row_filters(link_table, row, [{"field_name": "lnk", "op": "has_any", "value": [9]}])
        assert match_row_filters(link_table, row, [{"field_name": "lnk", "op": "is_not_null"}])

    def test_nested_and_group_over_link(self, link_table):
        row = {"id": 1, "lnk": [{"id": 1}], "lk": None}
        assert match_row_filters(
            link_table,
            row,
            [{"__and__": [{"field_name": "lnk", "op": "has_any", "value": [1]}]}],
        )


class TestSortRowsBothNone:
    def test_both_none_branch(self):
        """两行排序键都为 None → continue（line 462)."""
        rows = [{"id": 1, "n": None}, {"id": 2, "n": None}]
        assert sort_rows_in_memory(rows, [{"field_name": "n", "direction": "asc"}]) == rows


# ══════════════════════════════════════════════════════
# lookups.py — DB 场景
# ══════════════════════════════════════════════════════


def _lookup_scenario(db, engine, *, multiple: bool = True):
    """建 src(某文本字段) + dst(link + lookup) 并关联一行，返回 (dst, lookup_field, src_rows)."""
    src = _mk_table(db, "lk_src")
    sf = _mk_field(db, src, "sval", "text")
    ddl.create_table(engine, src)
    srows = [records.create_row(engine, src, {"sval": v}, db) for v in ("A", "B")]

    dst = _mk_table(db, "lk_dst")
    _mk_field(db, dst, "own", "text", order=0)
    lf = _mk_field(
        db,
        dst,
        "lnk",
        "link",
        order=1,
        config={"target_table_id": src.id, "multiple": multiple},
    )
    look = _mk_field(
        db,
        dst,
        "lref",
        "lookup",
        order=2,
        config={
            "source_table_id": src.id,
            "source_field_id": sf.id,
            "via_link_field_id": lf.id,
            "source_field_type": "text",
        },
    )
    ddl.create_table(engine, dst)
    records.create_row(engine, dst, {"own": "r1", "lnk": [srows[0]["id"], srows[1]["id"]]}, db)
    db.commit()
    return dst, look, lf, sf, srows


class TestResolveLookupValuesBranches:
    def test_missing_link_field_returns_155(self, db, db_engine):
        """via_link_field_id 指向不存在的 link → 返回 None（line 155)."""
        src = _mk_table(db, "lk_src2")
        sf = _mk_field(db, src, "sval", "text")
        dst = _mk_table(db, "lk_dst2")
        look = _mk_field(
            db,
            dst,
            "lref",
            "lookup",
            config={
                "source_table_id": src.id,
                "source_field_id": sf.id,
                "via_link_field_id": 999999,
                "source_field_type": "text",
            },
        )
        db.commit()
        values = lookups._resolve_lookup_values(db_engine, db, dst, look.config, [1])
        assert values == {}

    def test_source_values_none_returns_165(self, db, db_engine):
        """源物理表缺失 → _read_source_values 返回 None → 提前返回（lines 165, 515)."""
        # src 元数据存在但物理表未创建
        src = _mk_table(db, "lk_src3")
        sf = _mk_field(db, src, "sval", "text")
        dst = _mk_table(db, "lk_dst3")
        lf = _mk_field(db, dst, "lnk", "link", config={"target_table_id": src.id, "multiple": True})
        look = _mk_field(
            db,
            dst,
            "lref",
            "lookup",
            config={
                "source_table_id": src.id,
                "source_field_id": sf.id,
                "via_link_field_id": lf.id,
                "source_field_type": "text",
            },
        )
        ddl.create_table(db_engine, dst)  # 只建 dst（含 link 表），src 物理表缺失
        records.create_row(db_engine, dst, {"lnk": []}, db)
        db.commit()
        assert lookups._resolve_lookup_values(db_engine, db, dst, look.config, [1]) == {}

    def test_single_multiple_false(self, db, db_engine):
        """multiple=False 时输出首个关联值（line 174)."""
        dst, _look, _lf, _sf, _srows = _lookup_scenario(db, db_engine, multiple=False)
        rows, _ = records.list_rows(db_engine, dst, db=db)
        assert rows[0]["lref"] == "A"


class TestFindHelpers:
    def test_find_link_field_non_int(self):
        """via_link_field_id 非 int → None（line 482)."""
        tbl = _mem_table([DataField(name="lnk", field_type="link", order=0, db_column_name="field_c")])
        assert lookups._find_link_field(tbl, None) is None
        assert lookups._find_link_field(tbl, "x") is None

    def test_find_source_field_non_int(self, db):
        """source_field_id 非 int → None（line 493)."""
        assert lookups._find_source_field(db, {"source_field_id": "x"}) is None
        assert lookups._find_source_field(db, {}) is None

    def test_find_source_field_trashed(self, db):
        """源字段已回收 → None（line 496)."""
        tbl = _mk_table(db, "t_find_src")
        f = _mk_field(db, tbl, "s", "text")
        f.trashed = True
        db.commit()
        assert lookups._find_source_field(db, {"source_field_id": f.id}) is None


class TestReadSourceValuesEarlyReturns:
    def test_source_table_none(self, db_engine):
        """source_field.table 为 None → None（line 512)."""
        f = DataField(name="x", field_type="text", db_column_name="field_z", order=0)
        assert lookups._read_source_values(db_engine, f, [1]) is None

    def test_column_missing(self, db, db_engine):
        """物理表存在但字段列缺失 → None（line 518)."""
        tbl = _mk_table(db, "t_rcol")
        a = _mk_field(db, tbl, "a", "text")
        ddl.create_table(db_engine, tbl)
        b = _mk_field(db, tbl, "b", "text")  # 未执行 DDL，物理列不存在
        db.commit()
        bf = db.get(DataField, b.id)
        assert lookups._read_source_values(db_engine, bf, [1]) is None
        # a 正常可读
        assert lookups._read_source_values(db_engine, db.get(DataField, a.id), [1]) == {}

    def test_reflected_table_missing_column(self, db, db_engine, monkeypatch):
        """反射缓存表缺列 → col None → None（line 523)."""
        tbl = _mk_table(db, "t_rcol2")
        f = _mk_field(db, tbl, "a", "text")
        ddl.create_table(db_engine, tbl)
        db.commit()
        ff = db.get(DataField, f.id)
        fake = SATable("fake_tbl", MetaData(), Column("id", Integer, primary_key=True))
        monkeypatch.setattr(ddl, "get_reflected_table", lambda *a, **k: fake)
        assert lookups._read_source_values(db_engine, ff, [1]) is None


class TestMarkDependentBrokenAlreadyBroken:
    def test_already_broken_skipped(self, db):
        """已 broken 的引用字段跳过（line 61)."""
        src = _mk_table(db, "t_mark_src")
        sf = _mk_field(db, src, "s", "text")
        dst = _mk_table(db, "t_mark_dst")
        _mk_field(
            db,
            dst,
            "ref",
            "lookup",
            config={"source_field_id": sf.id, "broken": True},
        )
        db.commit()
        assert lookups.mark_dependent_lookups_broken(db, sf.id) == 0


# ══════════════════════════════════════════════════════
# links.py
# ══════════════════════════════════════════════════════


def _make_link_field(db, engine, dst: DataTable, name: str, target: DataTable, *, create: bool = True) -> DataField:
    f = _mk_field(db, dst, name, "link", config={"target_table_id": target.id, "multiple": True})
    if create:
        ddl.create_link_table(engine, f)
    return f


def _insert_link(engine, field: DataField, row_id: int, target_row_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(f'INSERT INTO "{field.link_table_name}" (row_id, target_row_id) VALUES (:r, :t)'),
            {"r": row_id, "t": target_row_id},
        )


class TestFindBackReferencesBranches:
    def test_all_skip_branches(self, db, db_engine):
        """覆盖 195/206/209：link 表缺失 / 无引用行 / 源表缺失 均跳过."""
        target = _mk_table(db, "br_target")
        _mk_field(db, target, "n", "text")
        ddl.create_table(db_engine, target)
        trow = records.create_row(db_engine, target, {"n": "x"}, db)

        # 195: link 表不存在
        dst_a = _mk_table(db, "br_dst_a")
        _make_link_field(db, db_engine, dst_a, "la", target, create=False)

        # 206: link 表存在但无引用行
        dst_b = _mk_table(db, "br_dst_b")
        _make_link_field(db, db_engine, dst_b, "lb", target, create=True)

        # 209: 有引用行但源表元数据缺失（table_id 指向不存在的表）
        ghost = DataField(
            table_id=999999,
            name="lb2",
            field_type="link",
            db_column_name=generate_db_column_name(),
            config={"target_table_id": target.id, "multiple": True},
            order=5,
        )
        db.add(ghost)
        db.flush()
        ddl.create_link_table(db_engine, ghost)
        db.commit()
        _insert_link(db_engine, ghost, 1, trow["id"])

        refs = links.find_back_references(db, db_engine, target, trow["id"])
        assert refs == []


class TestFindNullLinkRows:
    def test_missing_tables_returns_empty(self, db, db_engine):
        """link 表或源表缺失 → 空列表（line 240)."""
        tbl = _mk_table(db, "fnl_t")
        f = _mk_field(db, tbl, "lnk", "link", config={"target_table_id": 1, "multiple": True})
        db.commit()
        assert links.find_null_link_rows(db_engine, tbl, f) == []


class TestLinkSignatureMapMissingTable:
    def test_missing_link_table_returns_empty(self, db, db_engine):
        """关联表不存在 → 空映射（line 272)."""
        tbl = _mk_table(db, "lsm_t")
        f = _mk_field(db, tbl, "lnk", "link", config={"target_table_id": 1, "multiple": True})
        db.commit()
        assert links._link_signature_map(db_engine, f) == {}
        assert links.find_duplicate_link_values(db_engine, f) == []


class TestValidateLinkWriteTrashed:
    def test_trashed_field_skipped(self, db, db_engine):
        """trashed link 字段跳过校验（line 305)."""
        tbl = _mk_table(db, "vlw_t")
        f = _mk_field(db, tbl, "lnk", "link", config={"target_table_id": 1, "multiple": True})
        f.trashed = True
        f.required = True
        db.commit()
        # trashed 字段即使 required 且 ids 为空也不抛错
        links.validate_link_write(db_engine, [(f, [])])

    def test_unique_batch_conflict(self, db, db_engine):
        """batch_signatures 捕获批内重复集合（lines 311-312)."""
        target = _mk_table(db, "vlw_target")
        _mk_field(db, target, "n", "text")
        ddl.create_table(db_engine, target)
        tb = records.create_row(db_engine, target, {"n": "x"}, db)
        dst = _mk_table(db, "vlw_dst")
        f = _make_link_field(db, db_engine, dst, "lnk", target)
        f.is_unique = True
        db.commit()
        batch: dict[int, set] = {}
        links.validate_link_write(db_engine, [(f, [tb["id"]])], batch_signatures=batch)
        with pytest.raises(ValueError, match="批量写入中存在多行"):
            links.validate_link_write(db_engine, [(f, [tb["id"]])], batch_signatures=batch)


class TestEnsureLinkTargetsNoTrashedColumn:
    def test_table_without_trashed_column(self, db, db_engine):
        """目标物理表无 _trashed 列 → 跳过软删过滤分支（line 354->356)."""
        with db_engine.begin() as conn:
            conn.execute(text("CREATE TABLE raw_no_trash (id INTEGER PRIMARY KEY, k TEXT)"))
        raw = DataTable(workspace_id=1, name="raw_no_trash", db_table_name="raw_no_trash")
        db.add(raw)
        db.flush()
        f = _mk_field(db, raw, "lnk", "link", config={"target_table_id": raw.id, "multiple": True})
        db.commit()
        # ids 为空 → 不触发 missing 报错，仅覆盖无 _trashed 列的查询分支
        links.ensure_link_targets_exist(db_engine, f, [], db)


class TestResolveLinkTokensBranches:
    def _dst_and_field(self, db, engine, target: DataTable | None, config: dict) -> DataField:
        dst = _mk_table(db, "rlt_dst")
        return _mk_field(db, dst, "lnk", "link", config=config)

    def test_target_table_missing_raises(self, db, db_engine):
        """target 表解析失败 → 抛错（line 381)."""
        f = self._dst_and_field(db, db_engine, None, {"match_field_id": 5})
        db.commit()
        with pytest.raises(ValueError, match="关联目标表不存在"):
            links.resolve_link_tokens(db_engine, db, f, ["a"])

    def test_key_field_missing_raises(self, db, db_engine):
        """匹配字段不存在 → 抛错（line 384)."""
        target = _mk_table(db, "rlt_target")
        _mk_field(db, target, "n", "text")
        f = self._dst_and_field(db, db_engine, target, {"target_table_id": target.id, "match_field_id": 999999})
        db.commit()
        with pytest.raises(ValueError, match="匹配字段不存在"):
            links.resolve_link_tokens(db_engine, db, f, ["a"])

    def test_key_field_without_physical_column_raises(self, db, db_engine):
        """匹配字段无物理列 → 抛错（line 387)."""
        target = _mk_table(db, "rlt_target2")
        look = _mk_field(db, target, "ld", "lookup")
        f = self._dst_and_field(db, db_engine, target, {"target_table_id": target.id, "match_field_id": look.id})
        db.commit()
        with pytest.raises(ValueError, match="无物理列"):
            links.resolve_link_tokens(db_engine, db, f, ["a"])

    def test_table_without_trashed_and_duplicate_tokens(self, db, db_engine):
        """无 _trashed 列目标表 + 重复 token 去重（lines 392->394, 400->398, 409->405)."""
        with db_engine.begin() as conn:
            conn.execute(text("CREATE TABLE raw_tok (id INTEGER PRIMARY KEY, k TEXT)"))
            conn.execute(text("INSERT INTO raw_tok (id, k) VALUES (1, 'a')"))
            conn.execute(text("INSERT INTO raw_tok (id, k) VALUES (2, NULL)"))
        target = DataTable(workspace_id=1, name="raw_tok", db_table_name="raw_tok")
        db.add(target)
        db.flush()
        kf = DataField(
            table_id=target.id,
            name="k",
            field_type="text",
            db_column_name="k",
            config={},
            order=0,
        )
        db.add(kf)
        db.flush()
        dst = _mk_table(db, "rlt_dst5")
        f = _mk_field(
            db,
            dst,
            "lnk",
            "link",
            config={"target_table_id": target.id, "match_field_id": kf.id},
        )
        db.commit()
        # 重复 token：第二次命中已 resolved 分支
        assert links.resolve_link_tokens(db_engine, db, f, ["a", "a"]) == [1]


class TestMatchSummariesBranches:
    def test_no_db_returns_hash(self, db, db_engine):
        """db 为 None → #id（line 471)."""
        target = _mk_table(db, "ms_target0")
        dst = _mk_table(db, "ms_dst0")
        f = _mk_field(db, dst, "lnk", "link", config={"target_table_id": target.id})
        db.commit()
        assert links._match_summaries(db_engine, f, [3], {}, db=None) == {3: "#3"}

    def test_target_none_returns_hash(self, db, db_engine):
        """目标表解析失败 → #id（line 474)."""
        dst = _mk_table(db, "ms_dst1")
        f = _mk_field(db, dst, "lnk", "link", config={})
        db.commit()
        assert links._match_summaries(db_engine, f, [4], {}, db=db) == {4: "#4"}

    def test_match_key_differs_from_display(self, db, db_engine):
        """match 字段与 display 字段不同 → 走独立查询（lines 478->480, 483, 508-517)."""
        target = _mk_table(db, "ms_target2")
        f1 = _mk_field(db, target, "dis", "text", order=0)
        f2 = _mk_field(db, target, "mat", "text", order=1)
        ddl.create_table(db_engine, target)
        row = records.create_row(db_engine, target, {"dis": "D1", "mat": "M1"}, db)
        dst = _mk_table(db, "ms_dst2")
        lf = _mk_field(
            db,
            dst,
            "lnk",
            "link",
            config={"target_table_id": target.id, "display_field_id": f1.id, "match_field_id": f2.id},
        )
        db.commit()
        result = links._match_summaries(db_engine, lf, [row["id"]], {}, db=db)
        assert result[row["id"]] == "M1"


class TestResolveBusinessKeyBranches:
    def test_not_found_returns_none(self, db):
        """key_id 不属于目标表 → None（line 495)."""
        target = _mk_table(db, "rbk_target")
        _mk_field(db, target, "n", "text")
        db.commit()
        assert links._resolve_business_key(target, 999999) is None

    def test_no_physical_column_returns_none(self, db):
        """命中字段无物理列 → None（line 494)."""
        target = _mk_table(db, "rbk_target2")
        look = _mk_field(db, target, "ld", "lookup")
        db.commit()
        assert links._resolve_business_key(target, look.id) is None


# ══════════════════════════════════════════════════════
# records.py
# ══════════════════════════════════════════════════════


class TestNormalizeValuesDateBranches:
    def test_date_field_without_registered_type_skipped(self, monkeypatch):
        """date 字段注册表缺失 → 跳过自动填充（line 114)."""
        real = records.default_registry

        class _Stub:
            def get(self, t):
                return None if t == "date" else real.get(t)

        monkeypatch.setattr(records, "default_registry", _Stub())
        tbl = _mem_table([DataField(name="d", field_type="date", order=0, db_column_name="field_d")])
        result, link_values = records._normalize_values(tbl, {})
        assert result == {}
        assert link_values == []

    def test_date_config_invalid_skipped(self):
        """DateFieldConfig 解析失败 → 跳过（lines 117-119)."""
        tbl = _mem_table(
            [DataField(name="d", field_type="date", order=0, db_column_name="field_d", config={"auto_fill": "bogus"})]
        )
        result, link_values = records._normalize_values(tbl, {})
        assert result == {}
        assert link_values == []

    def test_auto_val_none_skipped(self, monkeypatch):
        """default_value 返回 None → 跳过（line 124)."""
        from cndb.plugins.tables.field_types import default_registry

        date_ft = default_registry.get("date")
        monkeypatch.setattr(date_ft, "default_value", lambda _cfg: None)
        tbl = _mem_table(
            [
                DataField(
                    name="d", field_type="date", order=0, db_column_name="field_d", config={"auto_fill": "on_create"}
                )
            ]
        )
        result, _ = records._normalize_values(tbl, {})
        assert result == {}

    def test_on_create_skips_when_user_provided(self):
        """on_create 且用户已传值 → 不覆盖（line 128->107)."""
        tbl = _mem_table(
            [
                DataField(
                    name="d", field_type="date", order=0, db_column_name="field_d", config={"auto_fill": "on_create"}
                )
            ]
        )
        result, _ = records._normalize_values(tbl, {"d": "2024-01-15"})
        assert result["field_d"] == __import__("datetime").date(2024, 1, 15)


class TestNormalizeValuesDefaultBranches:
    def test_default_value_no_physical_column_skipped(self):
        """lookup 字段默认值无物理列 → 跳过（line 146)."""
        tbl = _mem_table(
            [DataField(name="ld", field_type="lookup", order=0, db_column_name="field_ld", default_value="x")]
        )
        result, _ = records._normalize_values(tbl, {})
        assert result == {}

    def test_required_lookup_not_validated(self):
        """required lookup 无物理列 → 不参与必填校验（line 161)."""
        tbl = _mem_table([DataField(name="ld", field_type="lookup", order=0, db_column_name="field_ld", required=True)])
        result, _ = records._normalize_values(tbl, {})
        assert result == {}


class TestApplyAutoIncrementDefaultsError:
    def test_validate_failure_skipped(self, monkeypatch):
        """自动编号校验失败 → 跳过（lines 208-211)."""
        from cndb.plugins.tables.field_types import default_registry

        text_ft = default_registry.get("text")
        monkeypatch.setattr(text_ft, "next_increment_value", lambda *a, **k: "bad")
        monkeypatch.setattr(text_ft, "validate_value", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
        tbl = _mem_table([DataField(name="t", field_type="text", order=0, db_column_name="field_t")])
        normalized: dict = {}
        records._apply_auto_increment_defaults(None, tbl, {}, normalized)
        assert normalized == {}


class TestCreateRowEmptyLinkIds:
    def test_empty_link_ids_skips_ensure(self, db, db_engine):
        """create_row 中空 link ids 跳过目标校验（line 246->245)."""
        dst = _mk_table(db, "cr_dst")
        _mk_field(db, dst, "own", "text", order=0)
        _mk_field(db, dst, "lnk", "link", order=1, config={"target_table_id": 1, "multiple": True})
        ddl.create_table(db_engine, dst)
        db.commit()
        row = records.create_row(db_engine, dst, {"own": "x", "lnk": []}, db)
        assert row is not None
        assert row["lnk"] == []


class TestListRowsOffsetBranches:
    def test_offset_without_limit_sql_path(self, db, db_engine):
        """无 lookup 时 limit=None + offset → 仅加 offset（line 462)."""
        tbl = _mk_table(db, "lro_t")
        _mk_field(db, tbl, "n", "text")
        ddl.create_table(db_engine, tbl)
        for v in ("a", "b"):
            records.create_row(db_engine, tbl, {"n": v}, db)
        db.commit()
        rows, total = records.list_rows(db_engine, tbl, limit=None, offset=1, db=db)
        assert total == 2
        assert len(rows) == 1

    def test_offset_without_limit_post_path(self, db, db_engine):
        """含 lookup 排序时 limit=None + offset → 内存切片（lines 481-482)."""
        dst, _look, _lf, _sf, _srows = _lookup_scenario(db, db_engine)
        rows, _total = records.list_rows(
            db_engine,
            dst,
            sorts=[{"field_name": "lref", "direction": "asc"}],
            limit=None,
            offset=1,
            db=db,
        )
        assert isinstance(rows, list)


class TestRowScopeAppended:
    def _perm_table(self, db, engine, name):
        tbl = _mk_table(db, name)
        _mk_field(db, tbl, "n", "text")
        ddl.create_table(engine, tbl)
        row = records.create_row(engine, tbl, {"n": "keep"}, db)
        db.add(TablePermission(table_id=tbl.id, row_filters=[{"field_name": "n", "op": "=", "value": "keep"}]))
        db.commit()
        return tbl, row

    def test_delete_row_with_scope(self, db, db_engine):
        """delete_row 追加行范围条件（line 578)."""
        tbl, _row = self._perm_table(db, db_engine, "rs_del")
        assert records.delete_row(db_engine, tbl, 1, db) is True

    def test_trash_row_with_scope(self, db, db_engine):
        """trash_row 追加行范围条件（line 612)."""
        tbl, _row = self._perm_table(db, db_engine, "rs_trash")
        assert records.trash_row(db_engine, tbl, 1, db) is True

    def test_restore_row_with_scope(self, db, db_engine):
        """restore_row 追加行范围条件（line 637)."""
        tbl, _row = self._perm_table(db, db_engine, "rs_restore")
        assert records.trash_row(db_engine, tbl, 1, db) is True
        assert records.restore_row(db_engine, tbl, 1, db) is True

    def test_trash_nonexistent_returns_false(self, db, db_engine):
        """trash 不存在行 → ok False，不记 audit（line 623->628)."""
        tbl, _row = self._perm_table(db, db_engine, "rs_trash2")
        assert records.trash_row(db_engine, tbl, 99999, db) is False


class TestRowToDictUnknownColumn:
    def test_unknown_column_passthrough(self, db):
        """物理列无对应字段 → 原样输出（line 847)."""
        tbl = _mk_table(db, "rd_t")
        _mk_field(db, tbl, "n", "text")
        db.commit()
        fake_row = types.SimpleNamespace(_mapping={"id": 1, "unknown_col": "v", "_trashed": False})
        out = records._row_to_dict(tbl, None, fake_row)
        assert out == {"id": 1, "unknown_col": "v"}


class TestBulkBranches:
    def _perm_table(self, db, engine, name, rows=2):
        tbl = _mk_table(db, name)
        _mk_field(db, tbl, "n", "text")
        ddl.create_table(engine, tbl)
        ids = [records.create_row(engine, tbl, {"n": f"r{i}"}, db)["id"] for i in range(rows)]
        db.add(TablePermission(table_id=tbl.id, row_filters=[{"field_name": "n", "op": "contains", "value": "r"}]))
        db.commit()
        return tbl, ids

    def test_bulk_delete_no_valid_ids(self, db, db_engine):
        """bulk_delete 无有效行 → 提前返回 0（line 810)."""
        tbl = _mk_table(db, "bd_zero")
        _mk_field(db, tbl, "n", "text")
        ddl.create_table(db_engine, tbl)
        db.commit()
        assert records.bulk_delete(db_engine, tbl, [99999], db) == 0

    def test_bulk_delete_with_scope(self, db, db_engine):
        """bulk_delete 追加行范围 + 计数（lines 805, 817-826)."""
        tbl, ids = self._perm_table(db, db_engine, "bd_scope")
        assert records.bulk_delete(db_engine, tbl, ids, db) == 2

    def test_bulk_update_with_scope(self, db, db_engine):
        """bulk_update 追加行范围条件（lines 763, 778)."""
        tbl, ids = self._perm_table(db, db_engine, "bu_scope")
        assert records.bulk_update(db_engine, tbl, ids, {"n": "z"}, db) == 2

    def test_bulk_create_empty_link_ids(self, db, db_engine):
        """bulk_create 空 link ids 跳过目标校验（line 680->679)."""
        dst = _mk_table(db, "bc_dst")
        _mk_field(db, dst, "own", "text", order=0)
        _mk_field(db, dst, "lnk", "link", order=1, config={"target_table_id": 1, "multiple": True})
        ddl.create_table(db_engine, dst)
        db.commit()
        ids = records.bulk_create(db_engine, dst, [{"own": "a", "lnk": []}, {"own": "b", "lnk": []}], db)
        assert len(ids) == 2

    def test_bulk_update_empty_link_ids(self, db, db_engine):
        """bulk_update 空 link ids 跳过目标校验（line 755->754)."""
        dst = _mk_table(db, "bu_dst")
        _mk_field(db, dst, "own", "text", order=0)
        _mk_field(db, dst, "lnk", "link", order=1, config={"target_table_id": 1, "multiple": True})
        ddl.create_table(db_engine, dst)
        rid = records.create_row(db_engine, dst, {"own": "a"}, db)["id"]
        db.commit()
        assert records.bulk_update(db_engine, dst, [rid], {"lnk": []}, db) >= 1


class TestBulkUpdateRowsBranches:
    def _env(self, db, engine, name):
        target = _mk_table(db, name + "_t")
        _mk_field(db, target, "n", "text")
        ddl.create_table(engine, target)
        trow = records.create_row(engine, target, {"n": "x"}, db)
        dst = _mk_table(db, name + "_d")
        _mk_field(db, dst, "n", "text", order=0)
        _mk_field(db, dst, "lnk", "link", order=1, config={"target_table_id": target.id, "multiple": True})
        ddl.create_table(engine, dst)
        rid = records.create_row(engine, dst, {"n": "a"}, db)["id"]
        db.commit()
        return dst, rid, trow["id"]

    def test_db_none_skips_validation(self, db, db_engine):
        """db=None → 跳过预校验（line 961->972)."""
        dst, rid, _tid = self._env(db, db_engine, "bur_none")
        assert records.bulk_update_rows(db_engine, dst, [{"row_id": rid, "values": {"n": "b"}}], None) == 1

    def test_link_only_update(self, db, db_engine):
        """仅有 link 值 → 走 link-only 分支（lines 1006-1012)."""
        dst, rid, tid = self._env(db, db_engine, "bur_link")
        n = records.bulk_update_rows(db_engine, dst, [{"row_id": rid, "values": {"lnk": [tid]}}], db)
        assert n == 1
        assert links.load_links(
            db_engine, db.query(DataField).filter_by(table_id=dst.id, name="lnk").first(), [rid]
        ) == {rid: [tid]}

    def test_row_scope_and_empty_values(self, db, db_engine):
        """行范围条件 + 空 values 跳过（lines 968->967, 996)."""
        dst, rid, _tid = self._env(db, db_engine, "bur_scope")
        # 空 link ids 触发 968->967；同时建行范围
        f = db.query(DataField).filter_by(table_id=dst.id, name="lnk").first()
        db.add(TablePermission(table_id=dst.id, row_filters=[{"field_name": "n", "op": "=", "value": "a"}]))
        db.commit()
        n = records.bulk_update_rows(
            db_engine,
            dst,
            [
                {"row_id": rid, "values": {"lnk": []}},  # link_values ids 空 → 968->967
                {"row_id": rid, "values": {"n": "a"}},  # 命中行范围
            ],
            db,
        )
        assert n >= 1
        assert f is not None


# ══════════════════════════════════════════════════════
# field_import.py
# ══════════════════════════════════════════════════════


class TestUniqueNameHelpers:
    def test_unique_name_against_no_collision(self):
        assert fi._unique_name_against({"a"}, "b") == "b"

    def test_unique_name_against_with_index(self):
        assert fi._unique_name_against({"a"}, "a") == "a 2"
        assert fi._unique_name_against({"a", "a 2"}, "a") == "a 3"

    def test_unique_dst_name_no_collision(self, db):
        tbl = _mk_table(db, "udn_t")
        _mk_field(db, tbl, "base", "text")
        db.commit()
        assert fi._unique_dst_name(tbl, "other") == "other"

    def test_unique_dst_name_with_index(self, db):
        tbl = _mk_table(db, "udn_t2")
        _mk_field(db, tbl, "base", "text")
        _mk_field(db, tbl, "base 2", "text")
        db.commit()
        assert fi._unique_dst_name(tbl, "base") == "base 3"


class TestImportFieldsAsLookup:
    def test_create_link_table_failure_raises(self, db, db_engine, monkeypatch):
        """创建关联物理表失败 → 记录并抛出（lines 448-450)."""
        src = _mk_table(db, "ifl_src")
        sf = _mk_field(db, src, "name", "text")
        dst = _mk_table(db, "ifl_dst")
        db.commit()

        def _boom(*a, **k):
            raise RuntimeError("ddl fail")

        monkeypatch.setattr(fi._ddl, "create_link_table", _boom)
        with pytest.raises(RuntimeError, match="ddl fail"):
            fi.import_fields_as_lookup(db_engine, db, src, dst, [sf])

    def test_enable_lookup_and_skip_source(self, db, db_engine):
        """正常关联引入：建 link + lookup，跳过 link/lookup 源字段."""
        src = _mk_table(db, "ifl_src2")
        sf = _mk_field(db, src, "name", "text")
        sfl = _mk_field(db, src, "ld", "lookup")
        dst = _mk_table(db, "ifl_dst2")
        db.commit()
        created, skipped = fi.import_fields_as_lookup(db_engine, db, src, dst, [sf, sfl])
        types_created = {f.field_type for f in created}
        assert "link" in types_created
        assert "lookup" in types_created
        assert any("不支持关联引入" in s for s in skipped)


class TestSyncLinkReferenceFields:
    def test_create_update_and_stale_soft_delete(self, db):
        """新建引用字段 → 复用 → 移除软删除让位（lines 563-565, 580-634)."""
        target = _mk_table(db, "slrf_target")
        tf1 = _mk_field(db, target, "关联", "text", order=0)  # 名字与 link 字段同名，触发去重
        tf2 = _mk_field(db, target, "b", "text", order=1)
        dst = _mk_table(db, "slrf_dst")
        _mk_field(db, dst, "关联 2", "text", order=0)  # 占用 "关联 2" 名字
        lf = _mk_field(
            db,
            dst,
            "关联",
            "link",
            order=1,
            config={"target_table_id": target.id, "reference_fields": [tf1.id, tf2.id]},
        )
        db.commit()

        kept = fi.sync_link_reference_fields(db, lf, target)
        assert len(kept) == 2
        names = {f.name for f in kept}
        # tf1 源名 "关联" 与 link 同名 → 去重为 "关联 3"（"关联 2" 已被占用）
        assert "关联 3" in names
        assert "b" in names
        b_lookup = next(f for f in kept if f.name == "b")

        # 第二次：仅保留 tf1 → tf2 对应 lookup 软删除让位
        db.refresh(lf)
        lf.config = {**lf.config, "reference_fields": [tf1.id]}
        db.commit()
        kept2 = fi.sync_link_reference_fields(db, lf, target)
        assert len(kept2) == 1
        db.refresh(b_lookup)
        assert b_lookup.trashed is True


# ══════════════════════════════════════════════════════
# 残余缺口补齐（baseline 未覆盖 & 上批测试未触及的行/分支）
# ══════════════════════════════════════════════════════


class TestResolveLookupSourceTableMissing:
    def test_source_physical_table_absent(self, db, db_engine):
        """关联非空但源物理表缺失 → _read_source_values 返回 None（lines 165, 515)."""
        src = _mk_table(db, "lksm_src")
        sf = _mk_field(db, src, "sval", "text")  # 源物理表从未创建
        dst = _mk_table(db, "lksm_dst")
        lf = _mk_field(db, dst, "lnk", "link", order=0, config={"target_table_id": src.id, "multiple": True})
        look = _mk_field(
            db,
            dst,
            "lref",
            "lookup",
            order=1,
            config={
                "source_table_id": src.id,
                "source_field_id": sf.id,
                "via_link_field_id": lf.id,
                "source_field_type": "text",
            },
        )
        ddl.create_table(db_engine, dst)  # 建 dst（含关联表），src 物理表缺失
        row = records.create_row(db_engine, dst, {"lnk": []}, db)
        db.commit()
        _insert_link(db_engine, lf, row["id"], 4242)  # 直接写关联，保证 mapping 非空
        assert lookups._resolve_lookup_values(db_engine, db, dst, look.config, [row["id"]]) == {}


class TestMatchPhysicalValueNestedExcept:
    def test_inner_fallback_exception_returns_false(self):
        """内层字符串回退再次异常 → 返回 False（lines 341-342)."""

        class _Weird:
            def __gt__(self, other):
                raise TypeError("no gt")

            def __str__(self):
                raise RuntimeError("no str")

        assert _match_physical_value(_Weird(), ">", 5) is False  # type: ignore[arg-type]


class TestLinkMatchFieldsFallback:
    def test_no_match_or_display_falls_back(self, db):
        """match_field_id / display_field_id 均缺失 → 启发式摘要字段（lines 513, 517)."""
        target = _mk_table(db, "lmf_target")
        _mk_field(db, target, "n", "text")
        dst = _mk_table(db, "lmf_dst")
        f = _mk_field(db, dst, "lnk", "link", config={"target_table_id": target.id, "multiple": True})
        db.commit()
        fields = links._link_match_fields(target, f)
        assert [x.name for x in fields] == ["n"]


class TestResolveLinkTokensDuplicateKey:
    def test_duplicate_target_key_values(self, db, db_engine):
        """目标表存在重复键值 → 第二条命中已建映射（line 400->398)."""
        with db_engine.begin() as conn:
            conn.execute(text("CREATE TABLE raw_dup (id INTEGER PRIMARY KEY, k TEXT)"))
            conn.execute(text("INSERT INTO raw_dup (id, k) VALUES (1, 'a')"))
            conn.execute(text("INSERT INTO raw_dup (id, k) VALUES (2, 'a')"))
        target = DataTable(workspace_id=1, name="raw_dup", db_table_name="raw_dup")
        db.add(target)
        db.flush()
        kf = DataField(table_id=target.id, name="k", field_type="text", db_column_name="k", config={}, order=0)
        db.add(kf)
        db.flush()
        dst = _mk_table(db, "rlt_dup_dst")
        f = _mk_field(db, dst, "lnk", "link", config={"target_table_id": target.id, "match_field_id": kf.id})
        db.commit()
        assert links.resolve_link_tokens(db_engine, db, f, ["a"]) == [1]


class TestCreateRowGetRowNone:
    def test_row_none_skips_audit(self, db, db_engine, monkeypatch):
        """get_row 返回 None → 跳过 audit 记录（line 266->271)."""
        tbl = _mk_table(db, "cr_rownone")
        _mk_field(db, tbl, "n", "text", order=0)
        ddl.create_table(db_engine, tbl)
        db.commit()
        monkeypatch.setattr(records, "get_row", lambda *a, **k: None)
        assert records.create_row(db_engine, tbl, {"n": "x"}, db) is None


class TestImportLookupCommitFailure:
    def test_lookup_commit_failure_rolls_back(self, db, db_engine, monkeypatch):
        """lookup 批量 commit 失败 → rollback 并抛出（lines 490-493)."""
        src = _mk_table(db, "ilcf_src")
        sf = _mk_field(db, src, "name", "text")
        dst = _mk_table(db, "ilcf_dst")
        # 预置指向 src 的 link 字段 → 复用，跳过建 link 的 commit，只留 lookup commit
        linkf = _mk_field(db, dst, "lnk", "link", config={"target_table_id": src.id, "multiple": True})
        ddl.create_link_table(db_engine, linkf)
        db.commit()

        def _boom() -> None:
            raise RuntimeError("commit boom")

        monkeypatch.setattr(db, "commit", _boom)
        with pytest.raises(RuntimeError, match="commit boom"):
            fi.import_fields_as_lookup(db_engine, db, src, dst, [sf])


class TestSyncLinkReferenceFieldsResidual:
    def test_orphan_lookup_and_stale_ref(self, db):
        """名下 lookup 缺 source_field_id（564->562）+ 陈旧 ref_id（line 582)."""
        target = _mk_table(db, "slrfr_target")
        tf = _mk_field(db, target, "a", "text", order=0)
        dst = _mk_table(db, "slrfr_dst")
        lf = _mk_field(
            db,
            dst,
            "lnk",
            "link",
            order=0,
            config={"target_table_id": target.id, "reference_fields": [tf.id, 999999]},
        )
        _mk_field(db, dst, "orphan", "lookup", order=1, config={"via_link_field_id": lf.id})
        db.commit()
        kept = fi.sync_link_reference_fields(db, lf, target)
        assert len(kept) == 1
        assert kept[0].name == "a"


class TestRegisterLinkReferenceFieldsResidual:
    def test_orphan_lookup_no_source_id(self, db):
        """名下 lookup 缺 source_field_id → 跳过登记（line 531->529)."""
        dst = _mk_table(db, "rlrfr_dst")
        lf = _mk_field(db, dst, "lnk", "link", config={"target_table_id": 1, "multiple": True})
        _mk_field(db, dst, "orphan", "lookup", config={"via_link_field_id": lf.id})
        db.commit()
        fi._register_link_reference_fields(db, lf)
        db.refresh(lf)
        assert lf.config.get("reference_fields") == []


__all__: list[str] = []
