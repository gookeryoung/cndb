"""单行文本自动编号默认值测试 —— TextFieldConfig 校验 + next_increment_value + 建行填充."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cndb.plugins.tables import ddl
from cndb.plugins.tables import records as rec
from cndb.plugins.tables.field_types import TextFieldConfig, TextFieldType
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace

# ── 通用脚手架 ────────────────────────────────────────


@pytest.fixture
def ws(db):
    """最小工作区（created_by_id 可空，无需用户）."""
    workspace = Workspace(name="AI_WS")
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


def _make_table_with_increment(db, db_engine, ws, name: str, config: dict) -> tuple[DataTable, DataField]:
    """建表 + 单行文本自动编号字段，返回 (表, 字段)。"""
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    df = DataField(table_id=dt.id, name="编号", field_type="text", order=0, config=config)
    df.ensure_db_name()
    db.add(df)
    db.commit()
    db.refresh(dt)
    ddl.create_table(db_engine, dt)
    return dt, df


# ── TextFieldConfig 校验矩阵 ──────────────────────────


class TestTextFieldConfigValidation:
    def test_valid_config(self):
        """合法配置原样保留。"""
        cfg = TextFieldConfig(
            default_mode="auto_increment", increment_prefix="PRJ-", increment_padding=5, increment_start=10
        )
        assert cfg.default_mode == "auto_increment"
        assert cfg.increment_prefix == "PRJ-"
        assert cfg.increment_padding == 5
        assert cfg.increment_start == 10

    def test_defaults_are_static_mode(self):
        """默认配置为静态默认值模式（不启用自动编号）。"""
        cfg = TextFieldConfig()
        assert cfg.default_mode == ""
        assert cfg.increment_prefix == ""
        assert cfg.increment_padding == 4
        assert cfg.increment_start == 1

    @pytest.mark.parametrize("bad_mode", ["auto", "AUTO_INCREMENT", "static", "auto_increment "])
    def test_invalid_default_mode_rejected(self, bad_mode: str):
        """非法 default_mode 被模式约束拒绝。"""
        with pytest.raises(ValidationError, match="default_mode"):
            TextFieldConfig(default_mode=bad_mode)

    @pytest.mark.parametrize("bad_padding", [-1, 11])
    def test_padding_out_of_range_rejected(self, bad_padding: int):
        """补零位数超出 [0, 10] 被拒绝。"""
        with pytest.raises(ValidationError, match="increment_padding"):
            TextFieldConfig(increment_padding=bad_padding)

    def test_negative_start_rejected(self):
        """起始编号不能为负。"""
        with pytest.raises(ValidationError, match="increment_start"):
            TextFieldConfig(increment_start=-1)


# ── next_increment_value 单元测试 ─────────────────────


class TestNextIncrementValue:
    def test_not_enabled_returns_none(self, db, db_engine, ws):
        """未启用 auto_increment 的字段返回 None。"""
        dt, df = _make_table_with_increment(db, db_engine, ws, "AINotEnabled", {})
        assert TextFieldType().next_increment_value(db_engine, dt, df) is None

    def test_missing_table_returns_fallback(self, db, ws):
        """物理表不存在时返回 start 补零的兜底值。"""
        dt = DataTable(workspace_id=ws.id, name="AINoTable")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        df = DataField(
            table_id=dt.id, name="编号", field_type="text", order=0, config={"default_mode": "auto_increment"}
        )
        df.ensure_db_name()
        db.add(df)
        db.commit()

        # 独立空内存库：不含该物理表 → table_exists False → fallback（无前缀 → "0001"）
        from sqlalchemy import create_engine

        assert TextFieldType().next_increment_value(create_engine("sqlite://"), dt, df) == "0001"

    def test_empty_table_returns_start(self, db, db_engine, ws):
        """空表从 start 开始。"""
        dt, df = _make_table_with_increment(
            db, db_engine, ws, "AIEmpty", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        assert TextFieldType().next_increment_value(db_engine, dt, df) == "PRJ-0001"

    def test_scans_max_and_increments(self, db, db_engine, ws):
        """库内已有 PRJ-0007 时下一个为 PRJ-0008。"""
        dt, df = _make_table_with_increment(
            db, db_engine, ws, "AIMax", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        rec.create_row(db_engine, dt, {"编号": "PRJ-0007"})
        assert TextFieldType().next_increment_value(db_engine, dt, df) == "PRJ-0008"

    def test_non_matching_values_ignored(self, db, db_engine, ws):
        """前缀不匹配的值（手动输入）不参与编号推算。"""
        dt, df = _make_table_with_increment(
            db, db_engine, ws, "AIMismatch", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        rec.create_row(db_engine, dt, {"编号": "CUSTOM-9"})
        rec.create_row(db_engine, dt, {"编号": "PRJ-abc"})
        assert TextFieldType().next_increment_value(db_engine, dt, df) == "PRJ-0001"

    def test_padding_zero(self, db, db_engine, ws):
        """padding=0 时数字不补零。"""
        dt, df = _make_table_with_increment(
            db,
            db_engine,
            ws,
            "AIPad0",
            {"default_mode": "auto_increment", "increment_prefix": "N", "increment_padding": 0},
        )
        rec.create_row(db_engine, dt, {"编号": "N7"})
        assert TextFieldType().next_increment_value(db_engine, dt, df) == "N8"

    def test_start_wins_over_smaller_max(self, db, db_engine, ws):
        """start 大于库内最大编号时取 start。"""
        dt, df = _make_table_with_increment(
            db,
            db_engine,
            ws,
            "AIStart",
            {"default_mode": "auto_increment", "increment_prefix": "PRJ-", "increment_start": 100},
        )
        rec.create_row(db_engine, dt, {"编号": "PRJ-0002"})
        assert TextFieldType().next_increment_value(db_engine, dt, df) == "PRJ-0100"

    def test_soft_deleted_rows_counted(self, db, db_engine, ws):
        """软删行（物理行仍存在）计入 max，与唯一索引口径一致。"""
        dt, df = _make_table_with_increment(
            db, db_engine, ws, "AISoftDel", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        row = rec.create_row(db_engine, dt, {"编号": "PRJ-0042"})
        rec.trash_row(db_engine, dt, row["id"])
        assert TextFieldType().next_increment_value(db_engine, dt, df) == "PRJ-0043"


# ── 建行路径自动填充 ──────────────────────────────────


class TestCreateRowAutoIncrement:
    def _fixture(self, db, db_engine, ws, name: str, config: dict | None = None):
        cfg = {"default_mode": "auto_increment", "increment_prefix": "PRJ-"} if config is None else config
        return _make_table_with_increment(db, db_engine, ws, name, cfg)

    def test_consecutive_rows_increment(self, db, db_engine, ws):
        """连续建行编号递增。"""
        dt, _df = self._fixture(db, db_engine, ws, "AISeq")
        assert rec.create_row(db_engine, dt, {})["编号"] == "PRJ-0001"
        assert rec.create_row(db_engine, dt, {})["编号"] == "PRJ-0002"

    def test_explicit_value_not_overridden(self, db, db_engine, ws):
        """用户显式传值时不覆盖；后续编号不受非格式值影响。"""
        dt, _df = self._fixture(db, db_engine, ws, "AIExplicit")
        assert rec.create_row(db_engine, dt, {"编号": "手动值"})["编号"] == "手动值"
        assert rec.create_row(db_engine, dt, {})["编号"] == "PRJ-0001"

    def test_explicit_matching_value_advances_counter(self, db, db_engine, ws):
        """显式传入符合格式的值同样计入 max（下一行顺延）。"""
        dt, _df = self._fixture(db, db_engine, ws, "AIExplicitMatch")
        assert rec.create_row(db_engine, dt, {"编号": "PRJ-0050"})["编号"] == "PRJ-0050"
        assert rec.create_row(db_engine, dt, {})["编号"] == "PRJ-0051"

    def test_explicit_none_wins(self, db, db_engine, ws):
        """显式传 None（清空意图）不填编号。"""
        dt, _df = self._fixture(db, db_engine, ws, "AINone")
        assert rec.create_row(db_engine, dt, {"编号": None})["编号"] is None

    def test_increment_wins_over_static_default(self, db, db_engine, ws):
        """静态 default_value 与 auto_increment 并存时编号优先。"""
        dt = DataTable(workspace_id=ws.id, name="AIPriority")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        df = DataField(
            table_id=dt.id,
            name="编号",
            field_type="text",
            order=0,
            default_value="静态默认",
            config={"default_mode": "auto_increment", "increment_prefix": "PRJ-"},
        )
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)

        assert rec.create_row(db_engine, dt, {})["编号"] == "PRJ-0001"

    def test_bulk_create_increments_row_by_row(self, db, db_engine, ws):
        """bulk_create 逐行顺序递增。"""
        dt, _df = self._fixture(db, db_engine, ws, "AIBulk")
        ids = rec.bulk_create(db_engine, dt, [{}, {}, {"编号": "跳过"}])
        assert len(ids) == 3
        rows, _total = rec.list_rows(db_engine, dt)
        values = {r["id"]: r["编号"] for r in rows}
        assert values[ids[0]] == "PRJ-0001"
        assert values[ids[1]] == "PRJ-0002"
        assert values[ids[2]] == "跳过"

    def test_auto_increment_with_unique_constraint(self, db, db_engine, ws):
        """自动编号 + 唯一约束协同：连续建行不触发唯一冲突。"""
        dt, _df = self._fixture(db, db_engine, ws, "AIUnique")
        df = next(f for f in dt.fields if f.name == "编号")
        df.is_unique = True
        db.commit()
        ddl.add_unique_constraint(db_engine, dt, df)

        rows = [rec.create_row(db_engine, dt, {}) for _ in range(3)]
        assert [r["编号"] for r in rows] == ["PRJ-0001", "PRJ-0002", "PRJ-0003"]


# ── API 往返（config 键完整） ─────────────────────────


class TestAutoIncrementApiRoundtrip:
    def test_create_and_get_config_roundtrip(self, client, auth_headers):
        """创建带 auto_increment config 的字段 → GET 返回 config 四键完整."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ai_api"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ai_api"})
        tid = t.json()["id"]

        config = {
            "default_mode": "auto_increment",
            "increment_prefix": "PRJ-",
            "increment_padding": 5,
            "increment_start": 3,
        }
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "编号", "field_type": "text", "order": 0, "config": config},
        )
        assert r.status_code == 201, r.text

        fields = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=auth_headers).json()
        got = next(f for f in fields if f["name"] == "编号")
        for key, value in config.items():
            assert got["config"][key] == value

    def test_invalid_config_rejected(self, client, auth_headers):
        """非法 config（mode 不合法）→ 400。"""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ai_bad"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ai_bad"})
        tid = t.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "编号", "field_type": "text", "order": 0, "config": {"default_mode": "nonsense"}},
        )
        assert r.status_code == 400
