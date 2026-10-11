"""表单与审批流演示种子（cli/seed_forms.py）端到端测试.

覆盖：
- 业务演示用户创建（密码/角色）
- 工作区成员注入与「低质量数据」跳过
- 审批流线性链图结构（start → approval* → end，角色阈值正确）
- 表单定义（绑定审批流 / 直接落库两种模式，field_config 与计划一致）
- 审批实例四种进度：待首审 / 待复审 / 已通过（落库回写 record_id）/ 已驳回
- 缺表优雅跳过不阻断
- API 层「待我审批」按角色阈值过滤
"""

from __future__ import annotations

import pytest

from cndb.cli.seed_forms import (
    _MEMBER_ROLES,
    _WS_PLANS,
    _add_workspace_members,
    _ensure_demo_users,
    _seed_workspace_plan,
    seed_forms_and_workflows,
)

# ── fixture：单工作区（出差统计表）+ 全量计划注入 ──────────


@pytest.fixture
def sales_ws_seed(db, db_engine):
    """建「某企业销售管理」工作区 + 出差统计表，跑全量表单/审批流种子."""
    from cndb.plugins.accounts.models import User
    from cndb.plugins.tables.models import DataField, DataTable
    from cndb.plugins.tables.services.core.ddl import create_table
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    owner = User(username="seed_owner", email="seed_owner@example.com", nickname="种子属主")
    owner.set_password("pass1234")
    db.add(owner)
    db.commit()
    db.refresh(owner)

    ws = Workspace(name="某企业销售管理", description="测试")
    db.add(ws)
    db.commit()
    db.refresh(ws)
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role="owner"))

    # 低质量数据工作区：验证成员注入跳过逻辑
    ws_lq = Workspace(name="低质量数据", description="治理演示")
    db.add(ws_lq)
    db.commit()
    db.refresh(ws_lq)

    tbl = DataTable(workspace_id=ws.id, owner_id=owner.id, name="出差统计", description="", order=1)
    tbl.ensure_db_name()
    db.add(tbl)
    db.commit()
    db.refresh(tbl)
    for idx, (fname, ftype, req) in enumerate(
        [
            ("出差事项", "text", True),
            ("出差日期", "date", False),
            ("出差地点", "text", False),
            ("参与人员", "text", False),
            ("交流内容", "text", False),
            ("备注", "text", False),
        ]
    ):
        f = DataField(table_id=tbl.id, name=fname, field_type=ftype, config={}, order=idx, required=req)
        f.ensure_db_name()
        db.add(f)
    db.commit()
    create_table(db_engine, tbl)

    ws_map = {"某企业销售管理": ws, "低质量数据": ws_lq}
    tables_map = {"某企业销售管理": {"出差统计": tbl}, "低质量数据": {}}

    counts = seed_forms_and_workflows(db, ws_map, tables_map)
    yield {"ws": ws, "ws_lq": ws_lq, "table": tbl, "counts": counts}


# ── 1. 演示用户与成员 ────────────────────────────────────


def test_demo_users_created(db):
    """4 个业务演示用户创建：昵称/角色/密码符合约定."""
    from cndb.plugins.accounts.models import User, UserRole

    _ensure_demo_users(db)
    for username, nickname, _ in [
        ("liuyang", "刘洋", ""),
        ("chenjing", "陈静", ""),
        ("zhouwei", "周伟", ""),
        ("xiaomei", "小梅", ""),
    ]:
        u = db.query(User).filter(User.username == username).first()
        assert u is not None, f"用户 {username} 应存在"
        assert u.nickname == nickname
        assert u.role == UserRole.USER.value
        assert u.check_password(f"{username}1234"), f"{username} 密码应为 <username>1234"


def test_ensure_demo_users_idempotent(db):
    """重复调用 _ensure_demo_users 不会重建用户."""
    users1 = _ensure_demo_users(db)
    users2 = _ensure_demo_users(db)
    assert users1["liuyang"].id == users2["liuyang"].id


