"""派生字段（formula）：字段创建校验 / 读取期计算 / 只读口径."""

from __future__ import annotations

from sqlalchemy import select

from cndb.plugins.accounts.models import User
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


def _workspace_and_table(db, engine, owner: User) -> tuple[Workspace, DataTable]:
    ws = Workspace(name="派生字段工作区", created_by_id=owner.id)
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    table = DataTable(workspace_id=ws.id, name="明细表", owner_id=owner.id)
    table.ensure_db_name()
    db.add(table)
    db.commit()
    db.refresh(ws)
    db.refresh(table)
    for order, (name, ftype) in enumerate((("金额", "number"), ("数量", "number"), ("名称", "text"))):
        field = DataField(table_id=table.id, name=name, field_type=ftype, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(engine, table)
    return ws, table


def test_formula_field_create_and_read(client, auth_headers, db, db_engine):
    owner = db.execute(select(User).where(User.username == "testuser")).scalar_one()
    ws, table = _workspace_and_table(db, db_engine, owner)
    base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields"

    created = client.post(
        base,
        json={
            "name": "单价",
            "field_type": "formula",
            "config": {"formula": "round([金额] / [数量], 2)", "decimals": 2},
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    field = created.json()
    assert field["field_type"] == "formula"
    assert field["config"]["formula"] == "round([金额] / [数量], 2)"

    row = client.post(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
        json={"values": {"金额": 10, "数量": 3, "名称": "甲"}},
        headers=auth_headers,
    )
    assert row.status_code == 201, row.text
    listed = client.get(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records",
        headers=auth_headers,
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()["items"][0]["单价"] == 3.33
    fetched = client.get(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{row.json()['id']}",
        headers=auth_headers,
    )
    assert fetched.json()["单价"] == 3.33

    # 派生字段只读：整行回传公式值不会写入物理列，且后续读取仍按公式计算
    updated = client.patch(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{row.json()['id']}",
        json={"values": {"数量": 4, "单价": 999}},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    fetched = client.get(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{row.json()['id']}",
        headers=auth_headers,
    )
    assert fetched.json()["单价"] == 2.5


def test_formula_field_rejects_bad_formula_and_type_switch(client, auth_headers, db, db_engine):
    owner = db.execute(select(User).where(User.username == "testuser")).scalar_one()
    ws, table = _workspace_and_table(db, db_engine, owner)
    base = f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields"

    bad_ref = client.post(
        base,
        json={"name": "坏公式", "field_type": "formula", "config": {"formula": "[不存在] + 1"}},
        headers=auth_headers,
    )
    assert bad_ref.status_code == 400
    assert "不存在的字段" in bad_ref.text
    bad_syntax = client.post(
        base,
        json={"name": "坏语法", "field_type": "formula", "config": {"formula": "[金额] +"}},
        headers=auth_headers,
    )
    assert bad_syntax.status_code == 400

    physical = next(f for f in table.active_fields() if f.name == "金额")
    switched = client.patch(
        base + f"/{physical.id}",
        json={"field_type": "formula", "config": {"formula": "[数量] + 1"}},
        headers=auth_headers,
    )
    assert switched.status_code == 400
    assert "请新建派生字段" in switched.text
