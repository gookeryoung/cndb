"""REST API E2E — select/multiselect 导入后自动生成 options.

覆盖场景：
1. bulk-create 路由导入后，select/multiselect 字段的 config.options 被自动填充
2. 已有部分 options（带自定义 color）→ 新值追加、旧值不变
3. multiselect 字段（list 值）正确拆成独立选项
4. bulk-update 路由也能触发 options 同步
5. 文件导入（transfer.import_rows_from_json/csv）触发 options 自动补全
6. 重复值不重复添加、None/空值被跳过

走真实 REST API（TestClient + 真实数据库），不 mock.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cndb.core.config import settings
from cndb.core.database import get_db
from cndb.models.base import Base
from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.workspaces.models import Workspace, WorkspaceRole

# ── fixtures ─────────────────────────────────────────


@pytest.fixture
def db_engine(tmp_path: Path):
    settings.AUTH_ENABLED = True
    db_path = tmp_path / "select_options_e2e.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    import cndb.plugins.accounts.models
    import cndb.plugins.tables.models
    import cndb.plugins.workspaces.models  # noqa: F401

    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db(db_engine):
    SessionLocal = sessionmaker(bind=db_engine, autocommit=False, autoflush=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db):
    from cndb.app import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def owner_user(db):
    u = User(username="e2e_owner", nickname="E2E Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def auth_owner(client, owner_user):
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": owner_user.username, "password": "passw0rd"},
    )
    assert r.status_code == 200, f"Login failed: {r.text}"
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def workspace(db, owner_user):
    ws = Workspace(name="E2E 工作区", created_by_id=owner_user.id)
    db.add(ws)
    db.flush()
    from cndb.plugins.workspaces.models import WorkspaceMember

    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner_user.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    return ws


# ── helpers ──────────────────────────────────────────


def _create_table(client: TestClient, wid: int, auth: dict, name: str = "E2E 测试表") -> int:
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth,
        json={"name": name},
    )
    assert r.status_code == 201, f"建表失败: {r.status_code} {r.text}"
    return r.json()["id"]


def _create_field(
    client: TestClient,
    wid: int,
    tid: int,
    auth: dict,
    name: str,
    field_type: str,
    config: dict | None = None,
    order: int = 0,
) -> dict:
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth,
        json={
            "name": name,
            "field_type": field_type,
            "config": config or {},
            "order": order,
        },
    )
    assert r.status_code == 201, f"建字段失败: {r.status_code} {r.text}"
    return r.json()


def _list_fields(client: TestClient, wid: int, tid: int, auth: dict) -> list[dict]:
    r = client.get(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=auth,
    )
    assert r.status_code == 200
    return r.json()


def _bulk_create(
    client: TestClient,
    wid: int,
    tid: int,
    auth: dict,
    rows: list[dict],
) -> dict:
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/bulk-create",
        headers=auth,
        json={"rows": [{"values": row} for row in rows]},
    )
    assert r.status_code == 201, f"bulk-create 失败: {r.status_code} {r.text}"
    return r.json()


def _bulk_update(
    client: TestClient,
    wid: int,
    tid: int,
    auth: dict,
    row_ids: list[int],
    values: dict,
) -> dict:
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/records/bulk-update",
        headers=auth,
        json={"row_ids": row_ids, "values": values},
    )
    assert r.status_code == 200, f"bulk-update 失败: {r.status_code} {r.text}"
    return r.json()


def _get_field_by_name(fields: list[dict], name: str) -> dict:
    for f in fields:
        if f.get("name") == name:
            return f
    raise KeyError(f"未找到字段 {name!r}")


# ── 测试用例 ──────────────────────────────────────────


class TestBulkCreateAutoFillOptions:
    """bulk-create 路由导入 select 值 → config.options 自动填充."""

    def test_select_field_empty_options_filled_by_bulk_create(self, client, workspace, auth_owner):
        """核心场景：空 options 的 select 字段 → bulk-create 导入值 → options 自动填充."""
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "员工表")

        # 建字段：select 字段 options=[]，text 字段
        _create_field(client, wid, tid, auth_owner, "姓名", "text", {}, order=0)
        _create_field(client, wid, tid, auth_owner, "部门", "select", {"options": []}, order=1)

        # bulk-create 导入数据
        _bulk_create(
            client,
            wid,
            tid,
            auth_owner,
            [
                {"姓名": "Alice", "部门": "技术部"},
                {"姓名": "Bob", "部门": "市场部"},
                {"姓名": "Carol", "部门": "技术部"},
            ],
        )

        # GET /fields 验证
        fields = _list_fields(client, wid, tid, auth_owner)
        f_dept = _get_field_by_name(fields, "部门")
        options = f_dept["config"]["options"]
        labels = [o["label"] for o in options]
        assert set(labels) == {"技术部", "市场部"}
        # 每个 option 应有 color
        assert all("color" in o and o["color"] for o in options)

    def test_multiselect_field_filled_by_bulk_create(self, client, workspace, auth_owner):
        """multiselect 字段（list 值）→ 拆成独立选项."""
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "项目表")

        _create_field(client, wid, tid, auth_owner, "名称", "text", {}, order=0)
        _create_field(client, wid, tid, auth_owner, "标签", "multiselect", {"options": []}, order=1)

        _bulk_create(
            client,
            wid,
            tid,
            auth_owner,
            [
                {"名称": "项目A", "标签": ["urgent", "backend"]},
                {"名称": "项目B", "标签": ["backend", "devops"]},
                {"名称": "项目C", "标签": ["urgent", "frontend"]},
            ],
        )

        fields = _list_fields(client, wid, tid, auth_owner)
        f_tags = _get_field_by_name(fields, "标签")
        labels = [o["label"] for o in f_tags["config"]["options"]]
        assert set(labels) == {"urgent", "backend", "devops", "frontend"}

    def test_existing_options_preserved_new_appended(self, client, workspace, auth_owner):
        """已有 options（带自定义 color）→ 导入新值 → 旧的保持、新的追加."""
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "状态表")

        _create_field(client, wid, tid, auth_owner, "名称", "text", {}, order=0)
        _create_field(
            client,
            wid,
            tid,
            auth_owner,
            "状态",
            "select",
            {
                "options": [
                    {"label": "done", "value": "done", "color": "blue"},
                    {"label": "todo", "value": "todo", "color": "gold"},
                ]
            },
            order=1,
        )

        _bulk_create(
            client,
            wid,
            tid,
            auth_owner,
            [
                {"名称": "任务1", "状态": "done"},
                {"名称": "任务2", "状态": "in_progress"},
                {"名称": "任务3", "状态": "done"},
            ],
        )

        fields = _list_fields(client, wid, tid, auth_owner)
        f_status = _get_field_by_name(fields, "状态")
        options = f_status["config"]["options"]
        assert len(options) == 3
        # 已有项顺序和 color 不变
        assert options[0]["label"] == "done"
        assert options[0]["color"] == "blue"
        assert options[1]["label"] == "todo"
        assert options[1]["color"] == "gold"
        # 新值追加到末尾
        assert options[2]["label"] == "in_progress"

    def test_no_duplicate_on_repeat_import(self, client, workspace, auth_owner):
        """重复导入相同值 → options 不重复."""
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "城市表")

        _create_field(client, wid, tid, auth_owner, "城市", "select", {"options": []}, order=0)

        _bulk_create(client, wid, tid, auth_owner, [{"城市": "Beijing"}, {"城市": "Shanghai"}])
        # 再导入一次同样的值 + 一个新值
        _bulk_create(client, wid, tid, auth_owner, [{"城市": "Beijing"}, {"城市": "Guangzhou"}])

        fields = _list_fields(client, wid, tid, auth_owner)
        f_city = _get_field_by_name(fields, "城市")
        labels = [o["label"] for o in f_city["config"]["options"]]
        assert len(labels) == 3
        assert labels.count("Beijing") == 1

    def test_none_and_empty_values_skipped(self, client, workspace, auth_owner):
        """None/空值不进入 options."""
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "测试表")

        _create_field(client, wid, tid, auth_owner, "状态", "select", {"options": []}, order=0)

        _bulk_create(
            client,
            wid,
            tid,
            auth_owner,
            [
                {"状态": "ok"},
                {"状态": None},
            ],
        )

        fields = _list_fields(client, wid, tid, auth_owner)
        f_status = _get_field_by_name(fields, "状态")
        labels = [o["label"] for o in f_status["config"]["options"]]
        assert labels == ["ok"]

    def test_other_config_keys_preserved(self, client, workspace, auth_owner):
        """select 字段 config 有其他 key（auto_fill_colors 等）→ 同步后不丢失."""
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "测试表")

        _create_field(
            client,
            wid,
            tid,
            auth_owner,
            "等级",
            "select",
            {
                "options": [],
                "auto_fill_colors": True,
                "placeholder": "请选择等级",
            },
            order=0,
        )

        _bulk_create(client, wid, tid, auth_owner, [{"等级": "high"}, {"等级": "low"}])

        fields = _list_fields(client, wid, tid, auth_owner)
        f_level = _get_field_by_name(fields, "等级")
        cfg = f_level["config"]
        assert cfg.get("auto_fill_colors") is True
        assert cfg.get("placeholder") == "请选择等级"
        assert "options" in cfg
        assert len(cfg["options"]) == 2

    def test_table_without_select_fields_noop(self, client, workspace, auth_owner):
        """没有 select/multiselect 字段的表 → bulk-create 正常返回，不报错."""
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "纯文本表")

        _create_field(client, wid, tid, auth_owner, "姓名", "text", {}, order=0)
        _create_field(client, wid, tid, auth_owner, "年龄", "number", {}, order=1)

        result = _bulk_create(
            client,
            wid,
            tid,
            auth_owner,
            [
                {"姓名": "Alice", "年龄": 25},
            ],
        )
        assert result["created"] == 1


class TestBulkUpdateAutoFillOptions:
    """bulk-update 路由也能触发 options 同步."""

    def test_bulk_update_new_select_value_fills_options(self, client, workspace, auth_owner):
        """bulk-update 更新 select 字段值为新值 → options 自动追加."""
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "更新表")

        _create_field(client, wid, tid, auth_owner, "名称", "text", {}, order=0)
        _create_field(client, wid, tid, auth_owner, "状态", "select", {"options": []}, order=1)

        # 先插入数据（状态值 A）
        result = _bulk_create(
            client,
            wid,
            tid,
            auth_owner,
            [
                {"名称": "任务1", "状态": "A"},
                {"名称": "任务2", "状态": "B"},
            ],
        )
        row_ids = result["ids"]

        fields = _list_fields(client, wid, tid, auth_owner)
        f_status = _get_field_by_name(fields, "状态")
        assert len(f_status["config"]["options"]) == 2

        # 用 bulk-update 把行更新成新的状态值 C
        _bulk_update(client, wid, tid, auth_owner, row_ids[:1], {"状态": "C"})

        fields = _list_fields(client, wid, tid, auth_owner)
        f_status = _get_field_by_name(fields, "状态")
        labels = [o["label"] for o in f_status["config"]["options"]]
        # C 被追加
        assert "C" in labels


class TestFileImportAutoFillOptions:
    """通过 /import 路由（文件上传 → transfer.import_rows_from_json）也能触发 options 自动补全."""

    def test_json_file_import_fills_select_options(self, client, workspace, auth_owner):
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "文件导入表")

        _create_field(client, wid, tid, auth_owner, "姓名", "text", {}, order=0)
        _create_field(client, wid, tid, auth_owner, "部门", "select", {"options": []}, order=1)

        # 用 Transfer-Encoding: identity 直接上传 JSON 文件
        import io

        json_content = json.dumps(
            [
                {"姓名": "Alice", "部门": "技术部"},
                {"姓名": "Bob", "部门": "市场部"},
                {"姓名": "Carol", "部门": "销售部"},
            ]
        )
        files = {"file": ("data.json", io.BytesIO(json_content.encode("utf-8")), "application/json")}
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import",
            headers=auth_owner,
            files=files,
        )
        assert r.status_code == 200, f"文件导入失败: {r.status_code} {r.text}"

        fields = _list_fields(client, wid, tid, auth_owner)
        f_dept = _get_field_by_name(fields, "部门")
        labels = [o["label"] for o in f_dept["config"]["options"]]
        assert set(labels) == {"技术部", "市场部", "销售部"}

    def test_csv_file_import_fills_select_options(self, client, workspace, auth_owner):
        wid = workspace.id
        tid = _create_table(client, wid, auth_owner, "CSV 导入表")

        _create_field(client, wid, tid, auth_owner, "姓名", "text", {}, order=0)
        _create_field(client, wid, tid, auth_owner, "城市", "select", {"options": []}, order=1)

        import io

        csv_content = "姓名,城市\nAlice,Beijing\nBob,Shanghai\nCarol,Beijing\n".encode()
        files = {"file": ("data.csv", io.BytesIO(csv_content), "text/csv")}
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/import",
            headers=auth_owner,
            files=files,
        )
        assert r.status_code == 200, f"CSV 导入失败: {r.status_code} {r.text}"

        fields = _list_fields(client, wid, tid, auth_owner)
        f_city = _get_field_by_name(fields, "城市")
        labels = [o["label"] for o in f_city["config"]["options"]]
        assert set(labels) == {"Beijing", "Shanghai"}


class TestSyncFromExistingData:
    """物理表已有的存量数据也能在导入后被 sync 到 options."""

    def test_sync_selects_existing_rows_on_import(self, db, db_engine, workspace, auth_owner):
        """先手动塞几条数据到物理表（select 字段 options 为空）→ bulk-create 追加新数据 →
        sync 扫物理表把存量 + 新值都补全到 options."""
        from sqlalchemy import MetaData

        from cndb.plugins.tables.services.core import ddl as table_ddl

        wid = workspace.id

        # 手动建 DataTable + DataField（绕过 API 直接写 metadata）
        table = DataTable(workspace_id=wid, owner_id=workspace.created_by_id, name="存量同步表")
        table.ensure_db_name()
        db.add(table)
        db.flush()

        f_text = DataField(table_id=table.id, name="姓名", field_type="text", order=0)
        f_text.ensure_db_name()
        f_select = DataField(table_id=table.id, name="部门", field_type="select", config={"options": []}, order=1)
        f_select.ensure_db_name()
        db.add_all([f_text, f_select])
        db.commit()
        db.refresh(table)
        db.refresh(f_text)
        db.refresh(f_select)

        # 物理建表
        table_ddl.create_table(db_engine, table)

        # 手动往物理表塞存量数据（用 raw SQL）
        meta = MetaData()
        meta.reflect(bind=db_engine, only=[table.db_table_name])
        sa_table = meta.tables[table.db_table_name]
        db.execute(
            sa_table.insert(),
            [
                {f_text.db_column_name: "OldA", f_select.db_column_name: "技术部"},
                {f_text.db_column_name: "OldB", f_select.db_column_name: "人事部"},
            ],
        )
        db.commit()

        # 现在用 bulk-create API 追加新数据
        tid = table.id
        client = TestClient(app_from_db(db))
        new_token = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": "e2e_owner", "password": "passw0rd"},
        ).json()["access_token"]
        new_auth = {"Authorization": f"Bearer {new_token}"}

        _bulk_create(
            client,
            wid,
            tid,
            new_auth,
            [
                {"姓名": "NewC", "部门": "市场部"},
                {"姓名": "NewD", "部门": "技术部"},  # 存量已有，不重复
            ],
        )

        # 验证 options 包含存量的 + 新导入的
        fields = _list_fields(client, wid, tid, new_auth)
        f_dept = _get_field_by_name(fields, "部门")
        labels = [o["label"] for o in f_dept["config"]["options"]]
        assert set(labels) == {"技术部", "人事部", "市场部"}


def app_from_db(db):
    """为了存量场景复用 TestClient fixture 的依赖覆盖逻辑."""
    from cndb.app import app

    def _override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    return app
