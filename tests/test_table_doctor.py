"""数据表体检（需求 0142 / 路线图 P0-1）：孤儿关联 / 失效 lookup 冗余列 / 孤儿排序索引 / 回收站.

覆盖证明：
- 干净库零误报（C1）
- 四类问题各能检出（C2-C5）
- `--fix` 幂等且不删业务行（C6）
- 范围收窄 + 报告结构（C7）
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable, DataView
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core import records as rec
from cndb.plugins.tables.services.core import table_doctor as doctor
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

pytestmark = pytest.mark.usefixtures("db")


@pytest.fixture
def owner(db):
    u = User(username="doctor_owner", nickname="Owner")
    u.set_password("passw0rd")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture
def ws(db, owner):
    w = Workspace(name="DoctorWS", created_by_id=owner.id)
    db.add(w)
    db.flush()
    db.add(WorkspaceMember(workspace_id=w.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(w)
    return w


def _table(db, ws, name: str, fields: list[tuple[str, str]]) -> DataTable:
    engine = db.get_bind()
    dt = DataTable(workspace_id=ws.id, name=name)
    dt.ensure_db_name()
    db.add(dt)
    db.flush()
    for order, (fname, ftype) in enumerate(fields):
        f = DataField(table_id=dt.id, name=fname, field_type=ftype, order=order)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    db.refresh(dt)
    ddl.create_table(engine, dt)
    return dt


# ── C1：干净库零误报 ─────────────────────────────────


def test_clean_workspace_reports_nothing(db, ws):
    table = _table(db, ws, "干净表", [("名称", "text")])
    engine = db.get_bind()
    rec.create_row(engine, table, {"名称": "A"}, db=db)

    report = doctor.diagnose(db, workspace_id=ws.id)

    assert report["tables_scanned"] == 1
    assert report["issues"] == 0
    assert report["orphan_links"] == []
    assert report["stale_lookup"] == []
    assert report["orphan_sort_indexes"] == []
    assert report["trash"] == []


# ── C2：孤儿关联关系 ─────────────────────────────────


def _link_setup(db, ws, name: str) -> tuple[DataTable, DataField, DataTable]:
    target = _table(db, ws, f"{name}目标", [("名称", "text")])
    src = _table(db, ws, f"{name}源", [("关联", "link")])
    link_field = next(f for f in src.fields if f.field_type == "link")
    link_field.config = {
        **(link_field.config or {}),
        "target_table_id": target.id,
        "display_field_id": target.fields[0].id,
    }
    db.commit()
    db.refresh(src)
    return src, next(f for f in src.fields if f.field_type == "link"), target


def test_orphan_link_detected_and_fixed(db, ws):
    src, link_field, target = _link_setup(db, ws, "孤儿")
    engine = db.get_bind()
    t_row = rec.create_row(engine, target, {"名称": "T"}, db=db)
    row = rec.create_row(engine, src, {"关联": [t_row["id"]]}, db=db)

    # 制造孤儿：直接把目标行物理删除（绕过 link 清理，模拟手工删库）
    sa_target = ddl.get_reflected_table(engine, target.db_table_name)
    with engine.begin() as conn:
        conn.execute(sa_target.delete().where(sa_target.c.id == t_row["id"]))

    report = doctor.diagnose(db, table_id=src.id)
    entry = report["orphan_links"][0]
    assert entry["count"] == 1
    assert entry["samples"][0] == {"field": link_field.name, "row_id": row["id"], "target_row_id": t_row["id"]}

    fixed = doctor.diagnose(db, table_id=src.id, fix=True)
    assert fixed["orphan_links"][0]["fixed"] is True
    assert doctor.diagnose(db, table_id=src.id)["orphan_links"] == []
    # 业务行没被删
    assert rec.get_row(engine, src, row["id"], db=db) is not None


def test_orphan_link_when_source_row_missing(db, ws):
    src, _link_field, target = _link_setup(db, ws, "孤儿源")
    engine = db.get_bind()
    t_row = rec.create_row(engine, target, {"名称": "T"}, db=db)
    row = rec.create_row(engine, src, {"关联": [t_row["id"]]}, db=db)

    sa_src = ddl.get_reflected_table(engine, src.db_table_name)
    with engine.begin() as conn:
        conn.execute(sa_src.delete().where(sa_src.c.id == row["id"]))

    report = doctor.diagnose(db, table_id=src.id)
    assert report["orphan_links"][0]["count"] == 1
    doctor.diagnose(db, table_id=src.id, fix=True)
    assert doctor.diagnose(db, table_id=src.id)["orphan_links"] == []


# ── C3：失效 lookup 冗余列 ───────────────────────────


def _lookup_setup(db, ws, name: str) -> tuple[DataTable, DataTable, dict[str, int]]:
    target = _table(db, ws, f"{name}被引用", [("名称", "text")])
    consumer = _table(db, ws, f"{name}引用", [("关联", "link"), ("取值", "lookup")])
    link_field = next(f for f in consumer.fields if f.field_type == "link")
    link_field.config = {
        **(link_field.config or {}),
        "target_table_id": target.id,
        "display_field_id": target.fields[0].id,
    }
    db.commit()
    db.refresh(consumer)
    link_field = next(f for f in consumer.fields if f.field_type == "link")
    lookup_field = next(f for f in consumer.fields if f.field_type == "lookup")
    lookup_field.config = {
        **(lookup_field.config or {}),
        "via_link_field_id": link_field.id,
        "source_field_id": target.fields[0].id,
    }
    db.commit()
    db.refresh(consumer)
    ddl.create_table(db.get_bind(), consumer)
    ddl.ensure_lookup_columns(db.get_bind(), consumer)
    return target, consumer, {"link": link_field.id, "lookup": lookup_field.id}


def test_stale_lookup_detected_and_fixed(db, ws):
    target, consumer, _ids = _lookup_setup(db, ws, "失效")
    engine = db.get_bind()
    t_row = rec.create_row(engine, target, {"名称": "旧值"}, db=db)
    row = rec.create_row(engine, consumer, {"关联": [t_row["id"]]}, db=db)

    # 制造失效：绕过写路径直接改 `_lk_*`（模拟历史不一致）
    sa = ddl.get_reflected_table(engine, consumer.db_table_name)
    lk_col = next(c.name for c in sa.columns if c.name.startswith("_lk_"))
    with engine.begin() as conn:
        # `_lk_*` 是 BLOB 列（SQLite 下无亲和性，保类型排序），必须写 bytes
        conn.execute(sa.update().where(sa.c.id == row["id"]).values({lk_col: "被人改坏".encode()}))

    report = doctor.diagnose(db, table_id=consumer.id)
    entry = report["stale_lookup"][0]
    assert entry["count"] == 1 and entry["samples"] == [row["id"]]

    # 只读体检不得改数据
    with engine.connect() as conn:
        assert conn.execute(select(sa.c[lk_col]).where(sa.c.id == row["id"])).scalar() == "被人改坏".encode()

    fixed = doctor.diagnose(db, table_id=consumer.id, fix=True)
    assert fixed["stale_lookup"][0]["fixed"] is True
    assert doctor.diagnose(db, table_id=consumer.id)["stale_lookup"] == []


# ── C4：孤儿排序索引 ─────────────────────────────────


def test_orphan_sort_index_detected_and_dropped(db, ws):
    table = _table(db, ws, "索引表", [("名称", "text"), ("数量", "number")])
    engine = db.get_bind()
    view = DataView(
        table_id=table.id,
        name="按数量",
        view_type="grid",
        visibility="table",
        scope_key=0,
        sortings=[{"field_name": "数量", "direction": "desc"}],
    )
    db.add(view)
    db.commit()
    ddl.ensure_sort_index(db, table, view.sortings)

    from sqlalchemy import inspect as sa_inspect

    names = {i["name"] for i in sa_inspect(engine).get_indexes(table.db_table_name)}
    assert any(n.startswith(f"ix_{table.db_table_name}_sort_") for n in names)
    # 仍在用 → 不报
    assert doctor.diagnose(db, table_id=table.id)["orphan_sort_indexes"] == []

    # 视图改用别的排序 → 旧索引变孤儿
    view.sortings = [{"field_name": "名称", "direction": "asc"}]
    db.commit()
    report = doctor.diagnose(db, table_id=table.id)
    assert report["orphan_sort_indexes"][0]["count"] == 1

    doctor.diagnose(db, table_id=table.id, fix=True)
    assert doctor.diagnose(db, table_id=table.id)["orphan_sort_indexes"] == []


# ── C5：回收站体积 ───────────────────────────────────


def test_trash_volume_reported(db, ws):
    table = _table(db, ws, "回收站表", [("名称", "text")])
    engine = db.get_bind()
    old = rec.create_row(engine, table, {"名称": "老"}, db=db)
    fresh = rec.create_row(engine, table, {"名称": "新"}, db=db)
    rec.trash_rows(engine, table, [old["id"], fresh["id"]], db=db)

    sa = ddl.get_reflected_table(engine, table.db_table_name)
    with engine.begin() as conn:
        conn.execute(sa.update().where(sa.c.id == old["id"]).values(_trashed_at=datetime.now(UTC) - timedelta(days=40)))

    entry = doctor.diagnose(db, table_id=table.id, days=30)["trash"][0]
    assert entry["trashed"] == 2
    assert entry["expired"] == 1  # 40 天前那条到期
    assert entry["unknown_time"] == 0  # 两条都有删除时间（时间未知口径见 rows_retention）
    assert entry["retention_days"] == 30
    # 体检不清理
    assert rec.get_row(engine, table, old["id"], db=db) is None
    with engine.connect() as conn:
        remaining = conn.execute(select(sa.c.id).where(sa.c.id.in_([old["id"], fresh["id"]]))).all()
        total = conn.execute(text(f'SELECT count(*) FROM "{table.db_table_name}"')).scalar()
    assert len(remaining) == 2  # 体检不清理行
    assert int(total) == 2


# ── C6 / C7：范围与报告 ──────────────────────────────


def test_scope_narrowing_and_report_shape(db, ws):
    a = _table(db, ws, "范围A", [("名称", "text")])
    b = _table(db, ws, "范围B", [("名称", "text")])
    engine = db.get_bind()
    rec.create_row(engine, a, {"名称": "A"}, db=db)
    rec.create_row(engine, b, {"名称": "B"}, db=db)

    assert doctor.diagnose(db, workspace_id=ws.id)["tables_scanned"] == 2
    assert doctor.diagnose(db, table_id=b.id)["tables_scanned"] == 1
    assert doctor.diagnose(db, workspace_id=999999)["tables_scanned"] == 0

    report = doctor.diagnose(db, workspace_id=ws.id)
    assert set(report) == {
        "fix",
        "tables_scanned",
        "orphan_links",
        "stale_lookup",
        "orphan_sort_indexes",
        "trash",
        "issues",
    }


# ── CLI ──────────────────────────────────────────────


class TestDoctorCli:
    def _ns(self, **kwargs) -> argparse.Namespace:
        base = {
            "tables_cmd": "doctor",
            "fix": False,
            "json": True,
            "workspace_id": None,
            "table_id": None,
            "days": None,
        }
        base.update(kwargs)
        return argparse.Namespace(**base)

    def test_cli_json_report(self, db, ws, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        _table(db, ws, "CLI表", [("名称", "text")])
        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)

        cli_tables.tables_command(self._ns(workspace_id=ws.id))

        payload = json.loads(capsys.readouterr().out)
        assert payload["tables_scanned"] == 1
        assert payload["fix"] is False

    def test_cli_human_output_with_fix_hint(self, db, ws, monkeypatch, capsys):
        from cndb.cli import tables as cli_tables

        table = _table(db, ws, "CLI脏表", [("名称", "text")])
        engine = db.get_bind()
        row = rec.create_row(engine, table, {"名称": "x"}, db=db)
        sa = ddl.get_reflected_table(engine, table.db_table_name)
        with engine.begin() as conn:
            conn.execute(sa.update().where(sa.c.id == row["id"]).values(_trashed=True, _trashed_at=datetime.now(UTC)))
        monkeypatch.setattr(cli_tables, "_get_session", lambda: db)

        cli_tables.tables_command(self._ns(json=False, workspace_id=ws.id))

        out = capsys.readouterr().out
        assert "体检（只读）" in out
        assert "回收站体积" in out
        # 回收站行不归 --fix 管，提示走 purge-trash（ADR 0139 D4）
        assert "purge-trash" in out


# ── 边界：无关联字段 / 无 lookup / 无索引 / 空表 ─────


def test_no_applicable_checks_returns_empty(db, ws):
    """纯文本表：四类检查都不适用 → 全空且不误报（C1 的负向面）."""
    table = _table(db, ws, "纯文本表", [("名称", "text")])
    engine = db.get_bind()
    rec.create_row(engine, table, {"名称": "A"}, db=db)

    report = doctor.diagnose(db, table_id=table.id)
    assert report["orphan_links"] == []
    assert report["stale_lookup"] == []
    assert report["orphan_sort_indexes"] == []
    assert report["trash"] == []
    assert report["issues"] == 0


def test_empty_table_reports_nothing(db, ws):
    """空表（0 行）时 lookup / 回收站检查直接返回，不抛错."""
    table = _table(db, ws, "空表", [("名称", "text"), ("取值", "lookup")])
    assert doctor.check_stale_lookup(db, db.get_bind(), table) is None
    assert doctor.check_trash(db.get_bind(), table, 30) is None


def test_sort_index_check_ignores_unresolvable_sort_fields(db, ws):
    """视图 sortings 里含不存在的字段 / 非物理列字段时，不误判为"需要索引"."""
    table = _table(db, ws, "索引边界", [("名称", "text")])
    engine = db.get_bind()
    db.add(
        DataView(
            table_id=table.id,
            name="怪排序",
            view_type="grid",
            visibility="table",
            scope_key=0,
            sortings=[{"field_name": "不存在", "direction": "asc"}, "not-a-dict"],
        )
    )
    db.commit()
    # 无索引 → 直接返回 None；更不会因为解析不了而抛错
    assert doctor.check_orphan_sort_indexes(db, engine, table) is None


def test_link_field_without_target_config_reports_nothing(db, ws):
    """关联字段未配置目标表时：目标行按"全部失效"处理，但空关系表不会报问题."""
    src = _table(db, ws, "未配置目标", [("关联", "link")])
    engine = db.get_bind()
    field = next(f for f in src.fields if f.field_type == "link")
    field.config = {}
    db.commit()
    db.refresh(src)
    assert doctor.check_orphan_links(db, engine, src) is None


def test_helper_edge_branches(db, ws):
    """内部辅助的边界：空 id 列表 / 目标表未配置 / 关联表缺失 → 安全返回."""
    engine = db.get_bind()
    table = _table(db, ws, "边界辅助", [("名称", "text"), ("关联", "link")])
    db.commit()
    db.refresh(table)
    link_field = next(f for f in table.fields if f.field_type == "link")

    # 空 id 列表 → 空集（不查库）
    assert doctor._valid_ids(engine, table.db_table_name, []) == set()

    # 目标表未配置 / 配置非法 → None
    link_field.config = {}
    db.commit()
    assert doctor._target_table_name(db, link_field) is None
    link_field.config = {"target_table_id": "not-int"}
    db.commit()
    assert doctor._target_table_name(db, link_field) is None

    # 关联表不存在 → None（不让体检崩掉）：先 DROP 关联表
    ddl.drop_link_table(engine, link_field)
    assert doctor._link_sa_table(engine, link_field) is None


def test_needed_index_signatures_skip_unresolvable(db, ws):
    """视图 sortings 里的脏项（非 dict / 未知字段 / 无物理列字段）被跳过而不是报错."""
    from cndb.plugins.tables.field_types import default_registry

    table = _table(db, ws, "签名边界", [("名称", "text"), ("公式列", "formula")])
    db.add(
        DataView(
            table_id=table.id,
            name="脏排序",
            view_type="grid",
            visibility="table",
            scope_key=0,
            sortings=[
                "not-a-dict",
                {"field_name": "不存在"},
                {"field_name": "公式列", "direction": "desc"},
                {"field_name": "名称", "direction": "desc"},
            ],
        )
    )
    db.commit()
    sigs = doctor._needed_index_signatures(db, table)
    # 只有「名称 desc」是可建索引的物理列，其余跳过
    assert len(sigs) == 1
    assert default_registry.get("formula") is not None


def test_cli_human_output_with_issues_prints_fix_hint(db, ws, monkeypatch, capsys):
    """有问题时人读输出列出分节并提示 --fix（不误报"已修复"）."""
    from cndb.cli import tables as cli_tables

    src = _table(db, ws, "CLI孤儿源", [("关联", "link")])
    target = _table(db, ws, "CLI孤儿目标", [("名称", "text")])
    engine = db.get_bind()
    field = next(f for f in src.fields if f.field_type == "link")
    field.config = {**(field.config or {}), "target_table_id": target.id}
    db.commit()
    db.refresh(src)
    t_row = rec.create_row(engine, target, {"名称": "T"}, db=db)
    rec.create_row(engine, src, {"关联": [t_row["id"]]}, db=db)
    sa_target = ddl.get_reflected_table(engine, target.db_table_name)
    with engine.begin() as conn:
        conn.execute(sa_target.delete().where(sa_target.c.id == t_row["id"]))

    monkeypatch.setattr(cli_tables, "_get_session", lambda: db)
    cli_tables.tables_command(
        argparse.Namespace(tables_cmd="doctor", fix=False, json=False, workspace_id=ws.id, table_id=None, days=None)
    )
    out = capsys.readouterr().out
    assert "孤儿关联关系" in out
    assert "--fix" in out


def test_cli_missing_subcommand_exits(db, monkeypatch, capsys):
    """没有子命令时给出可用列表并退出码 2."""
    from cndb.cli import tables as cli_tables

    monkeypatch.setattr(cli_tables, "_get_session", lambda: db)
    with pytest.raises(SystemExit) as exc:
        cli_tables.tables_command(argparse.Namespace(tables_cmd=None))
    assert exc.value.code == 2
    assert "缺少 tables 子命令" in capsys.readouterr().err
