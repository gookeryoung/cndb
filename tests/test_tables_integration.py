"""tables 插件端到端集成测试."""

import pytest

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole


@pytest.fixture
def owner_user(db):
    u = User(username="owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def editor_user(db):
    u = User(username="editor", nickname="Editor")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def viewer_user(db):
    u = User(username="viewer", nickname="Viewer")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def workspace(db, owner_user):
    ws = Workspace(name="测试工作区", created_by_id=owner_user.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)

    from cndb.plugins.workspaces.models import WorkspaceMember

    for user, role in [
        (owner_user, WorkspaceRole.OWNER),
    ]:
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role=role))
    db.commit()
    return ws


@pytest.fixture
def auth_owner(client, owner_user):
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": owner_user.username, "password": "passw0rd"},
    )
    assert r.status_code == 200, f"Login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def table_with_fields(db, db_engine, workspace, owner_user):
    """创建一个带 text + number 字段的 DataTable（metadata + 物理表, 带 owner_id）."""
    dt = DataTable(workspace_id=workspace.id, owner_id=owner_user.id, name="员工表")
    dt.ensure_db_name()
    db.add(dt)
    db.flush()

    df1 = DataField(table_id=dt.id, name="姓名", field_type="text", order=0)
    df1.ensure_db_name()
    df2 = DataField(table_id=dt.id, name="年龄", field_type="number", order=1)
    df2.ensure_db_name()
    df3 = DataField(
        table_id=dt.id, name="部门", field_type="select", config={"options": ["技术部", "市场部", "人事部"]}, order=2
    )
    df3.ensure_db_name()

    db.add_all([df1, df2, df3])
    db.commit()
    db.refresh(dt)
    db.refresh(df1)
    db.refresh(df2)
    db.refresh(df3)

    # 创建物理表
    ddl.create_table(db_engine, dt)
    return dt, [df1, df2, df3]


# ── field_types 基础测试 ─────────────────────────────


class TestFieldTypesIntegration:
    def test_registry_all_types(self):
        names = sorted(ft.name for ft in default_registry.all())
        assert len(names) >= 9

    def test_select_config_validation(self):
        """空 options 合法（允许导入后自动识别补全）."""
        from cndb.plugins.tables.field_types import SelectFieldConfig

        cfg = SelectFieldConfig(options=[])
        assert cfg.options == []

        # 非空 options 正常工作
        cfg2 = SelectFieldConfig(options=["男", "女"])
        labels = [o.label for o in cfg2.options]
        assert labels == ["男", "女"]


# ── DDL 引擎测试 ────────────────────────────────────


