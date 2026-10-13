"""Coverage: routers/fields.py 分支覆盖."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from cndb.plugins.tables.models import DataField, DataTable


class TestLinkFieldValidation:
    def test_link_field_bad_config(self, client, auth_headers, db):
        """Link field with invalid config (bad target_table_id) -> 400."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_lf"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_lf"})
        tid = t.json()["id"]
        # Bad config: target_table_id does not exist
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={
                "name": "bad_link",
                "field_type": "link",
                "order": 0,
                "config": {"target_table_id": 99999, "multiple": True},
            },
        )
        assert r.status_code == 400

    def test_link_field_bad_config_format(self, client, auth_headers, db):
        """Link field with malformed config (missing required field) -> 400."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_lf2"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_lf2"})
        tid = t.json()["id"]
        # Missing target_table_id in config
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={
                "name": "bad_link2",
                "field_type": "link",
                "order": 0,
                "config": {"multiple": True},  # missing target_table_id
            },
        )
        assert r.status_code == 400

    def test_create_unknown_field_type(self, client, auth_headers, db):
        """Unknown field type -> 400."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_ut"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_ut"})
        tid = t.json()["id"]
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "f", "field_type": "nonexistent_type_xyz", "order": 0},
        )
        assert r.status_code == 400

    def test_delete_nonexistent_field(self, client, auth_headers, db):
        """Delete field that does not exist -> 404."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_df"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_df"})
        tid = t.json()["id"]
        r = client.delete(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields/99999",
            headers=auth_headers,
        )
        assert r.status_code == 404


# ── fields.py 剩余分支覆盖 ────────────────────────────


class TestFieldsRouterRemaining:
    def test_validate_field_config_unknown_type(self, db):
        """_validate_field_config 遇到未知 field_type -> 400 (覆盖 line 30)."""
        from cndb.plugins.tables.field_types import default_registry
        from cndb.plugins.tables.routers.fields import _validate_field_config

        with patch.object(default_registry, "get", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                _validate_field_config("ghost_type", {}, db)
            assert exc_info.value.status_code == 400
            assert "未知字段类型" in exc_info.value.detail

    def test_create_field_add_column_failure_rollback(self, client, auth_headers, db):
        """create_field 时 add_column 抛异常 -> 500 (覆盖 line 95-97)."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_acf"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_acf"})
        tid = t.json()["id"]

        # patch 目标是 fields 模块里已经 import 的 add_column
        with patch("cndb.plugins.tables.routers.fields.add_column", side_effect=RuntimeError("disk full")):
            r = client.post(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
                headers=auth_headers,
                json={"name": "bad_col", "field_type": "text", "order": 0},
            )
        assert r.status_code == 500
        assert "物理加列失败" in r.json()["detail"]

    def test_delete_field_drop_column_failure_rollback(self, client, auth_headers, db):
        """delete_field 时 drop_column 抛异常 -> 500 + trashed 回滚 (覆盖 line 161-164)."""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "ws_dcf"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": "t_dcf"})
        tid = t.json()["id"]
        # 先正常建个字段
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "rollback_col", "field_type": "text", "order": 0},
        )
        assert r.status_code == 201
        fid = r.json()["id"]

        # 删列失败时应回滚 trashed=True
        with patch("cndb.plugins.tables.routers.fields.drop_column", side_effect=RuntimeError("cannot drop")):
            r = client.delete(
                f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}",
                headers=auth_headers,
            )
        assert r.status_code == 500
        assert "物理删列失败" in r.json()["detail"]

        # 确认 trashed 已被回滚为 False
        fields = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields?include_trashed=true",
            headers=auth_headers,
        )
        target = next(f for f in fields.json() if f["id"] == fid)
        assert target["trashed"] is False


# ── 删除字段后同名字段可重建（软删除让位回归） ─────────


