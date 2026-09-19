"""match_key_advisor.recommend_match_keys 单元测试 —— 参考列推荐 / 禁用 / 降级."""

from __future__ import annotations

import json

import pytest

from cndb.plugins.tables import ddl
from cndb.plugins.tables.match_key_advisor import recommend_match_keys
from tests.test_import_pipeline import _add_field, _make_table


@pytest.fixture
def test_session(db_engine, db):
    """复用 conftest 内存 DB，yield (engine, session) 保持与主测试文件签名一致."""
    yield db_engine, db


def _entry(entries: list[dict], field: str) -> dict:
    """按字段名取推荐条目."""
    return next(e for e in entries if e["field"] == field)


class TestRecommendMatchKeys:
    """recommend_match_keys：推荐 / 禁用 / 提示原因 / 排序."""

    def test_unique_column_recommended_and_dup_not(self, test_session):
        """文件与表侧都唯一的列推荐置顶；文件侧重复列不推荐并提示重复原因."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", required=True, order=0)
        _add_field(session, table, "name", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)
        from cndb.plugins.tables import records as rec

        rec.bulk_create(
            engine,
            table,
            [{"code": "A1", "name": "苹果"}, {"code": "A2", "name": "香蕉"}],
            db=session,
        )
        rows = [
            {"code": "A1", "name": "Apple"},
            {"code": "A2", "name": "Apple"},
        ]
        entries = recommend_match_keys(engine, table, rows, ["code", "name"], [])

        code = _entry(entries, "code")
        assert code["recommended"] is True
        assert code["disabled"] is False
        assert code["score"] >= 0.9
        assert code["stats"]["table_rows"] == 2
        assert code["stats"]["table_unique_ratio"] == 1.0
        assert entries[0]["field"] == "code"  # 推荐项排最前

        name = _entry(entries, "name")
        assert name["recommended"] is False
        assert name["disabled"] is False
        assert "重复值" in name["reason"]
        assert "文件中" in name["reason"]  # 重复在文件侧

    def test_file_all_null_disabled_scan_path(self, test_session):
        """文件侧全空列 → 禁用并提示原因（画像缺失走行扫描兜底）."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        _add_field(session, table, "remark", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)
        from cndb.plugins.tables import records as rec

        rec.bulk_create(engine, table, [{"code": "A", "remark": "x"}], db=session)
        rows = [{"code": "A", "remark": ""}, {"code": "B", "remark": "  "}]
        entries = recommend_match_keys(engine, table, rows, ["code", "remark"], [])
        remark = _entry(entries, "remark")
        assert remark["disabled"] is True
        assert "文件中该列全为空" in remark["reason"]

    def test_file_all_null_disabled_profile_path(self, test_session):
        """文件侧全空列（画像路径：null_ratio=1.0）→ 禁用."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        _add_field(session, table, "remark", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)
        from cndb.plugins.tables import records as rec

        rec.bulk_create(engine, table, [{"code": "A", "remark": "x"}], db=session)
        profiles = [
            {"name": "code", "null_count": 0, "null_ratio": 0.0, "unique_count": 2},
            {"name": "remark", "null_count": 2, "null_ratio": 1.0, "unique_count": 0},
        ]
        rows = [{"code": "A", "remark": None}, {"code": "B", "remark": None}]
        entries = recommend_match_keys(engine, table, rows, ["code", "remark"], profiles)
        remark = _entry(entries, "remark")
        assert remark["disabled"] is True
        assert "文件中该列全为空" in remark["reason"]

    def test_table_all_null_disabled(self, test_session):
        """表侧全空列 → 禁用并提示原因."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        _add_field(session, table, "remark", "text", order=1)
        session.commit()
        ddl.create_table(engine, table)
        from cndb.plugins.tables import records as rec

        # 库内 remark 全为 NULL（bulk_create 跳过 None）
        rec.bulk_create(engine, table, [{"code": "A"}, {"code": "B"}], db=session)
        rows = [{"code": "A", "remark": "x"}, {"code": "B", "remark": "y"}]
        entries = recommend_match_keys(engine, table, rows, ["code", "remark"], [])
        remark = _entry(entries, "remark")
        assert remark["disabled"] is True
        assert "表中该列全为空" in remark["reason"]

    def test_empty_table_file_side_only(self, test_session):
        """空表 → 仅按文件侧评估，唯一列仍推荐且保留"表内暂无数据"提示."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)

        rows = [{"code": "A"}, {"code": "B"}]
        entries = recommend_match_keys(engine, table, rows, ["code"], [])
        code = _entry(entries, "code")
        assert code["recommended"] is True
        assert code["stats"]["table_rows"] is None
        assert code["reason"] == "表内暂无数据，仅按文件侧评估"

    def test_missing_physical_table_degrades(self, test_session):
        """物理表不存在 → 表侧统计降级为 None，仅按文件侧评估且不抛异常."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        session.commit()
        # 刻意不调 ddl.create_table → _get_sa_table 抛异常 → 降级

        rows = [{"code": "A"}, {"code": "B"}]
        entries = recommend_match_keys(engine, table, rows, ["code"], [])
        code = _entry(entries, "code")
        assert code["stats"]["table_unique_ratio"] is None
        assert code["recommended"] is True  # 文件侧唯一即推荐

    def test_field_mapping_resolves_source_col(self, test_session):
        """field_mapping：目标字段 code 的文件源列是 src_code，行数据按源列取."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)
        from cndb.plugins.tables import records as rec

        rec.bulk_create(engine, table, [{"code": "A1"}, {"code": "A2"}], db=session)
        rows = [{"src_code": "A1"}, {"src_code": "A2"}]
        entries = recommend_match_keys(engine, table, rows, ["src_code"], [], field_mapping={"src_code": "code"})
        code = _entry(entries, "code")
        assert code["recommended"] is True
        assert code["stats"]["file_unique_ratio"] == 1.0

    def test_table_side_duplicate_reason(self, test_session):
        """表侧重复 → 不推荐，reason 指向表中."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)
        from cndb.plugins.tables import records as rec

        rec.bulk_create(engine, table, [{"code": "X"}, {"code": "X"}], db=session)
        rows = [{"code": "X"}, {"code": "Y"}]
        entries = recommend_match_keys(engine, table, rows, ["code"], [])
        code = _entry(entries, "code")
        assert code["recommended"] is False
        assert "表中该列有重复值" in code["reason"]

    def test_low_nonnull_score_reason(self, test_session):
        """唯一率高但非空率低（score < 0.9）→ 不推荐，提示唯一性/非空率不足."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)
        from cndb.plugins.tables import records as rec

        rec.bulk_create(engine, table, [{"code": "A"}, {"code": "B"}], db=session)
        # 文件侧一半为空 → nonnull=0.5 → score=0.6*1.0+0.4*0.5=0.8 < 0.9
        rows = [{"code": "A"}, {"code": ""}]
        entries = recommend_match_keys(engine, table, rows, ["code"], [])
        code = _entry(entries, "code")
        assert code["recommended"] is False
        assert code["disabled"] is False
        assert code["reason"] == "唯一性或非空率不足，慎用"

    @pytest.mark.parametrize("ftype", ["link", "attachment", "multiselect", "json"])
    def test_unsupported_types_disabled(self, ftype, test_session):
        """link/attachment/multiselect/json 类型直接禁用并提示类型原因（不触发表侧查询）."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "rel", ftype, order=0)
        session.commit()
        # 不建物理表 —— 禁用类型不参与聚合查询；若误查会因缺表抛错导致用例失败
        entries = recommend_match_keys(engine, table, [], ["rel"], [])
        assert len(entries) == 1
        assert entries[0]["field"] == "rel"
        assert entries[0]["disabled"] is True
        assert "不适合做参考列" in entries[0]["reason"]

    def test_result_is_json_serializable(self, test_session):
        """输出全为标量结构，可直接 json.dumps."""
        engine, session = test_session
        table = _make_table(session, engine)
        _add_field(session, table, "code", "text", order=0)
        session.commit()
        ddl.create_table(engine, table)
        from cndb.plugins.tables import records as rec

        rec.bulk_create(engine, table, [{"code": "A"}], db=session)
        entries = recommend_match_keys(engine, table, [{"code": "A"}], ["code"], [])
        json.dumps(entries, ensure_ascii=False)  # 不抛即通过
