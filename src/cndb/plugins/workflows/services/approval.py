"""审批实例流转服务：提交建档、逐级推进、终态落库、待办查询.

事务与并发约定：
- 推进/终态用"乐观守卫 UPDATE"（WHERE status=pending AND current_node_id=期望值），
  影响行数为 0 即视为并发冲突，由路由映射 409；
- 链尾通过后先落库（rec.create_row）再回写 record_id，全程同一事务，
  落库抛 ValueError（字段漂移等）时由路由 rollback，实例保持 pending 并映射 409。
"""

from __future__ import annotations

import logging
from typing import Any, cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from cndb.plugins.accounts.models import User
from cndb.plugins.forms.models import FormDefinition
from cndb.plugins.tables.models import DataTable
from cndb.plugins.workflows.models import (
    APPROVAL_STATUS_APPROVED,
    APPROVAL_STATUS_PENDING,
    APPROVAL_STATUS_REJECTED,
    CHANGE_OP_CREATE,
    CHANGE_OP_DELETE,
    CHANGE_OP_UPDATE,
    NODE_TYPE_APPROVAL,
    ApprovalAction,
    ApprovalInstance,
    Workflow,
    WorkflowNode,
)
from cndb.plugins.workflows.services import graph as g
from cndb.plugins.workspaces.models import ROLE_RANK, Workspace, WorkspaceRole
from cndb.plugins.workspaces.permissions import get_member_role

logger = logging.getLogger(__name__)

ACTION_APPROVE = "approve"
ACTION_REJECT = "reject"


class ApprovalConflictError(RuntimeError):
    """审批状态冲突（非 pending / 并发推进 / 落库失败），映射 409."""


class ApprovalPermissionError(PermissionError):
    """当前用户不满足当前节点的审批角色阈值，映射 403."""


def _user_role_rank(db: Session, workspace_id: int, user: User) -> int:
    """用户在其工作区的角色等级；非成员为 -1."""
    workspace = db.get(Workspace, workspace_id)
    role = get_member_role(user, workspace, db) if workspace else None
    return ROLE_RANK[role] if role is not None else -1


def _satisfied(db: Session, workspace_id: int, user: User, approver_role: str) -> bool:
    """用户角色是否达到指定审批角色阈值."""
    if not approver_role:
        return False
    target = WorkspaceRole(approver_role)
    return _user_role_rank(db, workspace_id, user) >= ROLE_RANK[target]


def _locate_current(
    db: Session,
    instance: ApprovalInstance,
) -> WorkflowNode | None:
    """定位实例当前所在审批节点；节点悬空（图被重存）时回退链上首个审批节点."""
    node = db.get(WorkflowNode, instance.current_node_id) if instance.current_node_id else None
    if node is not None and node.workflow_id == instance.workflow_id:
        return node
    chain = g.chain_order(db, instance.workflow_id)
    return g.first_approval_node(chain)


def submit_for_approval(
    db: Session,
    form: FormDefinition,
    table: DataTable,
    workflow: Workflow,
    values: dict[str, Any],
    user: User,
) -> ApprovalInstance:
    """表单提交进入审批：创建 pending 实例并推进到链上首个审批节点.

    Args:
        db: 数据库会话（调用方负责 commit）。
        form: 提交来源表单定义。
        table: 表单绑定的数据表（终态落库目标）。
        workflow: 表单绑定的审批流。
        values: 经表单配置过滤/补默认值后的提交值快照。
        user: 提交人。

    Returns:
        新建的 ApprovalInstance（已 flush，未 commit）。

    Raises:
        ApprovalConflictError: 审批流图异常（无审批节点）。
    """
    chain = g.chain_order(db, workflow.id)
    first = g.first_approval_node(chain)
    if first is None:
        raise ApprovalConflictError("审批流图异常：未找到审批节点")
    instance = ApprovalInstance(
        workspace_id=form.workspace_id,
        workflow_id=workflow.id,
        form_id=form.id,
        table_id=table.id,
        values=values,
        current_node_id=first.id,
        current_approver_role=first.approver_role,
        status=APPROVAL_STATUS_PENDING,
        submitted_by=user.id if user else None,
    )
    db.add(instance)
    db.flush()
    return instance