class TestFieldNameReuseAfterDelete:
    """回归：删除字段后新建同名字段曾报「字段名已存在」.

    根因：delete_field 软删除（trashed=True）后记录仍占用
    uniq_table_field_name 唯一约束，create_field 重名校验未排除 trashed，
    且列表接口过滤了 trashed —— 形成"看不见但建不了"。
    修复：create_field 校验排除 trashed；删除时软删除字段改名让位；
    存量占用名字的软删除字段在建同名字段时兜底让位。
    """

    def _setup(self, client, auth_headers, tag: str) -> tuple[int, int]:
        """创建工作区 + 表，返回 (wid, tid)。"""
        ws = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": f"ws_fnr_{tag}"})
        wid = ws.json()["id"]
        t = client.post(f"/api/v1/workspaces/{wid}/tables", headers=auth_headers, json={"name": f"t_fnr_{tag}"})
        tid = t.json()["id"]
        return wid, tid

    def _add_field(self, client, auth_headers, wid: int, tid: int, name: str) -> dict:
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": name, "field_type": "text", "order": 0},
        )
        return r

    def test_create_same_name_after_delete_ok(self, client, auth_headers, db):
        """删除字段后新建同名字段 → 201（核心回归）."""
        wid, tid = self._setup(client, auth_headers, "core")
        r = self._add_field(client, auth_headers, wid, tid, "价格")
        assert r.status_code == 201
        fid = r.json()["id"]

        r = client.delete(f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}", headers=auth_headers)
        assert r.status_code == 204

        # 字段列表中已不可见
        fields = client.get(f"/api/v1/workspaces/{wid}/tables/{tid}/fields", headers=auth_headers).json()
        assert all(f["id"] != fid for f in fields)

        # 同名重建成功
        r = self._add_field(client, auth_headers, wid, tid, "价格")
        assert r.status_code == 201, r.text

    def test_create_conflict_with_active_field_still_400(self, client, auth_headers, db):
        """与未删除字段同名仍拒绝 → 400（校验排除 trashed 不放行活字段冲突）."""
        wid, tid = self._setup(client, auth_headers, "active")
        r = self._add_field(client, auth_headers, wid, tid, "数量")
        assert r.status_code == 201

        r = self._add_field(client, auth_headers, wid, tid, "数量")
        assert r.status_code == 400
        assert "字段名已存在" in r.json()["detail"]

    def test_legacy_trashed_name_released_on_create(self, client, auth_headers, db):
        """存量软删除字段占用名字时，新建同名字段自动让位成功并改名旧记录."""
        wid, tid = self._setup(client, auth_headers, "legacy")
        r = self._add_field(client, auth_headers, wid, tid, "备注")
        assert r.status_code == 201
        old_fid = r.json()["id"]

        # 模拟历史脏数据：软删除但未让位改名（修复前的删除行为产物）
        df = db.get(DataField, old_fid)
        df.trashed = True
        db.commit()

        r = self._add_field(client, auth_headers, wid, tid, "备注")
        assert r.status_code == 201, r.text

        # 旧软删除记录被让位改名，新字段占用原名
        fields = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields?include_trashed=true", headers=auth_headers
        ).json()
        old = next(f for f in fields if f["id"] == old_fid)
        assert old["trashed"] is True
        assert "已删" in old["name"]
        new = next(f for f in fields if f["name"] == "备注")
        assert new["id"] != old_fid

    def test_delete_failure_rollback_restores_name(self, client, auth_headers, db, monkeypatch):
        """物理删列失败 → 500 且 metadata 回滚含让位名（trashed=False + 原名恢复）."""

        def _boom(*args, **kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr("cndb.plugins.tables.routers.fields.drop_column", _boom)

        wid, tid = self._setup(client, auth_headers, "rollback")
        r = self._add_field(client, auth_headers, wid, tid, "附件")
        assert r.status_code == 201
        fid = r.json()["id"]

        r = client.delete(f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}", headers=auth_headers)
        assert r.status_code == 500
        assert "物理删列失败" in r.json()["detail"]

        fields = client.get(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields?include_trashed=true", headers=auth_headers
        ).json()
        target = next(f for f in fields if f["id"] == fid)
        assert target["trashed"] is False
        assert target["name"] == "附件"

    def test_repeated_delete_recreate_cycle(self, client, auth_headers, db):
        """删→建同名→再删→再建 循环成功，多次删除的让位名互不冲突."""
        wid, tid = self._setup(client, auth_headers, "cycle")
        for _ in range(3):
            r = self._add_field(client, auth_headers, wid, tid, "状态")
            assert r.status_code == 201, r.text
            fid = r.json()["id"]
            r = client.delete(f"/api/v1/workspaces/{wid}/tables/{tid}/fields/{fid}", headers=auth_headers)
            assert r.status_code == 204

        # 三条软删除记录让位名互不重复，且不含未让位的原名
        trashed = (
            db.query(DataField)
            .filter(DataField.table_id == tid, DataField.trashed == True)  # noqa: E712
            .all()
        )
        assert len(trashed) == 3
        names = [f.name for f in trashed]
        assert len(set(names)) == 3
        assert all("状态（已删）" in n for n in names)

        # 名字仍可复用
        r = self._add_field(client, auth_headers, wid, tid, "状态")
        assert r.status_code == 201, r.text


# ── rename_trashed_field_aside 单元测试 ────────────────


class TestRenameTrashedFieldAside:
    def test_suffix_with_existing_conflicts_numbered(self, db):
        """让位名与表内已有字段冲突时递增序号，返回首个不冲突名."""
        from cndb.plugins.tables.services.fields.field_ops import rename_trashed_field_aside

        dt = DataTable(workspace_id=1, name="t_rename_aside")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()

        # 占用「价格（已删）」与「价格（已删） 2」两个名字
        for n in ("价格", "价格（已删）", "价格（已删） 2"):
            f = DataField(table_id=dt.id, name=n, field_type="text")
            f.ensure_db_name()
            db.add(f)
        db.commit()

        trashed = db.query(DataField).filter(DataField.name == "价格").one()
        new_name = rename_trashed_field_aside(db, trashed)
        assert new_name == "价格（已删） 3"

    def test_self_name_excluded_from_conflicts(self, db):
        """字段自身名字不参与判重（软删除原名不阻塞让位名生成）."""
        from cndb.plugins.tables.services.fields.field_ops import rename_trashed_field_aside

        dt = DataTable(workspace_id=1, name="t_rename_self")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()
        f = DataField(table_id=dt.id, name="备注", field_type="text")
        f.ensure_db_name()
        db.add(f)
        db.commit()

        assert rename_trashed_field_aside(db, f) == "备注（已删）"
