"""E2E: 字段从其他表引入 —— field_ops 单元测试 + 路由集成测试.

覆盖矩阵：
┌─────────────────────────────┬──────────────────────────────────┐
│ 场景                         │ 关键断言                          │
├─────────────────────────────┼──────────────────────────────────┤
│ 单字段导入（按 field_id）     │ 201 + created 列表含新字段        │
│ 多字段批量导入               │ 所有 src_fields 克隆成功          │
│ 按字段名列表导入             │ 正确匹配字段名                    │
│ import_all_fields            │ 源表全部字段克隆                  │
│ 同名冲突（skip_conflicts=F） │ 400 + 冲突详情                    │
│ 同名冲突（skip_conflicts=T） │ 201 + skipped 列表                │
│ link 字段克隆                │ target_table_id 保留 + 物理表 OK  │
│ 源表不存在 / 已回收          │ 400                               │
│ 源字段不存在                  │ 400                               │
│ POST /fields/import 无 spec  │ 400                               │
│ create_table 带 import_from  │ 建表即带字段 + 回滚逻辑            │
│ field_ops 单元测试           │ resolve / validate / plan / exec   │
└─────────────────────────────┴──────────────────────────────────┘
"""

from __future__ import annotations

import pytest

# ── 辅助：创建源表（带若干字段） ──────────────────────


@pytest.fixture
def _src_table(client, auth_headers, db):
    """创建一个带 4 个基础字段的源表供各测试共享."""
    r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WS_SRC"})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]

    r = client.post(
        f"/api/v1/workspaces/{wid}/tables",
        headers=auth_headers,
        json={"name": "SrcTable"},
    )
    assert r.status_code == 201, r.text
    tid = r.json()["id"]

    # 创建 4 个字段
    for i, spec in enumerate(
        [
            ("src_name", "text"),
            ("src_amount", "number"),
            ("src_active", "boolean"),
            ("src_email", "email"),
        ]
    ):
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": spec[0], "field_type": spec[1], "order": i},
        )
        assert r.status_code == 201, r.text

    return wid, tid


# ── 基础场景：单字段 / 多字段 / import_all ──────────


class TestFieldImportRoute:
    def test_import_single_field_by_id(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        # 目标表
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstSingle"},
        )
        dst_tid = r.json()["id"]

        # 先拿源表字段 id
        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
        )
        src_field_ids = [f["id"] for f in r.json()]

        # 导入第一个字段
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [src_field_ids[0]]},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["created"]) == 1
        assert body["created"][0]["name"] == "src_name"
        assert body["created"][0]["field_type"] == "text"
        assert body["total_source_count"] == 1

        # 目标表现在有 1 个字段
        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields",
            headers=auth_headers,
        )
        assert len(r.json()) == 1

    def test_import_multiple_fields(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstMulti"},
        )
        dst_tid = r.json()["id"]

        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
        )
        src_field_ids = [f["id"] for f in r.json()]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": src_field_ids[:3]},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["created"]) == 3
        names = {f["name"] for f in body["created"]}
        assert names == {"src_name", "src_amount", "src_active"}

    def test_import_by_field_names(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstByName"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "field_names": ["src_amount", "src_email"],
            },
        )
        assert r.status_code == 201, r.text
        names = {f["name"] for f in r.json()["created"]}
        assert names == {"src_amount", "src_email"}

    def test_import_all_fields(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstAll"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["created"]) == 4
        assert body["total_source_count"] == 4

    def test_import_preserves_config(self, client, auth_headers, _src_table):
        """select 字段带 config.options —— 克隆后 config 完整保留."""
        wid, src_tid = _src_table
        # 在源表加一个带 config 的 select 字段
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
            json={
                "name": "src_select",
                "field_type": "select",
                "config": {"options": ["A", "B", "C"]},
                "order": 99,
            },
        )
        src_select_id = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstCfg"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [src_select_id]},
        )
        assert r.status_code == 201, r.text
        created = r.json()["created"][0]
        assert created["field_type"] == "select"
        # select options 会被 normalize 成 [{label, value, color}] 结构
        created_opts = created["config"]["options"]
        opt_values = [o["value"] if isinstance(o, dict) else o for o in created_opts]
        assert opt_values == ["A", "B", "C"]