class TestDDLEngine:
    def test_build_sa_table(self, table_with_fields):
        dt, _fields = table_with_fields
        from sqlalchemy import MetaData

        metadata = MetaData()
        sa_table = ddl.build_sa_table(metadata, dt, _fields)
        assert sa_table.name == dt.db_table_name
        col_names = {c.name for c in sa_table.columns}
        assert "id" in col_names
        for df in _fields:
            assert df.db_column_name in col_names
        assert "_trashed" in col_names

    def test_create_and_drop_table(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        # 表应该已存在（由 fixture 创建）
        assert ddl.table_exists(db_engine, dt.db_table_name)

        # 删除后应该不存在
        ddl.drop_table(db_engine, dt.db_table_name)
        assert not ddl.table_exists(db_engine, dt.db_table_name)

    def test_create_table_idempotent(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        ddl.create_table(db_engine, dt)
        ddl.create_table(db_engine, dt)  # 第二次不应报错

    def test_add_and_drop_column(self, db_engine, table_with_fields, db):
        dt, _fields = table_with_fields
        from cndb.plugins.tables.models import DataField

        new_field = DataField(
            table_id=dt.id,
            name="邮箱",
            field_type="text",
            order=3,
        )
        new_field.ensure_db_name()
        db.add(new_field)
        db.commit()
        db.refresh(new_field)

        ddl.add_column(db_engine, dt, new_field)
        insp = __import__("sqlalchemy", fromlist=["inspect"]).inspect(db_engine)
        col_names = {c["name"] for c in insp.get_columns(dt.db_table_name)}
        assert new_field.db_column_name in col_names

        ddl.drop_column(db_engine, dt, new_field)
        # drop_column 后重建 inspect，避免 SQLAlchemy 元数据缓存
        from sqlalchemy import inspect as sa_inspect

        col_names = {c["name"] for c in sa_inspect(db_engine).get_columns(dt.db_table_name)}
        assert new_field.db_column_name not in col_names


# ── records 行 CRUD 测试 ────────────────────────────


class TestRecordsEngine:
    def test_create_and_get_row(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        row = rec.create_row(db_engine, dt, {"姓名": "张三", "年龄": 28})
        assert row is not None
        assert row["姓名"] == "张三"
        assert row["年龄"] == 28
        assert "id" in row

        row_id = row["id"]
        fetched = rec.get_row(db_engine, dt, row_id)
        assert fetched is not None
        assert fetched["姓名"] == "张三"

    def test_update_row(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        row = rec.create_row(db_engine, dt, {"姓名": "李四", "年龄": 30})
        updated = rec.update_row(db_engine, dt, row["id"], {"年龄": 31})
        assert updated is not None
        assert updated["年龄"] == 31

    def test_delete_row(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        row = rec.create_row(db_engine, dt, {"姓名": "王五", "年龄": 25})
        assert rec.delete_row(db_engine, dt, row["id"])
        assert rec.get_row(db_engine, dt, row["id"]) is None

    def test_list_rows_with_filter(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        rec.create_row(db_engine, dt, {"姓名": "赵六", "年龄": 22})
        rec.create_row(db_engine, dt, {"姓名": "钱七", "年龄": 35})
        rec.create_row(db_engine, dt, {"姓名": "孙八", "年龄": 40})

        rows, total = rec.list_rows(
            db_engine,
            dt,
            filters=[{"field_name": "年龄", "op": ">", "value": 30}],
            limit=10,
            offset=0,
        )
        assert total == 2
        assert len(rows) == 2
        ages = {r["年龄"] for r in rows}
        assert ages == {35, 40}

    def test_list_rows_dict_filter_form(self, db_engine, table_with_fields):
        """list_rows 接受 dict {field: value} 形式的 filters."""
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        rec.create_row(db_engine, dt, {"姓名": "张三", "年龄": 22})
        rec.create_row(db_engine, dt, {"姓名": "李四", "年龄": 35})
        rec.create_row(db_engine, dt, {"姓名": "王五", "年龄": 40})

        rows, total = rec.list_rows(
            db_engine,
            dt,
            filters={"年龄": {"op": ">=", "value": 35}},
            limit=10,
            offset=0,
        )
        assert total == 2
        assert {r["姓名"] for r in rows} == {"李四", "王五"}

    def test_list_rows_query_keyword(self, db_engine, table_with_fields):
        """list_rows 的 dict filters 支持 $query 做全局关键词搜索."""
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        rec.create_row(db_engine, dt, {"姓名": "张三丰", "年龄": 50})
        rec.create_row(db_engine, dt, {"姓名": "李四", "年龄": 30})
        rec.create_row(db_engine, dt, {"姓名": "张无忌", "年龄": 25})

        rows, total = rec.list_rows(
            db_engine,
            dt,
            filters={"$query": "张"},
            limit=10,
            offset=0,
        )
        assert total == 2
        assert {r["姓名"] for r in rows} == {"张三丰", "张无忌"}

    def test_list_rows_with_sort(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        rec.create_row(db_engine, dt, {"姓名": "A", "年龄": 30})
        rec.create_row(db_engine, dt, {"姓名": "B", "年龄": 20})
        rec.create_row(db_engine, dt, {"姓名": "C", "年龄": 25})

        rows, _ = rec.list_rows(
            db_engine,
            dt,
            sorts=[{"field_name": "年龄", "direction": "desc"}],
            limit=10,
            offset=0,
        )
        assert rows[0]["年龄"] == 30
        assert rows[-1]["年龄"] == 20

    def test_bulk_operations(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        ids = rec.bulk_create(
            db_engine,
            dt,
            [
                {"姓名": "X", "年龄": 1},
                {"姓名": "Y", "年龄": 2},
                {"姓名": "Z", "年龄": 3},
            ],
        )
        assert len(ids) == 3

        updated = rec.bulk_update(db_engine, dt, ids, {"年龄": 99})
        assert updated == 3

        deleted = rec.bulk_delete(db_engine, dt, ids)
        assert deleted == 3

    def test_soft_delete_and_restore(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from cndb.plugins.tables.services.core import records as rec

        row = rec.create_row(db_engine, dt, {"姓名": "软删", "年龄": 18})
        rec.trash_row(db_engine, dt, row["id"])

        # 默认不包含软删除行
        assert rec.get_row(db_engine, dt, row["id"]) is None
        _rows, _total = rec.list_rows(db_engine, dt)
        assert _total == 0

        # 包含软删除行
        trashed = rec.get_row(db_engine, dt, row["id"])
        assert trashed is None

        # 恢复
        rec.restore_row(db_engine, dt, row["id"])
        assert rec.get_row(db_engine, dt, row["id"]) is not None

    def test_validation_error(self, db_engine, db, workspace):
        from cndb.plugins.tables.services.core import ddl
        from cndb.plugins.tables.services.core import records as rec
        from cndb.plugins.tables.models import DataField, DataTable

        dt = DataTable(workspace_id=workspace.id, name="必填测试表")
        dt.ensure_db_name()
        db.add(dt)
        db.flush()

        # Create a required field
        df = DataField(table_id=dt.id, name="必填名", field_type="text", required=True)
        df.ensure_db_name()
        db.add(df)
        db.commit()
        db.refresh(dt)

        ddl.create_table(db_engine, dt)

        with pytest.raises(ValueError, match="必填字段"):
            rec.create_row(db_engine, dt, {})


# ── Query 编译测试 ──────────────────────────────────


class TestQueryCompile:
    def test_compile_contains(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        from cndb.plugins.tables.services.core.query import compile_filters

        sa_table = ddl.build_sa_table(MetaData(), dt)
        compiled = compile_filters(
            dt,
            sa_table,
            [
                {"field_name": "姓名", "op": "contains", "value": "张"},
            ],
        )
        assert compiled is not None

    def test_compile_invalid_op(self, db_engine, table_with_fields):
        dt, _ = table_with_fields
        from sqlalchemy import MetaData

        from cndb.plugins.tables.services.core.query import compile_filters

        sa_table = ddl.build_sa_table(MetaData(), dt)
        with pytest.raises(ValueError, match="未知操作符"):
            compile_filters(dt, sa_table, [{"field_name": "姓名", "op": "BAD", "value": "x"}])


# ── REST API 端到端测试 ───────────────────────────────


class TestTablesAPI:
    def test_create_table(self, client, workspace, auth_owner):
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables",
            json={"name": "API测试表"},
            headers=auth_owner,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["name"] == "API测试表"
        assert data["db_table_name"].startswith("table_")

    def test_list_tables(self, client, workspace, auth_owner, table_with_fields):
        r = client.get(
            f"/api/v1/workspaces/{workspace.id}/tables",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_get_table_detail(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.get(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "员工表"

    def test_update_table(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.patch(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}",
            json={"name": "员工表V2"},
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert r.json()["name"] == "员工表V2"

    def test_add_field(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/fields",
            json={"name": "岗位", "field_type": "text", "order": 10},
            headers=auth_owner,
        )
        assert r.status_code == 201
        assert r.json()["name"] == "岗位"

    def test_list_fields(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.get(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/fields",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) == 3

    def test_create_record_via_api(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "API用户", "年龄": 33, "部门": "技术部"}},
            headers=auth_owner,
        )
        assert r.status_code == 201
        data = r.json()
        assert data["姓名"] == "API用户"

    def test_list_records_via_api(self, client, workspace, auth_owner, table_with_fields):
        dt, _ = table_with_fields

        # 先创建两行
        client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "R1", "年龄": 20, "部门": "技术部"}},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "R2", "年龄": 30, "部门": "市场部"}},
            headers=auth_owner,
        )

        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records/list",
            json={
                "filters": [{"field_name": "部门", "op": "=", "value": "技术部"}],
                "limit": 10,
            },
            headers=auth_owner,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["rows"][0]["姓名"] == "R1"

    def test_list_records_get_endpoint(self, client, workspace, auth_owner, table_with_fields):
        """GET /records 端点（前端 GridPage 使用的列表 API）."""
        dt, _ = table_with_fields
        rec_plugin = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "G1", "年龄": 20, "部门": "技术部"}},
            headers=auth_owner,
        )
        assert rec_plugin.status_code == 201

        # GET 端点：无参数
        r = client.get(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            headers=auth_owner,
        )
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["rows"][0]["姓名"] == "G1"


# ── Phase 1: TableDetail 增强字段测试 ──────────────


class TestTableDetailEnhancement:
    """验证 get_table / list_tables 新增强字段（统计、权限上下文、owner、工作区摘要）."""

    def test_list_tables_includes_stats(self, client, workspace, auth_owner, table_with_fields):
        """list_tables 返回的每张表应包含 field_count / record_count / view_count."""
        dt, _ = table_with_fields

        # 先插两行 + 建一个视图，让统计有值
        client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "R1", "年龄": 20, "部门": "技术部"}},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "R2", "年龄": 30, "部门": "市场部"}},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/views",
            json={"name": "默认", "view_type": "grid", "is_default": True},
            headers=auth_owner,
        )

        r = client.get(f"/api/v1/workspaces/{workspace.id}/tables", headers=auth_owner)
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1

        row = items[0]
        # 统计字段必须存在且类型正确
        assert "field_count" in row
        assert "record_count" in row
        assert "view_count" in row
        assert row["field_count"] == 3  # 姓名/年龄/部门
        assert row["record_count"] == 2
        assert row["view_count"] == 1
        # 原有字段不丢
        assert row["name"] == "员工表"
        assert "db_table_name" in row

    def test_get_table_detail_complete_structure(self, client, workspace, auth_owner, table_with_fields):
        """get_table 返回完整 TableDetailResponse 结构."""
        dt, _ = table_with_fields
        # 预建视图 + 插数据
        client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/records",
            json={"values": {"姓名": "R1", "年龄": 20, "部门": "技术部"}},
            headers=auth_owner,
        )
        client.post(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}/views",
            json={"name": "默认", "view_type": "grid", "is_default": True},
            headers=auth_owner,
        )

        r = client.get(f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}", headers=auth_owner)
        assert r.status_code == 200
        d = r.json()

        # ── 基础字段（继承 TableResponse）
        assert d["name"] == "员工表"
        assert d["workspace_id"] == workspace.id
        assert "db_table_name" in d
        assert "created_at" in d
        assert "updated_at" in d

        # ── 统计字段（Phase 1 增强）
        assert d["field_count"] == 3
        assert d["record_count"] == 1
        assert d["view_count"] == 1

        # ── fields: 列表且过滤了 trashed
        assert isinstance(d["fields"], list)
        assert len(d["fields"]) == 3
        field_names = {f["name"] for f in d["fields"]}
        assert field_names == {"姓名", "年龄", "部门"}

        # ── views: 精简摘要列表
        assert isinstance(d["views"], list)
        assert len(d["views"]) == 1
        v = d["views"][0]
        assert "id" in v and "name" in v and "view_type" in v and "is_default" in v
        assert v["name"] == "默认"
        assert v["is_default"] is True

        # ── current_user_actions: owner 应拥有所有权限
        assert isinstance(d["current_user_actions"], list)
        actions = set(d["current_user_actions"])
        assert "read" in actions
        assert "edit_records" in actions
        assert "edit_views" in actions
        assert "edit_schema" in actions

        # ── owner: 表级拥有者（DataTable.owner_id 关联用户，继承自 TableResponse）
        assert d["owner"] is not None
        owner = d["owner"]
        assert "id" in owner and "username" in owner
        assert owner["username"] == "owner"

        # ── workspace_owner: 工作区拥有者（从 WorkspaceMember 查出，含 nickname）
        assert d["workspace_owner"] is not None
        ws_owner = d["workspace_owner"]
        assert "id" in ws_owner and "username" in ws_owner and "nickname" in ws_owner
        assert ws_owner["username"] == "owner"

        # ── workspace: 精简摘要
        assert d["workspace"] is not None
        ws = d["workspace"]
        assert ws["id"] == workspace.id
        assert ws["name"] == "测试工作区"
        assert ws["current_user_role"] == "owner"

    def test_current_user_actions_differ_by_role(
        self,
        client,
        workspace,
        auth_owner,
        table_with_fields,
        db,
        editor_user,
        viewer_user,
    ):
        """不同工作区角色的 current_user_actions 应不同."""
        from cndb.plugins.workspaces.models import WorkspaceMember, WorkspaceRole

        # 给 editor / viewer 加进工作区
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=editor_user.id, role=WorkspaceRole.EDITOR))
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=viewer_user.id, role=WorkspaceRole.VIEWER))
        db.commit()

        dt, _ = table_with_fields

        # editor 登录
        r_login = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": editor_user.username, "password": "passw0rd"},
        )
        assert r_login.status_code == 200
        auth_editor = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

        r = client.get(f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}", headers=auth_editor)
        assert r.status_code == 200
        actions_e = set(r.json()["current_user_actions"])
        # editor 应该能编辑记录、视图；但不能编辑 schema
        assert "edit_records" in actions_e
        assert "edit_views" in actions_e
        assert "edit_schema" not in actions_e  # schema 需 admin+

        # viewer 登录
        r_login = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": viewer_user.username, "password": "passw0rd"},
        )
        assert r_login.status_code == 200
        auth_viewer = {"Authorization": f"Bearer {r_login.json()['access_token']}"}

        r = client.get(f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}", headers=auth_viewer)
        assert r.status_code == 200
        actions_v = set(r.json()["current_user_actions"])
        # viewer 应该只有 read
        assert "read" in actions_v
        assert "edit_records" not in actions_v
        assert "edit_views" not in actions_v
        assert "edit_schema" not in actions_v

        # viewer 的 workspace.current_user_role 也应正确
        assert r.json()["workspace"]["current_user_role"] == "viewer"

    def test_empty_table_stats_are_zero(self, client, workspace, auth_owner, db):
        """刚创建的空表：record_count=0, field_count=0, 但默认视图「全部」自动存在."""
        r = client.post(
            f"/api/v1/workspaces/{workspace.id}/tables",
            json={"name": "空表"},
            headers=auth_owner,
        )
        assert r.status_code == 201
        tid = r.json()["id"]

        r = client.get(f"/api/v1/workspaces/{workspace.id}/tables/{tid}", headers=auth_owner)
        assert r.status_code == 200
        d = r.json()
        assert d["field_count"] == 0
        assert d["record_count"] == 0
        # 创建表时自动生成默认视图「全部」
        assert d["view_count"] == 1
        assert d["fields"] == []
        assert len(d["views"]) == 1
        v0 = d["views"][0]
        assert v0["name"] == "全部"
        assert v0["view_type"] == "grid"
        assert v0["is_default"] is True
        # 空表仍有基础权限动作（owner）
        assert "edit_schema" in d["current_user_actions"]

    def test_trashed_table_excluded_from_list(self, client, workspace, auth_owner, table_with_fields):
        """软删表不出现在 list_tables 默认结果里."""
        dt, _ = table_with_fields
        # 再建一张表
        client.post(
            f"/api/v1/workspaces/{workspace.id}/tables",
            json={"name": "待删表"},
            headers=auth_owner,
        )

        r = client.get(f"/api/v1/workspaces/{workspace.id}/tables", headers=auth_owner)
        assert r.status_code == 200
        assert len(r.json()) == 2

        # 软删第一张
        client.delete(
            f"/api/v1/workspaces/{workspace.id}/tables/{dt.id}",
            headers=auth_owner,
        )
        r = client.get(f"/api/v1/workspaces/{workspace.id}/tables", headers=auth_owner)
        assert r.status_code == 200
        names = {t["name"] for t in r.json()}
        assert "员工表" not in names
        assert "待删表" in names

        # include_trashed=true 能看到
        r = client.get(
            f"/api/v1/workspaces/{workspace.id}/tables?include_trashed=true",
            headers=auth_owner,
        )
        assert r.status_code == 200
        assert len(r.json()) == 2


__all__ = []
