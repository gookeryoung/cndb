"""结合 seed 数据的工作区备份全流程单元验证.

使用 cli/seed.py 的 _seed_sales_tables 构造真实业务数据形态
（部门表 4 行 + 员工表 5 行，字段覆盖 text/link/date/number/select），
验证导出 → 导入后工作区配置、数据表、数据行、视图全量还原；
另覆盖 seed 视图配置纯函数（views.json 解析与字段校验）。
"""

from __future__ import annotations

import json

from cndb.cli.seed import _get_workspace_view_configs, _seed_sales_tables, _validate_view_fields
from cndb.plugins.accounts.models import User
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember
from cndb.plugins.workspaces.routers.workspaces import _coerce_row_value_types


def _make_sales_workspace(db, owner: User) -> Workspace:
    """按 seed 的方式创建"某企业销售管理"工作区并绑定 owner 成员."""
    ws = Workspace(name="某企业销售管理", description="seed 验证")
    db.add(ws)
    db.commit()
    db.refresh(ws)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"))
    db.commit()
    return ws


# 部门表 4 行的期望值（与 seed._seed_sales_tables 保持一致）
DEPT_ROWS = {
    "技术部": "张三",
    "市场部": "李四",
    "人事部": "王五",
    "财务部": "赵六",
}

# 员工表 5 行的期望值（姓名 → (入职日期, 薪资, 是否在职)）
EMP_ROWS = {
    "张三": ("2023-01-15", 15000, "是"),
    "李四": ("2022-06-01", 12000, "是"),
    "王五": ("2024-03-20", 10000, "是"),
    "赵六": ("2021-11-10", 13000, "否"),
    "钱七": ("2023-08-05", 18000, "是"),
}


class TestSeedBackupRoundtrip:
    """seed 业务数据（含 link 字段）经备份导出 → 导入的全量还原验证."""

    def test_seed_sales_backup_roundtrip_restores_all(self, client, auth_headers, db, db_engine):
        """导出 seed 工作区 → 从备份创建新工作区 → 逐行逐字段比对."""
        from cndb.plugins.tables.models import DataTable

        owner = db.query(User).filter(User.username == "testuser").first()
        ws = _make_sales_workspace(db, owner)
        table_count, tables_map = _seed_sales_tables(db, db_engine, ws, owner_id=owner.id)
        assert table_count == 2
        assert set(tables_map) == {"部门表", "员工表"}

        headers = auth_headers
        r_export = client.get(f"/api/v1/workspaces/{ws.id}/export", headers=headers)
        assert r_export.status_code == 200
        backup = r_export.json()
        assert backup["version"] == "3"
        tables = {t["name"]: t for t in backup["tables"]}
        assert set(tables) == {"部门表", "员工表"}

        # 导出内容：员工表字段类型齐全（含 link），select config 带选项
        emp_fields = {f["name"]: f for f in tables["员工表"]["fields"]}
        assert set(emp_fields) == {"姓名", "部门", "入职日期", "薪资", "是否在职"}
        assert emp_fields["部门"]["field_type"] == "link"
        assert emp_fields["是否在职"]["config"] == {"options": ["是", "否"]}
        assert len(tables["部门表"]["rows"]) == 4
        assert len(tables["员工表"]["rows"]) == 5

        # 从备份创建全新工作区
        r_restore = client.post("/api/v1/workspaces/import", json={"json_data": backup}, headers=headers)
        assert r_restore.status_code == 201, r_restore.text
        body = r_restore.json()
        assert body["errors"] == [], f"导入报错: {body['errors']}"
        assert body["imported_tables"] == 2
        assert body["imported_rows"] == 9
        restored = body["workspace"]
        assert restored["name"] == "某企业销售管理"

        # 恢复后的工作区再导出，逐值比对
        r_verify = client.get(f"/api/v1/workspaces/{restored['id']}/export", headers=headers)
        assert r_verify.status_code == 200
        dst = {t["name"]: t for t in r_verify.json()["tables"]}
        assert set(dst) == {"部门表", "员工表"}

        # 部门表 4 行全还原
        dept_rows = {r["部门名称"]: r["负责人"] for r in dst["部门表"]["rows"]}
        assert dept_rows == DEPT_ROWS

        # 员工表 5 行逐值还原（link 字段值存关联表，主表行为不应受其拖累）
        emp_rows = {r["姓名"]: r for r in dst["员工表"]["rows"]}
        for name, (hired, salary, active) in EMP_ROWS.items():
            assert emp_rows[name]["入职日期"] == hired
            assert emp_rows[name]["薪资"] == salary
            assert emp_rows[name]["是否在职"] == active

        # 字段定义逐项还原（含 select 选项与 link 类型）
        dst_emp_fields = {f["name"]: f for f in dst["员工表"]["fields"]}
        assert dst_emp_fields == emp_fields

        # 数据表对象也应存在（物理表 + 元数据）
        restored_tables = db.query(DataTable).filter(DataTable.workspace_id == restored["id"]).all()
        assert {t.name for t in restored_tables} == {"部门表", "员工表"}

    def test_seed_backup_import_into_existing_ws_skips_same_name(self, client, auth_headers, db, db_engine):
        """seed 备份导入到已有同结构工作区：同名表全部跳过且原数据不受影响."""
        owner = db.query(User).filter(User.username == "testuser").first()
        ws = _make_sales_workspace(db, owner)
        _seed_sales_tables(db, db_engine, ws, owner_id=owner.id)

        headers = auth_headers
        r_export = client.get(f"/api/v1/workspaces/{ws.id}/export", headers=headers)
        backup = r_export.json()

        r_import = client.post(f"/api/v1/workspaces/{ws.id}/import", json={"json_data": backup}, headers=headers)
        assert r_import.status_code == 200, r_import.text
        data = r_import.json()
        assert data["imported_tables"] == 0
        assert data["imported_rows"] == 0
        assert data["errors"] == []

        # 原数据未被破坏：再导出行数不变
        r_verify = client.get(f"/api/v1/workspaces/{ws.id}/export", headers=headers)
        tables = {t["name"]: t for t in r_verify.json()["tables"]}
        assert len(tables["部门表"]["rows"]) == 4
        assert len(tables["员工表"]["rows"]) == 5