# ── 冲突处理 ─────────────────────────────────────────


class TestFieldImportConflicts:
    def test_conflict_raises_400(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstConflict"},
        )
        dst_tid = r.json()["id"]

        # 目标表先建一个同名字段
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields",
            headers=auth_headers,
            json={"name": "src_name", "field_type": "text", "order": 0},
        )

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_names": ["src_name"]},
        )
        assert r.status_code == 400
        assert "同名字段" in r.json()["detail"]

    def test_conflict_skip_mode(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstSkip"},
        )
        dst_tid = r.json()["id"]

        # 建一个同名字段 + 一个非同名字段
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields",
            headers=auth_headers,
            json={"name": "src_name", "field_type": "text", "order": 0},
        )

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={
                "source_table_id": src_tid,
                "import_all_fields": True,
                "skip_conflicts": True,
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # src_name 冲突被跳过，其他 3 个字段克隆成功
        assert len(body["created"]) == 3
        assert len(body["skipped"]) == 1
        assert "src_name" in body["skipped"][0]
        created_names = {f["name"] for f in body["created"]}
        assert "src_name" not in created_names
        assert {"src_amount", "src_active", "src_email"} <= created_names


# ── 错误路径 ─────────────────────────────────────────


class TestFieldImportErrors:
    def test_source_table_not_found(self, client, auth_headers, _src_table):
        wid, _src_tid = _src_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstNoSrc"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": 99999, "import_all_fields": True},
        )
        assert r.status_code == 400

    def test_source_field_not_found(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstBadFid"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "field_ids": [99999]},
        )
        assert r.status_code == 400
        assert "不存在" in r.json()["detail"]

    def test_no_spec_returns_400(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstEmpty"},
        )
        dst_tid = r.json()["id"]

        # 三种模式都没指定
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid},
        )
        assert r.status_code == 400

    def test_trashed_source_table_rejected(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table
        # 把源表软删除
        client.delete(f"/api/v1/workspaces/{wid}/tables/{src_tid}", headers=auth_headers)

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DstTrashed"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True},
        )
        assert r.status_code == 400
        assert "已进回收站" in r.json()["detail"]


# ── link 字段克隆 ──────────────────────────────────────


class TestLinkFieldImport:
    def test_link_field_clone_preserves_target(self, client, auth_headers, db):
        """link 字段克隆后 config.target_table_id 保留原目标."""
        # 创建工作区 + 两张表（目标表 + 引用表）
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WSLINK"})
        wid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "LinkTarget"},
        )
        target_tid = r.json()["id"]

        # 源表有一个 link 字段指向 LinkTarget
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "LinkSource"},
        )
        src_tid = r.json()["id"]

        client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
            json={
                "name": "link_to_target",
                "field_type": "link",
                "order": 0,
                "config": {"target_table_id": target_tid},
            },
        )

        # 克隆到新表
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "LinkDest"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True},
        )
        assert r.status_code == 201, r.text
        created = r.json()["created"][0]
        assert created["field_type"] == "link"
        assert created["config"]["target_table_id"] == target_tid

        # 物理 link 关联表应该已创建
        from sqlalchemy import inspect

        from cndb.plugins.tables.models import DataField

        created_field = db.get(DataField, created["id"])
        assert created_field is not None
        insp = inspect(db.get_bind())
        assert created_field.link_table_name in insp.get_table_names()

    def test_link_field_missing_target_rejected(self, client, auth_headers, db):
        """link 字段 target_table_id 指向不存在表 → 拒绝克隆."""
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WSLINK2"})
        wid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "BadLinkSrc"},
        )
        src_tid = r.json()["id"]

        # 手动在 DB 里写一个指向不存在表的 link 字段
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create

        dt = db.get(DataTable, src_tid)
        bad_field = DataField(
            table_id=dt.id,
            name="ghost_link",
            field_type="link",
            config={"target_table_id": 99999},
        )
        bad_field.ensure_db_name()
        db.add(bad_field)
        db.commit()
        ddl_create(db.get_bind(), dt)  # link 字段需要建关联表
        db.refresh(bad_field)

        # 克隆应该失败
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "BadLinkDst"},
        )
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True},
        )
        assert r.status_code == 400
        assert "不存在" in r.json()["detail"]