def test_workspace_members_added(sales_ws_seed, db):
    """演示用户按固定角色加入业务工作区；低质量数据工作区被跳过."""
    from cndb.plugins.workspaces.models import WorkspaceMember

    ws = sales_ws_seed["ws"]
    members = {m.user.username: m.role for m in db.query(WorkspaceMember).filter_by(workspace_id=ws.id)}
    for username, role in _MEMBER_ROLES.items():
        assert members.get(username) == role, f"{username} 应以 {role} 加入工作区"

    lq_members = db.query(WorkspaceMember).filter_by(workspace_id=sales_ws_seed["ws_lq"].id).count()
    assert lq_members == 0, "低质量数据工作区不应添加演示成员"


# ── 2. 审批流图结构 ──────────────────────────────────────


def test_workflow_chain_structure(sales_ws_seed, db):
    """出差申请审批流为两级线性链，节点角色阈值正确."""
    from cndb.plugins.workflows.models import Workflow
    from cndb.plugins.workflows.services.graph import chain_order

    ws = sales_ws_seed["ws"]
    wf = db.query(Workflow).filter_by(workspace_id=ws.id, name="出差申请审批流").first()
    assert wf is not None

    chain = chain_order(db, wf.id)
    assert [n.node_type for n in chain] == ["start", "approval", "approval", "end"]
    assert chain[1].approver_role == "editor"
    assert chain[1].name == "部门主管审批"
    assert chain[2].approver_role == "admin"
    assert chain[2].name == "分管副总审批"


# ── 3. 表单定义 ──────────────────────────────────────────


def test_form_definitions_created(sales_ws_seed, db):
    """绑定审批流的表单与直接落库表单配置正确."""
    from cndb.plugins.forms.models import FormDefinition
    from cndb.plugins.workflows.models import Workflow

    ws = sales_ws_seed["ws"]
    travel = db.query(FormDefinition).filter_by(workspace_id=ws.id, name="出差申请单").first()
    assert travel is not None
    wf = db.query(Workflow).filter_by(workspace_id=ws.id, name="出差申请审批流").first()
    assert travel.approval_workflow_id == wf.id
    assert travel.table.name == "出差统计"
    names = [fc["field_name"] for fc in travel.field_config]
    assert names == ["出差事项", "出差日期", "出差地点", "参与人员", "交流内容", "备注"]
    assert next(fc for fc in travel.field_config if fc["field_name"] == "出差事项")["required"] is True
    assert travel.edit_role == "editor"
    assert travel.delete_role == "admin"

    # 员工表在本 fixture 中不存在 → 「新员工入职登记」应被优雅跳过
    onboard = db.query(FormDefinition).filter_by(workspace_id=ws.id, name="新员工入职登记").first()
    assert onboard is None


# ── 4. 审批实例各进度 ────────────────────────────────────


def test_instances_cover_all_progresses(sales_ws_seed, db):
    """4 条出差审批实例分别处于：待首审 / 待复审 / 已通过 / 已驳回."""
    from cndb.plugins.forms.models import FormDefinition
    from cndb.plugins.workflows.models import ApprovalInstance
    from cndb.plugins.workflows.services.graph import chain_order

    ws = sales_ws_seed["ws"]
    form = db.query(FormDefinition).filter_by(workspace_id=ws.id, name="出差申请单").first()
    instances = db.query(ApprovalInstance).filter_by(form_id=form.id).all()
    assert len(instances) == 4, f"应 4 条实例，实际 {len(instances)}"

    wf_chain = chain_order(db, instances[0].workflow_id)
    by_status = {}
    for inst in instances:
        by_status.setdefault(inst.status, []).append(inst)

    # 待首审：1 条，停在 editor 节点
    assert len(by_status.get("pending", [])) == 2
    first_node, second_node = wf_chain[1], wf_chain[2]
    at_first = [i for i in by_status["pending"] if i.current_node_id == first_node.id]
    at_second = [i for i in by_status["pending"] if i.current_node_id == second_node.id]
    assert len(at_first) == 1 and at_first[0].current_approver_role == "editor"
    assert len(at_second) == 1 and at_second[0].current_approver_role == "admin"

    # 已通过：落库回写 record_id，行真实存在
    approved = by_status["approved"]
    assert len(approved) == 1
    assert approved[0].record_id is not None
    from cndb.plugins.tables.services.core.records import get_row

    row = get_row(db.get_bind(), sales_ws_seed["table"], approved[0].record_id)
    assert row is not None
    assert row["出差事项"] == "深圳技术交流与产品演示"
    assert row["出差地点"] == "深圳"

    # 已驳回：驳回意见落流水
    rejected = by_status["rejected"]
    assert len(rejected) == 1
    from cndb.plugins.workflows.models import ApprovalAction

    actions = db.query(ApprovalAction).filter_by(instance_id=rejected[0].id).all()
    assert any(a.action == "reject" and "预算" in a.comment for a in actions)


