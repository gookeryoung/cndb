"""tables / workspaces / bulk 三个路由层的极端情况覆盖率补全测试.

覆盖范围（对应 coverage 报告缺行）：
- tables.py：物理表 COUNT 异常、表成员 my_access、current_user=None、
  import_fields 静默跳过与回滚、copy_table 各模式校验/数据复制/回滚、
  move_table 清空 owner。
- workspaces.py：详情统计 total_rows（含 suppress 异常）、导出读取数据行
  （含 trashed_at 列过滤）、导入同名表跳过、DDL 失败 400、数据行导入
  成功/失败告警、整体失败回滚 400。
- bulk.py：bulk 前后置 options 辅助函数异常吞掉、tsv 格式 400、
  analyze 的 dropped_columns 解析、confirm 的 match_keys/dropped_columns
  覆盖解析、reanalyze 各校验分支。
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, DataView, ImportTask, TableMember
from cndb.plugins.tables.routers.tables import _fill_table_stats
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.fields import field_ops

# ── 复用基建的小工具 ────────────────────────────────────


def _login(client, username: str, password: str = "passw0rd") -> dict:
    """登录获取认证头."""
    r = client.post("/api/v1/accounts/auth/login", json={"login": username, "password": password})
    assert r.status_code == 200, f"登录失败: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _mk_table(db, db_engine, ws_id: int, owner_id: int | None, name: str):
    """真实构造一张带 2 字段（姓名/年龄）和 2 行数据的表，返回 (dt, fields)."""
    dt = DataTable(workspace_id=ws_id, owner_id=owner_id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    f_name = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    f_name.ensure_db_name()
    f_age = DataField(table_id=dt.id, name="年龄", field_type="number", order=1)
    f_age.ensure_db_name()
    db.add_all([f_name, f_age])
    db.commit()
    db.refresh(dt)
    ddl.create_table(db_engine, dt)
    rec.create_row(db_engine, dt, {"姓名": "张三", "年龄": 28})
    rec.create_row(db_engine, dt, {"姓名": "李四", "年龄": 35})
    return dt, [f_name, f_age]


def _mk_task(db, dt: DataTable, status: str = "pending_confirm") -> ImportTask:
    """直接构造一条指定状态的导入任务（confirm/reanalyze 路由用）."""
    task = ImportTask(table_id=dt.id, filename="edge.csv", format="csv", status=status)
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _add_ws_member(client, headers: dict, ws_id: int, username: str, role: str) -> None:
    """通过成员接口把用户加入工作区."""
    r = client.post(
        f"/api/v1/workspaces/{ws_id}/members",
        json={"username": username, "role": role},
        headers=headers,
    )
    assert r.status_code in (200, 201), f"加成员失败: {r.text}"


# ── fixtures ───────────────────────────────────────────


@pytest.fixture
def owner(db):
    u = User(username="edge_owner", nickname="EdgeOwner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def peer(db):
    u = User(username="edge_peer", nickname="EdgePeer")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner(client, owner):
    return _login(client, owner.username)


@pytest.fixture
def auth_peer(client, peer):
    return _login(client, peer.username)


@pytest.fixture
def ws_id(client, auth_owner) -> int:
    r = client.post("/api/v1/workspaces", json={"name": "EdgeWS"}, headers=auth_owner)
    assert r.status_code == 201, r.text
    return r.json()["id"]


@pytest.fixture
def src_table(db, db_engine, ws_id, owner):
    """owner 名下带数据的源表."""
    return _mk_table(db, db_engine, ws_id, owner.id, "Edge源表")


# ── tables.py ──────────────────────────────────────────


class TestTablesRouterEdge:
    def test_fill_table_stats_without_current_user(self, db, src_table):
        """current_user=None 时 my_access 应为 None（内部调用路径）."""
        dt, _ = src_table
        resp = _fill_table_stats(db, dt, current_user=None)
        assert resp.my_access is None

    def test_list_tables_member_my_access(self, client, db, ws_id, auth_owner, auth_peer, peer, src_table):
        """表成员视角：列表接口 my_access 应返回成员角色（read/write）."""
        dt, _ = src_table
        _add_ws_member(client, auth_owner, ws_id, peer.username, "viewer")
        db.add(TableMember(table_id=dt.id, user_id=peer.id, role="read"))
        db.commit()
        r = client.get(f"/api/v1/workspaces/{ws_id}/tables", headers=auth_peer)
        assert r.status_code == 200
        item = next(t for t in r.json() if t["id"] == dt.id)
        assert item["my_access"] == "read"

    def test_get_table_record_count_none_when_physical_missing(self, client, db_engine, ws_id, auth_owner, src_table):
        """物理表被删后 COUNT 异常 → record_count=None 而非报错."""
        dt, _ = src_table
        ddl.drop_table(db_engine, dt.db_table_name)
        r = client.get(f"/api/v1/workspaces/{ws_id}/tables/{dt.id}", headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["record_count"] is None

    def test_create_table_import_missing_source_silent(self, client, ws_id, auth_owner):
        """import_from_table_id 指向不存在的表 → 静默跳过，建表不受影响."""
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables",
            json={"name": "孤立新表", "import_from_table_id": 99999},
            headers=auth_owner,
        )
        assert r.status_code == 201, r.text
        assert r.json()["name"] == "孤立新表"

    def test_create_table_import_field_ids_and_empty_selection(self, client, db, ws_id, auth_owner, src_table):
        """按 field_ids 引入源表字段；未指定任何引入选择时静默跳过."""
        dt, fields = src_table
        base = f"/api/v1/workspaces/{ws_id}/tables"
        # 指定 field_ids → 只引入一个字段
        r1 = client.post(
            base,
            json={"name": "按列引入表", "import_from_table_id": dt.id, "import_field_ids": [fields[0].id]},
            headers=auth_owner,
        )
        assert r1.status_code == 201, r1.text
        dst1 = db.get(DataTable, r1.json()["id"])
        assert len(dst1.fields) == 1
        # 只传 import_from_table_id、不选字段 → 不导入，表本身照常创建
        r2 = client.post(
            base,
            json={"name": "空引入表", "import_from_table_id": dt.id},
            headers=auth_owner,
        )
        assert r2.status_code == 201, r2.text
        dst2 = db.get(DataTable, r2.json()["id"])
        assert len(dst2.fields) == 0

    def test_create_table_import_clone_fail_rollback(self, client, db, monkeypatch, ws_id, auth_owner, src_table):
        """字段克隆失败 → 回滚删除新表 + DROP 物理表后原样抛出."""
        dt, _ = src_table

        def _boom(*args, **kwargs):
            raise RuntimeError("clone boom")

        monkeypatch.setattr(field_ops, "clone_fields_between_tables", _boom)
        with pytest.raises(RuntimeError, match="clone boom"):
            client.post(
                f"/api/v1/workspaces/{ws_id}/tables",
                json={"name": "回滚表", "import_from_table_id": dt.id, "import_all_fields": True},
                headers=auth_owner,
            )
        # 新表已回滚，工作区只剩源表
        assert db.query(DataTable).filter(DataTable.workspace_id == ws_id).count() == 1

    def test_copy_table_invalid_mode_400(self, client, ws_id, auth_owner, src_table):
        """无效 mode → 400."""
        dt, _ = src_table
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/copy",
            params={"mode": "bogus"},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "无效的 mode" in r.json()["detail"]

    def test_copy_table_view_mode_requires_view_id(self, client, ws_id, auth_owner, src_table):
        """mode=view 缺 view_id → 400."""
        dt, _ = src_table
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/copy",
            params={"mode": "view"},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "view_id" in r.json()["detail"]

    def test_copy_table_view_not_belong_404(self, client, ws_id, auth_owner, src_table):
        """mode=view 传不属于该表的 view_id → 404."""
        dt, _ = src_table
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/copy",
            params={"mode": "view", "view_id": 99999},
            headers=auth_owner,
        )
        assert r.status_code == 404

    def test_copy_table_view_mode_copies_filtered_rows(self, client, db, ws_id, auth_owner, src_table):
        """mode=view 按视图过滤条件复制数据行."""
        dt, _ = src_table
        dv = DataView(
            table_id=dt.id,
            name="大龄视图",
            view_type="grid",
            filter_type="AND",
            filters=[{"field_name": "年龄", "op": ">=", "value": 30}],
        )
        db.add(dv)
        db.commit()
        db.refresh(dv)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/copy",
            params={"mode": "view", "view_id": dv.id},
            headers=auth_owner,
        )
        assert r.status_code == 201, r.text
        dst_id = r.json()["id"]
        detail = client.get(f"/api/v1/workspaces/{ws_id}/tables/{dst_id}", headers=auth_owner)
        assert detail.status_code == 200
        assert detail.json()["record_count"] == 1  # 只有 35 岁的李四

    def test_copy_table_all_mode_skips_dropped_column(self, client, db_engine, ws_id, auth_owner, src_table):
        """mode=all 复制时，行数据缺失某字段 key → 跳过该字段继续复制."""
        dt, fields = src_table
        ddl.drop_column(db_engine, dt, fields[1])  # 物理表删掉「年龄」列，行 dict 不再含该 key
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/copy",
            params={"mode": "all"},
            headers=auth_owner,
        )
        assert r.status_code == 201, r.text
        dst_id = r.json()["id"]
        detail = client.get(f"/api/v1/workspaces/{ws_id}/tables/{dst_id}", headers=auth_owner)
        assert detail.json()["record_count"] == 2

    def test_copy_table_clone_fail_rollback_500(self, client, db, monkeypatch, ws_id, auth_owner, src_table):
        """复制时字段克隆失败 → 500 且新表已回滚."""
        dt, _ = src_table

        def _boom(*args, **kwargs):
            raise RuntimeError("copy clone boom")

        monkeypatch.setattr(field_ops, "clone_fields_between_tables", _boom)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/copy",
            params={"mode": "structure"},
            headers=auth_owner,
        )
        assert r.status_code == 500
        assert "字段克隆失败" in r.json()["detail"]
        assert db.query(DataTable).filter(DataTable.workspace_id == ws_id).count() == 1

    def test_move_table_clears_owner_when_not_target_member(self, client, db, auth_owner, auth_peer, ws_id, src_table):
        """owner 不在目标工作区 → 移动后 owner_id 清空."""
        dt, _ = src_table
        # ws2 由 peer 创建（peer 是 ws2 的 owner，而表 owner 不是 ws2 成员）
        r_ws2 = client.post("/api/v1/workspaces", json={"name": "EdgeWS2"}, headers=auth_peer)
        ws2 = r_ws2.json()["id"]
        # 操作人 peer 在源工作区是 admin（可改表结构）
        _add_ws_member(client, auth_owner, ws_id, "edge_peer", "admin")
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/move",
            params={"target_workspace_id": ws2},
            headers=auth_peer,
        )
        assert r.status_code == 200, r.text
        # owner（原工作区 owner）不是目标工作区成员 → owner_id 被清空
        db.expire_all()
        assert db.get(DataTable, dt.id).owner_id is None


# ── workspaces.py ──────────────────────────────────────


class TestWorkspacesRouterEdge:
    def test_workspace_detail_total_rows_and_suppress(self, client, db, ws_id, auth_owner, src_table):
        """详情统计 total_rows：正常累加 + 物理表缺失时 suppress 跳过."""
        _dt, _ = src_table
        # 幻影表：只有元数据没有物理表 → autoload 异常被 suppress
        phantom = DataTable(workspace_id=ws_id, name="幻影表")
        phantom.ensure_db_name()
        db.add(phantom)
        db.commit()
        r = client.get(f"/api/v1/workspaces/{ws_id}", headers=auth_owner)
        assert r.status_code == 200
        body = r.json()
        assert body["table_count"] == 2
        assert body["total_rows"] == 2

    def test_export_workspace_rows_reads_data(self, client, db, db_engine, ws_id, auth_owner, src_table):
        """导出读取物理数据行：默认无 trashed_at 列走全量分支，补列后走过滤分支.

        行键为业务字段名（物理列名跨库恢复时会重新生成，不能作为导出行键）.
        """
        dt, _ = src_table
        r1 = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=auth_owner)
        assert r1.status_code == 200
        rows1 = r1.json()["tables"][0]["rows"]
        assert len(rows1) == 2
        assert {row["姓名"] for row in rows1} == {"张三", "李四"}

        # 物理表补一列 trashed_at（模拟列漂移），其中一行打上标记
        db.execute(text(f'ALTER TABLE "{dt.db_table_name}" ADD COLUMN "trashed_at" TEXT'))
        row3 = rec.create_row(db_engine, dt, {"姓名": "王五", "年龄": 50})
        db.execute(
            text(f'UPDATE "{dt.db_table_name}" SET "trashed_at" = :v WHERE id = :i'),
            {"v": "2020-01-01 00:00:00", "i": row3["id"]},
        )
        db.commit()
        r2 = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=auth_owner)
        assert r2.status_code == 200
        rows2 = r2.json()["tables"][0]["rows"]
        # trashed_at 非空的行被过滤掉（王五不出现），且行键只含业务字段名
        assert len(rows2) == 2
        assert all("王五" not in row.values() for row in rows2)
        assert all(set(row) == {"姓名", "年龄"} for row in rows2)

    def test_import_workspace_skips_same_name(self, client, db, ws_id, auth_owner):
        """导入时与现存表同名 → 跳过."""
        existing = DataTable(workspace_id=ws_id, name="同名表")
        existing.ensure_db_name()
        db.add(existing)
        db.commit()
        payload = {
            "version": "2",
            "tables": [{"name": "同名表", "description": "", "fields": [], "rows": [], "views": []}],
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json={"json_data": payload}, headers=auth_owner)
        assert r.status_code == 200
        assert r.json()["imported_tables"] == 0

    def test_import_workspace_ddl_fail_400(self, client, monkeypatch, ws_id, auth_owner):
        """DDL 创建物理表失败 → 回滚并返回 400."""
        from cndb.plugins.tables.services.core import ddl as ddl_mod

        def _boom(engine, table):
            raise RuntimeError("ddl boom")

        monkeypatch.setattr(ddl_mod, "create_table", _boom)
        payload = {
            "version": "2",
            "tables": [
                {
                    "name": "炸裂表",
                    "fields": [{"name": "姓名", "field_type": "text", "order": 0}],
                    "rows": [],
                    "views": [],
                }
            ],
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json={"json_data": payload}, headers=auth_owner)
        assert r.status_code == 400
        assert "创建表" in r.json()["detail"]

    def test_import_workspace_rows_roundtrip(self, client, db, monkeypatch, ws_id, auth_owner):
        """导入插入数据行（行 key 与字段 db_column_name 匹配时走真实 INSERT）.

        导入时字段物理列名由 generate_db_column_name 随机生成，固定为确定性
        序列后，payload 行即可按列名命中，覆盖 db.execute(insert) 分支.
        """
        from cndb.plugins.tables import models as tables_models

        counter = {"n": 0}

        def _deterministic_column() -> str:
            counter["n"] += 1
            return f"field_edge{counter['n']:06d}"

        monkeypatch.setattr(tables_models, "generate_db_column_name", _deterministic_column)
        payload = {
            "version": "2",
            "tables": [
                {
                    "name": "回填表",
                    "fields": [
                        {"name": "姓名", "field_type": "text", "order": 0},
                        {"name": "年龄", "field_type": "number", "order": 1},
                    ],
                    "rows": [
                        {"field_edge000001": "张三", "field_edge000002": 28},
                        {"field_edge000001": "李四", "field_edge000002": 35},
                    ],
                    "views": [],
                }
            ],
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json={"json_data": payload}, headers=auth_owner)
        assert r.status_code == 200, r.text
        assert r.json()["imported_rows"] == 2

    def test_import_workspace_rows_fail_warning(self, client, db, monkeypatch, ws_id, auth_owner):
        """数据行插入阶段 autoload 物理表失败 → 仅告警不中断，表结构仍导入."""
        from cndb.plugins.tables.services.core import ddl as ddl_mod

        monkeypatch.setattr(ddl_mod, "create_table", lambda engine, table: None)  # 不建物理表
        payload = {
            "version": "2",
            "tables": [
                {
                    "name": "无物理表",
                    "fields": [{"name": "姓名", "field_type": "text", "order": 0}],
                    "rows": [{"姓名": "张三"}],
                    "views": [],
                }
            ],
        }
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json={"json_data": payload}, headers=auth_owner)
        assert r.status_code == 200, r.text
        assert r.json()["imported_tables"] == 1
        assert r.json()["imported_rows"] == 0

    def test_import_workspace_bad_table_entry_400(self, client, ws_id, auth_owner):
        """tables 里混入非 dict 条目 → 整体回滚返回 400."""
        payload = {"version": "2", "tables": ["not-a-dict"]}
        r = client.post(f"/api/v1/workspaces/{ws_id}/import", json={"json_data": payload}, headers=auth_owner)
        assert r.status_code == 400
        assert "导入失败" in r.json()["detail"]

    def test_workspace_backup_roundtrip_preserves_rows(self, client, ws_id, auth_owner, src_table):
        """导出 → 导入到新工作区，数据行不丢且值一致（v3 行键为业务字段名）.

        回归背景：旧版导出行键为随机物理列名（field_xxx），导入时字段重新
        随机生成列名导致键永远匹配不上，恢复后数据行全部丢失。
        """
        r_export = client.get(f"/api/v1/workspaces/{ws_id}/export", headers=auth_owner)
        assert r_export.status_code == 200
        backup = r_export.json()
        assert backup["version"] == "4"

        # 建一个全新工作区接收导入，避免同名表被跳过
        r_new_ws = client.post("/api/v1/workspaces", json={"name": "恢复WS"}, headers=auth_owner)
        assert r_new_ws.status_code == 201
        new_ws_id = r_new_ws.json()["id"]

        r_import = client.post(
            f"/api/v1/workspaces/{new_ws_id}/import",
            json={"json_data": backup},
            headers=auth_owner,
        )
        assert r_import.status_code == 200, r_import.text
        assert r_import.json()["imported_tables"] == 1
        assert r_import.json()["imported_rows"] == 2

        # 再导出恢复后的工作区，验证行值一致
        r_verify = client.get(f"/api/v1/workspaces/{new_ws_id}/export", headers=auth_owner)
        assert r_verify.status_code == 200
        restored = r_verify.json()["tables"][0]["rows"]
        assert {row["姓名"]: row["年龄"] for row in restored} == {"张三": 28, "李四": 35}


# ── bulk.py ────────────────────────────────────────────


class TestBulkRouterEdge:
    def test_bulk_create_helpers_crash_swallowed(self, client, monkeypatch, ws_id, auth_owner, src_table):
        """建行前后置 options 辅助函数抛异常 → 吞掉，批量建行照常成功."""
        dt, _ = src_table

        def _boom(*args, **kwargs):
            raise RuntimeError("options boom")

        monkeypatch.setattr(field_ops, "prefill_select_options_from_rows", _boom)
        monkeypatch.setattr(field_ops, "sync_select_options_from_table", _boom)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/records/bulk-create",
            json={"rows": [{"values": {"姓名": "甲", "年龄": 1}}]},
            headers=auth_owner,
        )
        assert r.status_code == 201, r.text
        assert r.json()["created"] == 1

    def test_bulk_update_helpers_crash_swallowed(self, client, db_engine, monkeypatch, ws_id, auth_owner, src_table):
        """改行前后置 options 辅助函数抛异常 → 吞掉，批量改行照常成功."""
        dt, _ = src_table
        rows, _total = rec.list_rows(db_engine, dt)
        row_id = rows[0]["id"]

        def _boom(*args, **kwargs):
            raise RuntimeError("options boom")

        monkeypatch.setattr(field_ops, "prefill_select_options_from_rows", _boom)
        monkeypatch.setattr(field_ops, "sync_select_options_from_table", _boom)
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/records/bulk-update",
            json={"row_ids": [row_id], "values": {"年龄": 99}},
            headers=auth_owner,
        )
        assert r.status_code == 200, r.text
        assert r.json()["updated"] == 1

    def test_import_table_tsv_unsupported_400(self, client, ws_id, auth_owner, src_table):
        """上传 .tsv → 格式推断成功但导入路由不支持 → 400."""
        dt, _ = src_table
        r = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/import",
            files={"file": ("data.tsv", b"a\tb\n1\t2\n", "text/tab-separated-values")},
            headers=auth_owner,
        )
        assert r.status_code == 400
        assert "不支持的格式" in r.json()["detail"]

    def test_analyze_dropped_columns_parsing(self, client, ws_id, auth_owner, src_table):
        """analyze 的 dropped_columns：JSON 数组与逗号分隔两种形式都能解析."""
        dt, _ = src_table
        csv_content = "a,b\n1,2\n"
        files = {"file": ("t.csv", csv_content.encode("utf-8"), "text/csv")}
        r1 = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/import/analyze",
            files=files,
            data={"dropped_columns": '["a","b"]'},
            headers=auth_owner,
        )
        assert r1.status_code == 200, r1.text
        assert r1.json()["dropped_columns"] == ["a", "b"]
        r2 = client.post(
            f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/import/analyze",
            files=files,
            data={"dropped_columns": "a, b"},  # 非法 JSON → 回退逗号分隔
            headers=auth_owner,
        )
        assert r2.status_code == 200, r2.text
        assert r2.json()["dropped_columns"] == ["a", "b"]

    def test_confirm_overrides_match_keys_and_dropped_columns(
        self, client, db, monkeypatch, ws_id, auth_owner, src_table
    ):
        """confirm 阶段覆盖 match_keys / dropped_columns 的三种解析形态.

        置空后台执行（空内容任务会被执行线程清理，断言拿不到稳定值），
        本用例只关心参数解析分支.
        """
        monkeypatch.setattr(
            "cndb.plugins.tables.routers.bulk.run_task_in_background",
            lambda *args, **kwargs: None,
        )
        dt, _ = src_table
        base = f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/import"

        # match_keys：JSON 解析成功但不是 list → 回退逗号分隔（原始串含引号）
        t1 = _mk_task(db, dt)
        r1 = client.post(f"{base}/{t1.id}/confirm", params={"match_keys": '"abc"'}, headers=auth_owner)
        assert r1.status_code == 200, r1.text
        assert t1.match_keys == ['"abc"']

        # dropped_columns：合法 JSON 数组
        t2 = _mk_task(db, dt)
        r2 = client.post(f"{base}/{t2.id}/confirm", params={"dropped_columns": '["x","y"]'}, headers=auth_owner)
        assert r2.status_code == 200, r2.text
        assert t2.dropped_columns == ["x", "y"]

        # dropped_columns：非法 JSON → 逗号分隔
        t3 = _mk_task(db, dt)
        r3 = client.post(f"{base}/{t3.id}/confirm", params={"dropped_columns": "x,y"}, headers=auth_owner)
        assert r3.status_code == 200, r3.text
        assert t3.dropped_columns == ["x", "y"]

        # dropped_columns：JSON 解析成功但不是 list → 逗号分隔（原始串含引号）
        t4 = _mk_task(db, dt)
        r4 = client.post(f"{base}/{t4.id}/confirm", params={"dropped_columns": '"z"'}, headers=auth_owner)
        assert r4.status_code == 200, r4.text
        assert t4.dropped_columns == ['"z"']

    def test_reanalyze_variants(self, client, db, monkeypatch, ws_id, auth_owner, src_table):
        """reanalyze：任务不存在 404 / 状态不允许 400 / 两种参数解析.

        置空后台执行，避免空内容任务被后台线程清理影响断言.
        """
        monkeypatch.setattr(
            "cndb.plugins.tables.routers.bulk.run_task_in_background",
            lambda *args, **kwargs: None,
        )
        dt, _ = src_table
        base = f"/api/v1/workspaces/{ws_id}/tables/{dt.id}/import"

        # 任务不存在 → 404
        r404 = client.post(f"{base}/99999/reanalyze", headers=auth_owner)
        assert r404.status_code == 404

        # 状态不在 pending_confirm/pending_validation → 400
        t_bad = _mk_task(db, dt, status="pending")
        r400 = client.post(f"{base}/{t_bad.id}/reanalyze", headers=auth_owner)
        assert r400.status_code == 400
        assert "不允许重新分析" in r400.json()["detail"]

        # match_keys 非法 JSON → 回退逗号分隔
        t_a = _mk_task(db, dt)
        r_a = client.post(f"{base}/{t_a.id}/reanalyze", params={"match_keys": "a,b"}, headers=auth_owner)
        assert r_a.status_code == 200, r_a.text
        assert r_a.json()["match_keys"] == ["a", "b"]
        assert t_a.match_keys == ["a", "b"]

        # match_keys 非法 list + 合法策略
        t_b = _mk_task(db, dt)
        r_b = client.post(
            f"{base}/{t_b.id}/reanalyze",
            params={"match_keys": '"abc"', "unknown_cols_strategy": "add_text_field"},
            headers=auth_owner,
        )
        assert r_b.status_code == 200, r_b.text
        assert t_b.match_keys == ['"abc"']
        assert t_b.unknown_cols_strategy == "add_text_field"


__all__ = []