# ── create_table 带 import_from_table_id ──────────────


class TestCreateTableWithImport:
    def test_create_table_with_import(self, client, auth_headers, _src_table):
        """建表同时从源表引入全部字段."""
        wid, src_tid = _src_table

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={
                "name": "DstBuiltIn",
                "import_from_table_id": src_tid,
                "import_all_fields": True,
            },
        )
        assert r.status_code == 201, r.text
        dst_tid = r.json()["id"]

        # 目标表现在应该有 4 个字段
        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields",
            headers=auth_headers,
        )
        fields = r.json()
        assert len(fields) == 4
        names = {f["name"] for f in fields}
        assert names == {"src_name", "src_amount", "src_active", "src_email"}

    def test_create_table_with_import_by_names(self, client, auth_headers, _src_table):
        wid, src_tid = _src_table

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={
                "name": "DstByNameBuilt",
                "import_from_table_id": src_tid,
                "import_field_names": ["src_name", "src_email"],
            },
        )
        assert r.status_code == 201, r.text
        dst_tid = r.json()["id"]

        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields",
            headers=auth_headers,
        )
        names = {f["name"] for f in r.json()}
        assert names == {"src_name", "src_email"}


# ── field_ops 单元测试 ────────────────────────────────


class TestFieldOpsUnit:
    def test_resolve_source_fields_by_ids(self, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.fields.field_ops import resolve_source_fields

        src = DataTable(workspace_id=1, name="S", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()

        for i, name in enumerate(["a", "b", "c"]):
            f = DataField(table_id=src.id, name=name, field_type="text", order=i)
            f.ensure_db_name()
            db.add(f)
        db.commit()
        db.refresh(src)

        fields = resolve_source_fields(src, field_ids=[src.fields[0].id, src.fields[2].id])
        assert [f.name for f in fields] == ["a", "c"]

    def test_resolve_source_fields_by_names_missing(self, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.fields.field_ops import resolve_source_fields

        src = DataTable(workspace_id=1, name="S", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()

        f = DataField(table_id=src.id, name="only", field_type="text", order=0)
        f.ensure_db_name()
        db.add(f)
        db.commit()

        with pytest.raises(ValueError, match="不存在"):
            resolve_source_fields(src, field_names=["only", "missing"])

    def test_plan_field_import_conflict(self, db):
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.fields.field_ops import plan_field_import

        dst = DataTable(workspace_id=1, name="D", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        existing = DataField(table_id=dst.id, name="dup", field_type="text", order=0)
        existing.ensure_db_name()
        db.add(existing)
        db.commit()

        src_f = DataField(name="dup", field_type="text", order=0)
        ok_f = DataField(name="ok", field_type="number", order=1)

        plan, skipped = plan_field_import(dst, [src_f, ok_f])
        assert len(plan) == 1
        assert plan[0].name == "ok"
        assert len(skipped) == 1
        assert "dup" in skipped[0]

    def test_validate_link_targets_missing(self, db):
        from cndb.plugins.tables.models import DataField
        from cndb.plugins.tables.services.fields.field_ops import validate_link_targets_exist

        bad = DataField(name="ghost", field_type="link", config={"target_table_id": 99999})
        with pytest.raises(ValueError, match="不存在"):
            validate_link_targets_exist([bad], db)


# ── copy_table refactor 回归 ──────────────────────────


class TestCopyTableRegression:
    def test_copy_table_still_works(self, client, auth_headers, db):
        """copy_table refactor 后行为不变."""
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WSCOPY"})
        wid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "Src"},
        )
        tid = r.json()["id"]

        # 建两个字段 + 插入一行数据
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "name", "field_type": "text", "order": 0},
        )
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
            headers=auth_headers,
            json={"name": "score", "field_type": "number", "order": 1},
        )
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/records",
            headers=auth_headers,
            json={"values": {"name": "Alice", "score": 95}},
        )

        # 复制结构 + 数据
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{tid}/copy?include_data=true",
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        copy_tid = r.json()["id"]

        # 字段相同
        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{copy_tid}/fields",
            headers=auth_headers,
        )
        copy_names = {f["name"] for f in r.json()}
        assert copy_names == {"name", "score"}

        # 数据也在
        r = client.get(
            f"/api/v1/workspaces/{wid}/tables/{copy_tid}/records",
            headers=auth_headers,
        )
        assert r.json()["total"] == 1
        assert r.json()["rows"][0]["name"] == "Alice"
        assert r.json()["rows"][0]["score"] == 95

    def test_copy_table_with_link_field(self, client, auth_headers, db):
        """源表有 link 字段时克隆正确 — link 字段的 target_table_id 保留."""
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WSCOPYLINK"})
        wid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "Targets"},
        )
        target_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "SrcLink"},
        )
        src_tid = r.json()["id"]

        client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
            json={"name": "my_link", "field_type": "link", "order": 0, "config": {"target_table_id": target_tid}},
        )

        r = client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/copy",
            headers=auth_headers,
        )
        assert r.status_code == 201, r.text
        copy_tid = r.json()["id"]

        # 复制后的字段 link_table_name 在物理表中存在
        from cndb.plugins.tables.models import DataTable
        from cndb.plugins.tables.services.core.links import is_link_field, link_table_exists

        copy_table = db.get(DataTable, copy_tid)
        link_fields = [f for f in copy_table.active_fields() if is_link_field(f)]
        assert len(link_fields) == 1
        assert link_table_exists(db.get_bind(), link_fields[0].link_table_name)
        assert link_fields[0].config["target_table_id"] == target_tid