def submit_change_request(
    db: Session,
    table: DataTable,
    workflow: Workflow,
    op: str,
    row_id: int | None,
    values: dict[str, Any],
    user: User,
) -> ApprovalInstance:
    """网格/表单编辑变更单提交：创建 pending 实例并推进到链上首个审批节点.

    与表单提交共用 ApprovalInstance 双载荷：form_id 为 NULL、op 指明
    create/update/delete，values 为新值快照（update 存增量）。

    防叠加守卫（行锁定的服务端保障）：同表同行已有在途变更单时拒绝，
    避免变更单叠加导致落库语义混乱。

    Args:
        db: 数据库会话（调用方负责 commit）。
        table: 变更目标数据表（须已开启「编辑需审批」）。
        workflow: 表绑定的审批流。
        op: 变更操作类型，见 CHANGE_OPS。
        row_id: update/delete 的目标行 id；create 为 None。
        values: 变更值快照。
        user: 提交人。

    Returns:
        新建的 ApprovalInstance（已 flush，未 commit）。

    Raises:
        ApprovalConflictError: 同行已有在途变更 / 审批流图异常。
    """
    if row_id is not None:
        existing = (
            db.query(ApprovalInstance)
            .filter(
                ApprovalInstance.table_id == table.id,
                ApprovalInstance.row_id == row_id,
                ApprovalInstance.status == APPROVAL_STATUS_PENDING,
                ApprovalInstance.op.isnot(None),
            )
            .first()
        )
        if existing is not None:
            raise ApprovalConflictError("该行已有在途审批，请等待审批结束后再提交")
    chain = g.chain_order(db, workflow.id)
    first = g.first_approval_node(chain)
    if first is None:
        raise ApprovalConflictError("审批流图异常：未找到审批节点")
    instance = ApprovalInstance(
        workspace_id=table.workspace_id,
        workflow_id=workflow.id,
        form_id=None,
        table_id=table.id,
        op=op,
        row_id=row_id,
        values=values,
        current_node_id=first.id,
        current_approver_role=first.approver_role,
        status=APPROVAL_STATUS_PENDING,
        submitted_by=user.id if user else None,
    )
    db.add(instance)
    db.flush()
    return instance