class TestSeedViewHelpers:
    """seed 视图配置纯函数的单元验证."""

    def test_get_workspace_view_configs_strips_prefix_and_bom(self, tmp_path):
        """views.json 以 utf-8-sig（BOM）读取，工作区名剥离「工作区-」前缀."""
        folder = tmp_path / "工作区-某企业销售管理"
        folder.mkdir()
        views = {"员工表": [{"name": "在职员工", "view_type": "grid", "filters": []}]}
        (folder / "views.json").write_text(json.dumps(views, ensure_ascii=False), encoding="utf-8-sig")

        # 无 views.json 的文件夹应被忽略
        (tmp_path / "空工作区").mkdir()

        result = _get_workspace_view_configs(tmp_path)
        assert result == {"某企业销售管理": views}

    def test_validate_view_fields_accepts_valid_and_rejects_missing(self):
        valid = {"姓名", "薪资"}

        assert _validate_view_fields({"name": "v", "filters": [{"field_name": "薪资"}]}, valid, "ws", "t") is True
        # filter 引用不存在字段 → 拒绝
        assert _validate_view_fields({"name": "v", "filters": [{"field_name": "缺失"}]}, valid, "ws", "t") is False
        # sorting 引用不存在字段 → 拒绝
        assert _validate_view_fields({"name": "v", "sortings": [{"field_name": "缺失"}]}, valid, "ws", "t") is False
        # view_options 字段引用不存在 → 拒绝
        assert _validate_view_fields({"name": "v", "view_options": {"group_field": "缺失"}}, valid, "ws", "t") is False


class TestCoerceRowValueTypes:
    """备份行值按反射列类型反序列化的单元验证."""

    def _make_sa_table(self):
        from sqlalchemy import Column, Date, DateTime, Integer, MetaData, Table

        metadata = MetaData()
        return Table(
            "t",
            metadata,
            Column("id", Integer, primary_key=True),
            Column("d", Date),
            Column("ts", DateTime),
        )

    def test_normalizes_iso_strings_and_handles_interleaved_formats(self):
        import datetime

        sa = self._make_sa_table()
        rows = [
            {"d": "2023-01-15", "ts": "2024-03-20T08:30:00"},
            {"d": "2024-06-01T09:00:00", "ts": "2024-06-01"},  # 交错：Date 列收 datetime 串、DateTime 列收纯日期
            {"d": None, "ts": None},
        ]
        _coerce_row_value_types(sa, rows)
        assert rows[0]["d"] == datetime.date(2023, 1, 15)
        assert rows[0]["ts"] == datetime.datetime(2024, 3, 20, 8, 30)
        assert rows[1]["d"] == datetime.date(2024, 6, 1)
        assert rows[1]["ts"] == datetime.datetime(2024, 6, 1, 0, 0)
        assert rows[2]["d"] is None and rows[2]["ts"] is None

    def test_invalid_values_kept_as_is(self):
        sa = self._make_sa_table()
        rows = [{"d": "not-a-date", "ts": "garbage"}]
        _coerce_row_value_types(sa, rows)
        assert rows[0] == {"d": "not-a-date", "ts": "garbage"}

    def test_non_string_values_untouched(self):
        import datetime

        sa = self._make_sa_table()
        rows = [{"d": datetime.date(2023, 1, 1), "ts": 12345}]
        _coerce_row_value_types(sa, rows)
        assert rows[0]["d"] == datetime.date(2023, 1, 1)
        assert rows[0]["ts"] == 12345
