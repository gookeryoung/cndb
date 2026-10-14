"""「修改申请写模式」演示数据。

注入典型权限用户、直编开放/关闭两个演示工作区、修改申请与问题清单。"""

from __future__ import annotations

from typing import Any


def _seed_permission_demo(db: Any, engine: Any, owner: Any) -> None:
    """注入"修改申请写模式"演示数据：典型权限用户 + 修改申请 + 问题清单.

    覆盖双轨写入分派的全部典型工况，供人工核验写模式标注与提示适配：
    - 直编开放工作区（allow_edit=True）：editor 直编、viewer 走申请；
    - 直编关闭工作区（allow_edit=False）：editor 走申请、viewer+表成员 write 授权边界工况；
    - 申请状态覆盖：open / merged / merge 后自动 stale；
    - 问题清单登记已知的表成员授权边界行为（分派仅看工作区角色）。
    """
    import datetime as _dt

    from cndb.plugins.change_requests import services as cr_services
    from cndb.plugins.change_requests.models import ChangeItem
    from cndb.plugins.issues.models import (
        ISSUE_ACTION_CREATED,
        ISSUE_CATEGORY_QUESTION,
        ISSUE_CATEGORY_SUGGESTION,
        ISSUE_STATUS_CLOSED,
        ISSUE_STATUS_OPEN,
        Issue,
        IssueComment,
        IssueEvent,
    )
    from cndb.plugins.tables.models import DataField, DataTable, TableMember
    from cndb.plugins.tables.services.core.ddl import create_table
    from cndb.plugins.tables.services.core.records import create_row
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole

    def _demo_user(username: str, nickname: str) -> Any:
        from cndb.plugins.accounts.models import User

        u = User(username=username, nickname=nickname)
        u.set_password("perm1234")
        db.add(u)
        db.commit()
        db.refresh(u)
        print(f"[seed] 创建用户: {username} / perm1234  (角色: {nickname})")
        return u

    def _demo_table(ws: Any) -> Any:
        tbl = DataTable(workspace_id=ws.id, owner_id=owner.id, name="权限演示表", description="修改申请写模式演示数据")
        tbl.ensure_db_name()
        db.add(tbl)
        db.commit()
        db.refresh(tbl)
        for idx, (fname, ftype) in enumerate([("名称", "text"), ("数量", "number"), ("备注", "text")]):
            f = DataField(table_id=tbl.id, name=fname, field_type=ftype, order=idx)
            f.ensure_db_name()
            db.add(f)
        db.commit()
        create_table(engine, tbl)
        row_ids = []
        for values in [
            {"名称": "甲", "数量": 1, "备注": ""},
            {"名称": "乙", "数量": 2, "备注": ""},
            {"名称": "丙", "数量": 3, "备注": ""},
        ]:
            row = create_row(engine, tbl, values=values)
            if row is None:
                raise RuntimeError("create_row 返回空，seed 数据异常")
            row_ids.append(row["id"])
        print(f"[seed] 创建数据表: 权限演示表 (工作区: {ws.name}, 行数: {len(row_ids)})")
        return tbl, row_ids

    def _open_cr(table: Any, user: Any, op: str, row_id: int | None, values: dict[str, Any]) -> Any:
        """经服务层创建申请（base_values 服务端快照，与线上行为一致）."""
        return cr_services.create_dispatch_request(db, table, user, op, row_id, values)

    # ── 演示用户（四个典型权限工况） ──
    u_editor = _demo_user("perm_editor", "编辑者-直编工况")
    u_viewer = _demo_user("perm_viewer", "查看者-申请工况")
    u_review = _demo_user("perm_review", "编辑者-关闭直编工况")
    u_member = _demo_user("perm_member", "查看者+表成员授权边界")

    # ── 工作区 1：直编开放（editor 直接落库，viewer 自动生成申请） ──
    ws1_name = "权限演示-直编开放"
    ws1 = Workspace(name=ws1_name, description="editor 直编直存 / viewer 走修改申请", created_by_id=owner.id)
    db.add(ws1)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws1.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=ws1.id, user_id=u_editor.id, role=WorkspaceRole.EDITOR))
    db.add(WorkspaceMember(workspace_id=ws1.id, user_id=u_viewer.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(ws1)
    print(f"[seed] 创建工作区: {ws1_name} (allow_edit=True, owner: admin)")
    tbl1, rows1 = _demo_table(ws1)

    _open_cr(tbl1, u_viewer, "update", rows1[0], {"数量": 10})  # open：修改行 #甲
    _open_cr(tbl1, u_viewer, "delete", rows1[2], {})  # open：删除行 #丙
    print("[seed] 注入修改申请: 直编开放区 2 条 open（viewer 提交，待 owner/editor 合并）")

    # ── 工作区 2：直编关闭（editor 也走申请轨道） ──
    ws2_name = "权限演示-直编关闭"
    ws2 = Workspace(
        name=ws2_name,
        description="allow_edit=False：editor 与 viewer 写路径均自动生成修改申请",
        created_by_id=owner.id,
        allow_edit=False,
    )
    db.add(ws2)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws2.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.add(WorkspaceMember(workspace_id=ws2.id, user_id=u_review.id, role=WorkspaceRole.EDITOR))
    db.add(WorkspaceMember(workspace_id=ws2.id, user_id=u_member.id, role=WorkspaceRole.VIEWER))
    db.commit()
    db.refresh(ws2)
    print(f"[seed] 创建工作区: {ws2_name} (allow_edit=False, owner: admin)")
    tbl2, rows2 = _demo_table(ws2)

    # 同行双申请 → merge 其一，另一个自动 stale（基准过期演示）
    cr_kept = _open_cr(tbl2, u_review, "update", rows2[0], {"数量": 100})
    cr_stale = _open_cr(tbl2, u_review, "update", rows2[0], {"数量": 200})
    kept_item = db.query(ChangeItem).filter(ChangeItem.request_id == cr_kept.id).first()
    cr_services.merge_request(
        db,
        cr_kept,
        tbl2,
        owner,
        {kept_item.id: "apply"},
        "演示：合并后同行其余申请自动置 stale",
    )
    db.refresh(cr_stale)
    assert cr_stale.stale is True
    _open_cr(tbl2, u_review, "create", None, {"名称": "丁", "数量": 4, "备注": "新增行演示"})  # open
    print("[seed] 注入修改申请: 直编关闭区 1 条 merged + 1 条 stale + 1 条 open")

    # 表成员授权边界工况：工作区 viewer + TableMember write（分派仅看工作区角色，仍走申请轨道）
    db.add(TableMember(table_id=tbl2.id, user_id=u_member.id, role="write"))
    db.commit()
    print("[seed] 表成员授权: perm_member → 权限演示表 write（边界工况：仍走申请轨道）")

    # ── 问题清单（issues）：登记写模式相关已知问题与结论 ──
    now = _dt.datetime.now(_dt.UTC)
    issue1 = Issue(
        workspace_id=ws2.id,
        table_id=tbl2.id,
        title="工作区 viewer 获得表成员 write 授权后，编辑仍走修改申请轨道",
        description=(
            "复现：perm_member 在『权限演示-直编关闭』工作区为 viewer 角色，同时被授予"
            "『权限演示表』表成员 write 授权；其表格编辑仍返回 202 自动生成修改申请，"
            "与表级 write 授权预期不一致。"
        ),
        category=ISSUE_CATEGORY_QUESTION,
        status=ISSUE_STATUS_OPEN,
        created_by_id=u_member.id,
    )
    db.add(issue1)
    db.flush()
    db.add(IssueEvent(issue_id=issue1.id, action=ISSUE_ACTION_CREATED, actor_id=u_member.id, created_at=now))
    db.add(
        IssueComment(
            issue_id=issue1.id,
            content=(
                "现状确认：写路径双轨分派 can_write_directly 仅判定工作区角色"
                "（owner 恒直编 / editor 需 allow_edit / viewer 一律走申请），"
                "表成员授权不参与分派，仅作为表级动作权限在直编轨道内二次校验。"
            ),
            created_by_id=owner.id,
        )
    )

    issue2 = Issue(
        workspace_id=ws1.id,
        table_id=tbl1.id,
        title="admin 编辑表格未生成修改申请，新建申请提示与行为矛盾",
        description=(
            "修改申请页曾无条件提示『请直接在表格中编辑数据，系统会自动生成修改申请』，"
            "但 admin（owner）在表格中编辑直接落库成功，未生成任何申请。"
        ),
        category=ISSUE_CATEGORY_SUGGESTION,
        status=ISSUE_STATUS_CLOSED,
        created_by_id=u_viewer.id,
    )
    db.add(issue2)
    db.flush()
    db.add(IssueEvent(issue_id=issue2.id, action=ISSUE_ACTION_CREATED, actor_id=u_viewer.id, created_at=now))
    db.add(
        IssueComment(
            issue_id=issue2.id,
            content=(
                "已修复：申请列表接口返回 write_mode（direct/change_request/denied），"
                "列表页头部按写模式显示权限标注，新建按钮提示按模式适配——"
                "直编用户明确告知『编辑直接生效，不会生成修改申请』。"
            ),
            created_by_id=owner.id,
        )
    )
    db.commit()
    print("[seed] 注入问题清单: 2 条（表成员授权边界 open / 直编提示矛盾 closed）")