def test_approved_instance_lands_row(sales_ws_seed, db):
    """counts 汇总：4 实例 / 1 已通过；审批流 1 条、表单 1 个（缺表表单跳过）."""
    counts = sales_ws_seed["counts"]
    assert counts["workflows"] == 1
    assert counts["forms"] == 1
    assert counts["instances"] == 4
    assert counts["approved"] == 1


# ── 5. 缺表优雅跳过 ──────────────────────────────────────


def test_seed_workspace_plan_missing_tables_no_raise(db, db_engine):
    """工作区无任何表时计划执行不抛错，表单/实例计数为 0."""
    from cndb.plugins.accounts.models import User
    from cndb.plugins.workspaces.models import Workspace

    user = db.query(User).filter_by(username="liuyang").first()
    ws = Workspace(name="空工作区", description="")
    db.add(ws)
    db.commit()
    db.refresh(ws)

    plan = _WS_PLANS[0]
    counts = _seed_workspace_plan(
        db, ws, {}, plan, {"liuyang": user, "chenjing": user, "zhouwei": user, "xiaomei": user}
    )
    assert counts["forms"] == 0
    assert counts["instances"] == 0
    # 审批流不依赖表，仍应创建成功
    assert counts["workflows"] == 1


# ── 6. API：待我审批按角色阈值过滤 ────────────────────────


def test_pending_for_me_filtered_by_role(sales_ws_seed, client, db):
    """admin 阈值实例只对待审角色达标者可见；viewer 小梅看不到任何待审."""
    from cndb.plugins.workspaces.models import Workspace

    ws = db.query(Workspace).filter_by(name="某企业销售管理").first()

    def _login(username: str) -> dict[str, str]:
        r = client.post(
            "/api/v1/accounts/auth/login",
            json={"login": username, "password": f"{username}1234"},
        )
        assert r.status_code == 200, r.text
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    # 周伟（admin 成员）：能看到停在 admin 节点的 1 条 + 停在 editor 节点的 1 条
    r = client.get(f"/api/v1/workspaces/{ws.id}/approvals?scope=pending_for_me", headers=_login("zhouwei"))
    assert r.status_code == 200, r.text
    items = r.json()
    assert len(items) == 2
    roles = {it["current_approver_role"] for it in items}
    assert roles == {"editor", "admin"}
    assert {it["form_name"] for it in items} == {"出差申请单"}

    # 小梅（viewer 成员）：角色低于 editor 阈值，看不到任何待审
    r = client.get(f"/api/v1/workspaces/{ws.id}/approvals?scope=pending_for_me", headers=_login("xiaomei"))
    assert r.status_code == 200, r.text
    assert r.json() == []


# ── 7. 计划完整性 ────────────────────────────────────────


def test_plans_cover_business_workspaces():
    """计划覆盖除低质量数据外的全部 5 个业务工作区."""
    assert {p["workspace"] for p in _WS_PLANS} == {
        "某企业销售管理",
        "项目管理",
        "科研项目管理",
        "某地区数据",
        "股票信息管理",
    }


def test_add_workspace_members_no_duplicate(db):
    """重复调用 _add_workspace_members 不会产生重复成员."""
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember

    users = _ensure_demo_users(db)
    ws = Workspace(name="成员幂等工作区", description="")
    db.add(ws)
    db.commit()
    db.refresh(ws)
    before = db.query(WorkspaceMember).filter_by(workspace_id=ws.id).count()
    _add_workspace_members(db, {"成员幂等工作区": ws}, users)
    _add_workspace_members(db, {"成员幂等工作区": ws}, users)
    after = db.query(WorkspaceMember).filter_by(workspace_id=ws.id).count()
    assert before == 0
    assert after == len(_MEMBER_ROLES)
