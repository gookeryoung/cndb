"""单行文本自动编号默认值测试 —— TextFieldConfig 校验 + next_increment_value + 建行填充."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from cndb.plugins.tables.field_types import TextFieldConfig, TextFieldType
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
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

    def test_whitespace_padded_values_counted(self, db, db_engine, ws):
        """历史 / 导入值带首尾空白也要计入 max，避免从头开始编号。"""
        dt, df = _make_table_with_increment(
            db, db_engine, ws, "AIWhitespace", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        rec.create_row(db_engine, dt, {"编号": " PRJ-0041 "})
        assert TextFieldType().next_increment_value(db_engine, dt, df) == "PRJ-0042"


# ── 自动编号预览（新增行只读展示） ─────────────────────


class TestPreviewAutoIncrementValues:
    def test_empty_table_returns_start(self, db, db_engine, ws):
        """空表预览返回起始编号。"""
        dt, _df = _make_table_with_increment(
            db, db_engine, ws, "AIPreviewEmpty", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        assert rec.preview_auto_increment_values(db_engine, dt) == {"编号": "PRJ-0001"}

    def test_uses_existing_max(self, db, db_engine, ws):
        """已有数据时按库内 max + 1 往后排。"""
        dt, _df = _make_table_with_increment(
            db, db_engine, ws, "AIPreviewMax", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        rec.create_row(db_engine, dt, {})
        rec.create_row(db_engine, dt, {})
        assert rec.preview_auto_increment_values(db_engine, dt) == {"编号": "PRJ-0003"}

    def test_soft_deleted_row_counted(self, db, db_engine, ws):
        """软删行仍占用编号，预览跳过它往后排。"""
        dt, _df = _make_table_with_increment(
            db, db_engine, ws, "AIPreviewSoftDel", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        row = rec.create_row(db_engine, dt, {"编号": "PRJ-0009"})
        rec.trash_row(db_engine, dt, row["id"])
        assert rec.preview_auto_increment_values(db_engine, dt) == {"编号": "PRJ-0010"}

    def test_skips_non_increment_and_trashed_fields(self, db, db_engine, ws):
        """未启用自动编号的字段与已删除字段不出现在预览结果里。"""
        dt, _df = _make_table_with_increment(
            db, db_engine, ws, "AIPreviewSkip", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        plain = DataField(table_id=dt.id, name="备注", field_type="text", order=1)
        plain.ensure_db_name()
        removed = DataField(
            table_id=dt.id,
            name="旧编号",
            field_type="text",
            order=2,
            trashed=True,
            config={"default_mode": "auto_increment", "increment_prefix": "OLD-"},
        )
        removed.ensure_db_name()
        db.add_all([plain, removed])
        db.commit()
        db.refresh(dt)

        assert rec.preview_auto_increment_values(db_engine, dt) == {"编号": "PRJ-0001"}

    def test_preview_matches_created_value(self, db, db_engine, ws):
        """预览值与随后建行实际生成值一致。"""
        dt, _df = _make_table_with_increment(
            db, db_engine, ws, "AIPreviewMatch", {"default_mode": "auto_increment", "increment_prefix": "PRJ-"}
        )
        rec.create_row(db_engine, dt, {})
        previewed = rec.preview_auto_increment_values(db_engine, dt)["编号"]
        assert rec.create_row(db_engine, dt, {})["编号"] == previewed


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

    def test_required_auto_increment_field_filled_on_create(self, db, db_engine, ws):
        """必填的自动编号字段不需要用户填值 —— 编号在校验前生成。"""
        dt, _df = self._fixture(db, db_engine, ws, "AIRequired")
        df = next(f for f in dt.fields if f.name == "编号")
        df.required = True
        db.commit()

        assert rec.create_row(db_engine, dt, {})["编号"] == "PRJ-0001"

    def test_required_auto_increment_field_filled_in_bulk(self, db, db_engine, ws):
        """bulk_create 同样先生成编号再校验必填。"""
        dt, _df = self._fixture(db, db_engine, ws, "AIBulkRequired")
        df = next(f for f in dt.fields if f.name == "编号")
        df.required = True
        db.commit()

        ids = rec.bulk_create(db_engine, dt, [{}, {}])
        rows, _total = rec.list_rows(db_engine, dt)
        values = {r["id"]: r["编号"] for r in rows}
        assert [values[i] for i in ids] == ["PRJ-0001", "PRJ-0002"]

    def test_required_plain_field_still_raises(self, db, db_engine, ws):
        """非自动编号的必填字段仍然拦截（必填校验没有被整体放宽）。"""
        dt = DataTable(workspace_id=ws.id, name="AIRequiredPlain")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        df = DataField(table_id=dt.id, name="标题", field_type="text", order=0, required=True)
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)
        ddl.create_table(db_engine, dt)

        with pytest.raises(ValueError, match="必填字段 标题 不能为空"):
            rec.create_row(db_engine, dt, {})


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


# ── 自动编号预览接口 ─────────────────────────────────


class TestAutoIncrementPreviewApi:
    @staticmethod
    def _make_table(client, auth_headers, name: str) -> tuple[int, int]:
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": f"ws_{name}"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": name})
        tid = t.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={
                "name": "编号",
                "field_type": "text",
                "order": 0,
                "config": {"default_mode": "auto_increment", "increment_prefix": "PRJ-"},
            },
        )
        assert r.status_code == 201, r.text
        return wid, tid

    def test_empty_table_preview(self, client, auth_headers):
        """空表预览返回起始编号。"""
        wid, tid = self._make_table(client, auth_headers, "t_ai_preview_empty")
        r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/records/auto-increment-preview", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json() == {"values": {"编号": "PRJ-0001"}}

    def test_preview_follows_existing_rows(self, client, auth_headers):
        """已有两行时预览为第三号；同时验证路由未被 /{record_id} 吞掉（否则 422）。"""
        wid, tid = self._make_table(client, auth_headers, "t_ai_preview_rows")
        for _ in range(2):
            created = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/records", headers=auth_headers, json={"values": {}}
            )
            assert created.status_code == 201, created.text

        r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/records/auto-increment-preview", headers=auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["values"]["编号"] == "PRJ-0003"

    def test_missing_table_returns_404(self, client, auth_headers):
        """表不存在 → 404。"""
        wid, _tid = self._make_table(client, auth_headers, "t_ai_preview_404")
        r = client.get(f"/api/v1/workspaces/{wid}/tables/999999/records/auto-increment-preview", headers=auth_headers)
        assert r.status_code == 404

    def test_non_member_forbidden(self, client, auth_headers):
        """非工作区成员 → 403。"""
        wid, tid = self._make_table(client, auth_headers, "t_ai_preview_403")
        reg = client.post(
            "/api/v1/accounts/auth/register",
            json={"username": "outsider_ai", "email": "outsider_ai@example.com", "password": "passw0rd"},
        )
        assert reg.status_code in (200, 201), reg.text
        login = client.post("/api/v1/accounts/auth/login", json={"login": "outsider_ai", "password": "passw0rd"})
        assert login.status_code == 200, login.text
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        r = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/records/auto-increment-preview", headers=other_headers)
        assert r.status_code == 403