# ── DDL 物理列存在性验证 ──────────────────────────────


class TestFieldImportDDL:
    def test_import_creates_physical_columns(self, client, auth_headers, db):
        """克隆字段后，目标物理表应拥有对应的物理列."""
        from sqlalchemy import inspect

        from cndb.plugins.tables.models import DataTable

        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WSDDL"})
        wid = r.json()["id"]

        # 源表 + 2 个字段
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DDLSrc"},
        )
        src_tid = r.json()["id"]

        client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
            json={"name": "col_text", "field_type": "text", "order": 0},
        )
        client.post(
            f"/api/v1/workspaces/{wid}/tables/{src_tid}/fields",
            headers=auth_headers,
            json={"name": "col_num", "field_type": "number", "order": 1},
        )

        # 目标表
        r = client.post(
            f"/api/v1/workspaces/{wid}/tables",
            headers=auth_headers,
            json={"name": "DDLDst"},
        )
        dst_tid = r.json()["id"]

        client.post(
            f"/api/v1/workspaces/{wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True},
        )

        # 查物理列
        dst_table = db.get(DataTable, dst_tid)
        insp = inspect(db.get_bind())
        cols = {c["name"] for c in insp.get_columns(dst_table.db_table_name)}
        dst_fields = {f.db_column_name: f for f in dst_table.active_fields()}
        for col_name in dst_fields:
            assert col_name in cols, f"物理列 {col_name} 不存在于 {dst_table.db_table_name}"


# ── field_ops 单元测试（补 execute_field_import / generate_column_name / plan_field_import 覆盖率） ──