def act_on_instance(
    db: Session,
    instance_id: int,
    user: User,
    action: str,
    comment: str = "",
) -> ApprovalInstance:
    """对审批实例执行批准/驳回（乐观守卫，调用方负责 commit/rollback）.

    Args:
        db: 数据库会话。
        instance_id: 审批实例 id。
        user: 操作人（须满足当前节点审批角色阈值）。
        action: "approve" 或 "reject"。
        comment: 审批意见（可选）。

    Returns:
        推进后的 ApprovalInstance（未 commit）。

    Raises:
        ApprovalPermissionError: 角色不达标。
        ApprovalConflictError: 非 pending / 并发推进 / 链尾落库失败。
    """
    instance = db.get(ApprovalInstance, instance_id)
    if instance is None:
        raise ApprovalConflictError("审批实例不存在")
    if instance.status != APPROVAL_STATUS_PENDING:
        raise ApprovalConflictError("该实例已结束审批")

    node = _locate_current(db, instance)
    if node is None or node.node_type != NODE_TYPE_APPROVAL:
        raise ApprovalConflictError("未定位到当前审批节点")
    if not _satisfied(db, instance.workspace_id, user, node.approver_role):
        raise ApprovalPermissionError("您不满足当前节点的审批权限")

    acted_node_id = node.id
    if action == ACTION_REJECT:
        moved = _guarded_update(
            db,
            instance,
            {"status": APPROVAL_STATUS_REJECTED, "current_approver_role": ""},
        )
        if not moved:
            raise ApprovalConflictError("审批状态已变化，请刷新后重试")
        db.add(
            ApprovalAction(
                instance_id=instance.id, node_id=acted_node_id, action=action, comment=comment, acted_by=user.id
            )
        )
        db.flush()
        return instance

    # approve：推进到下一节点或链尾终态
    chain = g.chain_order(db, instance.workflow_id)
    idx = next((i for i, n in enumerate(chain) if n.id == node.id), -1)
    next_node = chain[idx + 1] if 0 <= idx < len(chain) - 1 else None
    if next_node is not None and next_node.node_type == NODE_TYPE_APPROVAL:
        moved = _guarded_update(
            db,
            instance,
            {"current_node_id": next_node.id, "current_approver_role": next_node.approver_role},
        )
        if not moved:
            raise ApprovalConflictError("审批状态已变化，请刷新后重试")
        db.add(
            ApprovalAction(
                instance_id=instance.id, node_id=acted_node_id, action=action, comment=comment, acted_by=user.id
            )
        )
        db.flush()
        return instance

    # 链尾：先做落库前置检查（表/目标行存在），再守卫置终态，最后按 op 落库。
    # 前置检查失败时实例从未离开 pending（可重试/可驳回），置终态后
    # 的落库失败仍走同事务整体回滚。
    table = db.get(DataTable, instance.table_id)
    if table is None:
        raise ApprovalConflictError("落库失败：目标数据表已不存在")
    _ensure_target_row(db, instance, table)
    moved = _guarded_update(db, instance, {"status": APPROVAL_STATUS_APPROVED})
    if not moved:
        raise ApprovalConflictError("审批状态已变化，请刷新后重试")
    row = _apply_final(db, instance, table)
    record_id = row.get("id") if isinstance(row, dict) else None
    db.execute(
        update(ApprovalInstance)
        .where(ApprovalInstance.id == instance.id)
        .values(record_id=int(record_id) if record_id is not None else None)
    )
    db.add(
        ApprovalAction(instance_id=instance.id, node_id=acted_node_id, action=action, comment=comment, acted_by=user.id)
    )
    db.flush()
    return instance


def _ensure_target_row(db: Session, instance: ApprovalInstance, table: DataTable) -> None:
    """update/delete 变更单落库前置检查：目标行须存在（审批期间可能已被删除）.

    检查置于守卫置终态之前，失败时实例从未离开 pending，
    可重试 / 可驳回（AC-10）；置终态后的落库失败另由事务回滚兜底。

    Raises:
        ApprovalConflictError: 目标行已不存在。
    """
    if instance.op not in (CHANGE_OP_UPDATE, CHANGE_OP_DELETE) or instance.row_id is None:
        return
    from cndb.plugins.tables.services.core import records as rec

    if rec.get_row(db.get_bind(), table, instance.row_id, db=db) is None:
        raise ApprovalConflictError("落库失败：目标行已不存在")


def _apply_final(db: Session, instance: ApprovalInstance, table: DataTable) -> dict[str, Any]:
    """审批链尾按载荷类型落库：变更单按 op 分派，表单提交等价 create.

    update/delete 落库前检查目标行存在（审批期间可能已被删除），
    不存在时抛 ApprovalConflictError，由路由映射 409 并整体回滚
    （实例保持 pending，AC-10 语义：可重试 / 可驳回）。

    Returns:
        落库结果行（delete 返回 {"id": row_id} 供 record_id 回写）。
    """
    from cndb.plugins.tables.services.core import records as rec

    op = instance.op or CHANGE_OP_CREATE
    if op == CHANGE_OP_DELETE:
        target = instance.row_id
        if target is None or not rec.trash_row(db.get_bind(), table, target, db=db):
            raise ApprovalConflictError("落库失败：目标行已不存在")
        return {"id": target}
    if op == CHANGE_OP_UPDATE:
        target = instance.row_id
        if target is None or rec.get_row(db.get_bind(), table, target, db=db) is None:
            raise ApprovalConflictError("落库失败：目标行已不存在")
        try:
            row = rec.update_row(db.get_bind(), table, target, dict(instance.values or {}), db=db)
        except ValueError as exc:
            raise ApprovalConflictError(f"落库失败：{exc}") from exc
        if row is None:
            raise ApprovalConflictError("落库失败：目标行已不存在")
        return row
    # create（含表单提交 op=None 的传统语义）
    try:
        row = rec.create_row(db.get_bind(), table, dict(instance.values or {}), db=db)
    except ValueError as exc:
        raise ApprovalConflictError(f"落库失败：{exc}") from exc
    if row is None:
        raise ApprovalConflictError("落库失败：创建行返回空")
    return row