class TestFieldOpsCoverage:
    def test_plan_field_import_with_explicit_start_order(self, db):
        """plan_field_import 指定 start_order 时使用指定值."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.fields.field_ops import plan_field_import

        dst = DataTable(workspace_id=1, name="D", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        src_f = DataField(name="x", field_type="text", order=0)
        plan, skipped = plan_field_import(dst, [src_f], start_order=42)
        assert len(plan) == 1
        assert plan[0].order == 42
        assert len(skipped) == 0

    def test_plan_field_import_default_start_order(self, db):
        """plan_field_import start_order=None 时从最大 order+1 开始."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.fields.field_ops import plan_field_import

        dst = DataTable(workspace_id=1, name="D2", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()
        # 目标表已有一个 order=5 的字段
        existing = DataField(table_id=dst.id, name="exist", field_type="text", order=5)
        existing.ensure_db_name()
        db.add(existing)
        db.flush()

        src_f = DataField(name="new", field_type="text", order=0)
        plan, _skipped = plan_field_import(dst, [src_f])
        assert plan[0].order == 6  # max(5) + 1

    def test_execute_field_import_basic(self, db):
        """execute_field_import 基本路径（clone_fields_between_tables 的低级 API）."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.fields import field_ops as _fo

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_exec", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_exec", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        src_field = DataField(table_id=src.id, name="f1", field_type="text", order=0)
        src_field.ensure_db_name()
        db.add(src_field)
        db.commit()

        ddl_create(engine, dst)
        db.refresh(src_field)
        created = _fo.execute_field_import(engine, db, dst, [src_field])
        assert len(created) == 1
        assert created[0].name == "f1"
        assert created[0].db_column_name != src_field.db_column_name  # 独立列名

    def test_execute_field_import_skip_conflicts(self, db):
        """execute_field_import skip_conflicts=True 时跳过冲突."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.fields import field_ops as _fo

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_exec2", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_exec2", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        # 源表两个字段：dup / unique
        dup_src = DataField(table_id=src.id, name="dup", field_type="text", order=0)
        dup_src.ensure_db_name()
        unique_src = DataField(table_id=src.id, name="unique", field_type="text", order=1)
        unique_src.ensure_db_name()
        db.add_all([dup_src, unique_src])
        db.commit()
        db.refresh(dup_src)
        db.refresh(unique_src)

        # 目标表已有 dup
        dup_dst = DataField(table_id=dst.id, name="dup", field_type="text", order=0)
        dup_dst.ensure_db_name()
        db.add(dup_dst)
        db.commit()

        ddl_create(engine, dst)
        created = _fo.execute_field_import(engine, db, dst, [dup_src, unique_src], skip_conflicts=True)
        assert len(created) == 1
        assert created[0].name == "unique"

    def test_execute_field_import_empty_plan(self, db):
        """execute_field_import 所有字段都冲突时返回空列表."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.fields import field_ops as _fo

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_exec3", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_exec3", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        src_f = DataField(table_id=src.id, name="only", field_type="text", order=0)
        src_f.ensure_db_name()
        db.add(src_f)
        db.commit()
        db.refresh(src_f)

        # 目标表先建同名字段
        existing = DataField(table_id=dst.id, name="only", field_type="text", order=0)
        existing.ensure_db_name()
        db.add(existing)
        db.commit()
        ddl_create(engine, dst)

        # skip_conflicts=True 时返回空
        created = _fo.execute_field_import(engine, db, dst, [src_f], skip_conflicts=True)
        assert created == []

    def test_generate_column_name_uniqueness(self):
        """generate_column_name 返回唯一的列名."""
        from cndb.plugins.tables.services.fields.field_ops import generate_column_name

        names = {generate_column_name() for _ in range(100)}
        assert len(names) == 100
        for n in names:
            assert n.startswith("field_")

    def test_clone_with_unique_field_creates_index(self, db):
        """clone_fields_between_tables 克隆 is_unique=True 字段时物理加唯一索引."""
        from sqlalchemy import inspect

        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.fields import field_ops as _fo

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_uniq", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_uniq", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        src_f = DataField(table_id=src.id, name="code", field_type="text", is_unique=True, order=0)
        src_f.ensure_db_name()
        db.add(src_f)
        db.commit()
        db.refresh(src_f)

        ddl_create(engine, dst)
        created, _skipped = _fo.clone_fields_between_tables(engine, db, src, dst, field_ids=[src_f.id])
        assert len(created) == 1
        assert created[0].is_unique is True

        # 物理表上应该有唯一索引
        insp = inspect(engine)
        indexes = {idx["name"] for idx in insp.get_indexes(dst.db_table_name)}
        assert any("u_" in name or "uniq" in name.lower() for name in indexes)

    def test_link_field_no_target_table_id_skipped(self, db):
        """validate_link_targets_exist 遇到 link 字段 config.target_table_id=None 时跳过."""
        from cndb.plugins.tables.models import DataField
        from cndb.plugins.tables.services.fields.field_ops import validate_link_targets_exist

        # link 字段没有 target_table_id — 不应该报错
        bad_link = DataField(name="orphan", field_type="link", config={})
        # 不应该抛异常
        validate_link_targets_exist([bad_link], db)

    def test_clone_all_conflict_returns_empty(self, db):
        """clone_fields_between_tables skip_conflicts=True 且全部冲突时返回空."""
        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.fields import field_ops as _fo

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_allc", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_allc", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        src_f = DataField(table_id=src.id, name="x", field_type="text", order=0)
        src_f.ensure_db_name()
        db.add(src_f)
        db.commit()
        db.refresh(src_f)

        existing = DataField(table_id=dst.id, name="x", field_type="text", order=0)
        existing.ensure_db_name()
        db.add(existing)
        db.commit()
        ddl_create(engine, dst)

        created, skipped = _fo.clone_fields_between_tables(
            engine, db, src, dst, field_ids=[src_f.id], skip_conflicts=True
        )
        assert created == []
        assert len(skipped) == 1

    def test_execute_field_import_with_unique(self, db):
        """execute_field_import unique 字段时物理加唯一索引."""
        from sqlalchemy import inspect

        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.fields import field_ops as _fo

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_execu", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_execu", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        src_f = DataField(table_id=src.id, name="uniq", field_type="text", is_unique=True, order=0)
        src_f.ensure_db_name()
        db.add(src_f)
        db.commit()
        db.refresh(src_f)

        ddl_create(engine, dst)
        created = _fo.execute_field_import(engine, db, dst, [src_f])
        assert len(created) == 1

        insp = inspect(engine)
        indexes = {idx["name"] for idx in insp.get_indexes(dst.db_table_name)}
        assert any("u_" in n for n in indexes)

    def test_execute_field_import_ddl_failure_rollback(self, db):
        """execute_field_import DDL 失败时回滚并抛异常 (行 220-223)."""
        from unittest.mock import patch

        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.fields import field_ops as _fo

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_fail1", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_fail1", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        src_f = DataField(table_id=src.id, name="f", field_type="text", order=0)
        src_f.ensure_db_name()
        db.add(src_f)
        db.commit()
        db.refresh(src_f)

        ddl_create(engine, dst)

        with (
            patch("cndb.plugins.tables.services.fields.field_ops._ddl.add_column", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            _fo.execute_field_import(engine, db, dst, [src_f])

    def test_clone_between_tables_ddl_failure(self, db):
        """clone_fields_between_tables DDL 失败时回滚并抛异常 (行 279-281)."""
        from unittest.mock import patch

        from cndb.plugins.tables.models import DataField, DataTable
        from cndb.plugins.tables.services.core.ddl import create_table as ddl_create
        from cndb.plugins.tables.services.fields import field_ops as _fo

        engine = db.get_bind()

        src = DataTable(workspace_id=1, name="S_fail2", owner_id=1)
        src.ensure_db_name()
        db.add(src)
        db.flush()
        dst = DataTable(workspace_id=1, name="D_fail2", owner_id=1)
        dst.ensure_db_name()
        db.add(dst)
        db.flush()

        src_f = DataField(table_id=src.id, name="f", field_type="text", order=0)
        src_f.ensure_db_name()
        db.add(src_f)
        db.commit()
        db.refresh(src_f)

        ddl_create(engine, dst)

        with (
            patch("cndb.plugins.tables.services.fields.field_ops._ddl.add_column", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError, match="boom"),
        ):
            _fo.clone_fields_between_tables(engine, db, src, dst, field_ids=[src_f.id])


# ── 跨工作区权限收紧 ──────────────────────────────────


def _register_and_login(client, username: str, email: str) -> dict[str, str]:
    """注册 + 登录第二个用户，返回 auth headers."""
    r = client.post(
        "/api/v1/accounts/auth/register",
        json={"username": username, "email": email, "password": "passw0rd"},
    )
    assert r.status_code in (200, 201), r.text
    r = client.post(
        "/api/v1/accounts/auth/login",
        json={"login": username, "password": "passw0rd"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _create_table_with_field(client, headers: dict, ws_name: str, table_name: str, field_name: str) -> tuple[int, int]:
    """创建工作区 + 表 + 单字段，返回 (wid, tid)."""
    r = client.post("/api/v1/workspaces", headers=headers, json={"name": ws_name})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]
    r = client.post(f"/api/v1/workspaces/{wid}/tables", headers=headers, json={"name": table_name})
    assert r.status_code == 201, r.text
    tid = r.json()["id"]
    r = client.post(
        f"/api/v1/workspaces/{wid}/tables/{tid}/fields",
        headers=headers,
        json={"name": field_name, "field_type": "text", "order": 0},
    )
    assert r.status_code == 201, r.text
    return wid, tid


class TestCrossWorkspacePermission:
    def test_import_denied_without_source_workspace_access(self, client, auth_headers):
        """AC-1: 对源工作区无任何权限 → 400，detail 含源工作区名（含 preview_only）."""
        # user2 拥有源工作区
        headers2 = _register_and_login(client, "wsperm_other", "wsperm_other@example.com")
        _, src_tid = _create_table_with_field(client, headers2, "机密工作区", "SecretTable", "secret_col")

        # user1 在自己的工作区建目标表
        r = client.post("/api/v1/workspaces", headers=auth_headers, json={"name": "WSDST1"})
        dst_wid = r.json()["id"]
        r = client.post(f"/api/v1/workspaces/{dst_wid}/tables", headers=auth_headers, json={"name": "Dst"})
        dst_tid = r.json()["id"]

        r = client.post(
            f"/api/v1/workspaces/{dst_wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True},
        )
        assert r.status_code == 400, r.text
        assert "机密工作区" in r.json()["detail"]

        # preview_only 同样受限
        r = client.post(
            f"/api/v1/workspaces/{dst_wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True, "preview_only": True},
        )
        assert r.status_code == 400, r.text
        assert "机密工作区" in r.json()["detail"]

    def test_import_allowed_with_source_read_access(self, client, auth_headers):
        """AC-2: 同一用户拥有两个工作区（对源表有 READ）→ 跨工作区 preview + 引入成功."""
        _, src_tid = _create_table_with_field(client, auth_headers, "WS_SRC_X", "CrossSrc", "cross_name")
        dst_wid, dst_tid = _create_table_with_field(client, auth_headers, "WS_DST_X", "CrossDst", "dst_col")

        # preview：gap_analysis 可用且不创建（路由默认 201，preview 也是 201）
        r = client.post(
            f"/api/v1/workspaces/{dst_wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True, "preview_only": True},
        )
        assert r.status_code == 201, r.text
        assert r.json()["created"] == []
        assert r.json()["total_source_count"] == 1

        # 实际引入
        r = client.post(
            f"/api/v1/workspaces/{dst_wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": src_tid, "import_all_fields": True},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert len(body["created"]) == 1
        assert body["created"][0]["name"] == "cross_name"

    def test_import_denied_source_workspace_deleted_guard(self, client, auth_headers, db):
        """源工作区不存在（防御分支）→ 400，detail 不崩溃."""
        from cndb.plugins.tables.models import DataTable

        dst_wid, dst_tid = _create_table_with_field(client, auth_headers, "WS_GUARD", "GuardDst", "g_col")

        # 直插一个 workspace_id 指向不存在工作区的表
        ghost = DataTable(
            name="GhostSrc",
            workspace_id=999999,
            owner_id=None,
            trashed=False,
            description="",
            db_table_name="ghost_src_table",
        )
        db.add(ghost)
        db.commit()
        assert ghost.id is not None

        r = client.post(
            f"/api/v1/workspaces/{dst_wid}/tables/{dst_tid}/fields/import",
            headers=auth_headers,
            json={"source_table_id": ghost.id, "import_all_fields": True},
        )
        assert r.status_code == 400, r.text
        assert "未知" in r.json()["detail"]