def _guarded_update(
    db: Session,
    instance: ApprovalInstance,
    values: dict[str, Any],
) -> bool:
    """乐观守卫更新：仅当实例仍 pending 且停在当前节点时生效.

    Returns:
        是否命中（True = 推进成功）。
    """
    conditions = [
        ApprovalInstance.id == instance.id,
        ApprovalInstance.status == APPROVAL_STATUS_PENDING,
    ]
    if instance.current_node_id is None:
        conditions.append(ApprovalInstance.current_node_id.is_(None))
    else:
        conditions.append(ApprovalInstance.current_node_id == instance.current_node_id)
    result = cast(CursorResult[Any], db.execute(update(ApprovalInstance).where(*conditions).values(**values)))
    return bool(result.rowcount)


def list_instances(
    db: Session,
    workspace_id: int,
    scope: str,
    user: User,
    form_id: int | None = None,
    table_id: int | None = None,
) -> list[ApprovalInstance]:
    """按范围查询审批实例.

    Args:
        db: 数据库会话。
        workspace_id: 工作区 id。
        scope: "pending_for_me"=待我审批 / "mine"=我提交的。
        user: 当前用户。
        form_id: 可选，按表单过滤。
        table_id: 可选，按数据表过滤（网格行锁定/待审标识数据源）。

    Returns:
        实例列表（新→旧）。
    """
    q = db.query(ApprovalInstance).filter(ApprovalInstance.workspace_id == workspace_id)
    if form_id is not None:
        q = q.filter(ApprovalInstance.form_id == form_id)
    if table_id is not None:
        q = q.filter(ApprovalInstance.table_id == table_id)
    if scope == "mine":
        q = q.filter(ApprovalInstance.submitted_by == user.id)
    else:
        q = q.filter(ApprovalInstance.status == APPROVAL_STATUS_PENDING)
    items = q.order_by(ApprovalInstance.id.desc()).limit(200).all()
    if scope != "mine":
        items = [
            it
            for it in items
            if it.current_approver_role and _satisfied(db, workspace_id, user, it.current_approver_role)
        ]
    return items


def decorate_instance(db: Session, instance: ApprovalInstance) -> dict[str, Any]:
    """实例 → 响应字典（补工作流/表单/节点/提交人名称）."""
    workflow = db.get(Workflow, instance.workflow_id)
    form = db.get(FormDefinition, instance.form_id)
    node = db.get(WorkflowNode, instance.current_node_id) if instance.current_node_id else None
    submitter = db.get(User, instance.submitted_by) if instance.submitted_by else None
    return {
        "id": instance.id,
        "workspace_id": instance.workspace_id,
        "workflow_id": instance.workflow_id,
        "workflow_name": workflow.name if workflow else "",
        "form_id": instance.form_id,
        "form_name": form.name if form else "",
        "table_id": instance.table_id,
        "op": instance.op,
        "row_id": instance.row_id,
        "status": instance.status,
        "current_node_id": instance.current_node_id,
        "current_node_name": node.name if node else "",
        "current_approver_role": instance.current_approver_role,
        "submitted_by": instance.submitted_by,
        "submitted_by_name": (submitter.nickname or submitter.username) if submitter else "",
        "values": instance.values or {},
        "record_id": instance.record_id,
        "created_at": instance.created_at,
        "updated_at": instance.updated_at,
    }


__all__ = [
    "ACTION_APPROVE",
    "ACTION_REJECT",
    "ApprovalConflictError",
    "ApprovalPermissionError",
    "act_on_instance",
    "decorate_instance",
    "list_instances",
    "submit_change_request",
    "submit_for_approval",
]
