"""审批流图服务：校验 + 整图保存 + 链上遍历辅助.

形态约定：线性链 start → approval* → end，每个节点至多一个出边。
保存即整图覆盖（删旧节点/边再插新）；校验失败返回中文明细列表，由路由映射 400。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.plugins.workflows.models import (
    NODE_TYPE_APPROVAL,
    NODE_TYPE_END,
    NODE_TYPE_START,
    Workflow,
    WorkflowEdge,
    WorkflowNode,
)
from cndb.plugins.workflows.schemas.models import WorkflowEdgeSave, WorkflowNodeSave
from cndb.plugins.workspaces.models import WorkspaceRole

_ROLE_VALUES = {r.value for r in WorkspaceRole}


def validate_graph_payload(nodes: list[WorkflowNodeSave], edges: list[WorkflowEdgeSave]) -> list[str]:
    """校验审批流图载荷，返回错误明细列表（空列表 = 通过）.

    规则：
    - key 不得重复；edge 引用的 key 必须存在
    - start 节点恰一个；approval 节点至少一个且必须配置合法审批角色
    - 每个节点至多一个出边（线性链，拒绝分叉/环）
    - 从 start 沿出边可达 end，且所有节点都在链上（无游离节点）
    """
    errors: list[str] = []
    keys = [n.key for n in nodes]
    if len(keys) != len(set(keys)):
        errors.append("节点 key 重复")
    key_set = set(keys)
    for i, e in enumerate(edges):
        if e.source not in key_set:
            errors.append(f"edges[{i}].source 引用了不存在的节点 key '{e.source}'")
        if e.target not in key_set:
            errors.append(f"edges[{i}].target 引用了不存在的节点 key '{e.target}'")
    if errors:
        return errors

    starts = [n for n in nodes if n.node_type == NODE_TYPE_START]
    if len(starts) != 1:
        errors.append(f"start 节点必须恰有一个，当前 {len(starts)} 个")
    approvals = [n for n in nodes if n.node_type == NODE_TYPE_APPROVAL]
    if not approvals:
        errors.append("至少需要一个审批节点")
    for n in approvals:
        if not n.approver_role:
            errors.append(f"审批节点 '{n.key}' 未配置审批人角色")
        elif n.approver_role not in _ROLE_VALUES:
            errors.append(f"审批节点 '{n.key}' 的审批人角色非法: {n.approver_role}")
    ends = [n for n in nodes if n.node_type == NODE_TYPE_END]
    if len(ends) != 1:
        errors.append(f"end 节点必须恰有一个，当前 {len(ends)} 个")
    if errors:
        return errors

    # 出边唯一性 + 环/游离检测（沿 start 单向行走）
    out_edge: dict[str, str] = {}
    for e in edges:
        if e.source in out_edge:
            errors.append(f"节点 '{e.source}' 存在多个出边，线性链不允许分叉")
        else:
            out_edge[e.source] = e.target
    if errors:
        return errors

    assert starts and ends  # 上方已保证数量
    visited: list[str] = []
    seen: set[str] = set()
    cur: str | None = starts[0].key
    while cur is not None:
        if cur in seen:
            errors.append(f"链上检测到环：节点 '{cur}' 被重复访问")
            break
        seen.add(cur)
        visited.append(cur)
        cur = out_edge.get(cur)
    if not errors:
        end_key = ends[0].key
        if visited[-1] != end_key:
            errors.append("从 start 沿出边无法到达 end 节点")
        stray = [k for k in keys if k not in seen]
        for k in stray:
            errors.append(f"节点 '{k}' 不在 start→end 链上（游离节点）")
    return errors


def save_graph(
    db: Session,
    workflow: Workflow,
    nodes: list[WorkflowNodeSave],
    edges: list[WorkflowEdgeSave],
) -> Workflow:
    """整图覆盖保存：删旧节点/边，按载荷重建（校验由调用方先完成）.

    节点按载荷顺序插入，edges 的 key 引用转换为节点 id。
    注意：重存会更换节点 id，存量 pending 实例的 current_node_id 被
    SET NULL 置空（审批动作按首个审批节点兜底继续，见 services.approval）。
    """
    db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).delete()
    db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow.id).delete()
    db.flush()

    key_to_id: dict[str, int] = {}
    for i, n in enumerate(nodes):
        node = WorkflowNode(
            workflow_id=workflow.id,
            name=n.name or n.node_type,
            pos_x=n.pos_x if n.pos_x else i * 160,
            pos_y=n.pos_y,
            config={"node_type": n.node_type, "approver_role": n.approver_role},
        )
        db.add(node)
        db.flush()
        key_to_id[n.key] = node.id
    for e in edges:
        db.add(
            WorkflowEdge(
                workflow_id=workflow.id,
                source_node_id=key_to_id[e.source],
                target_node_id=key_to_id[e.target],
            )
        )
    db.flush()
    return workflow


def load_graph_dto(db: Session, workflow: Workflow) -> tuple[list[dict[str, Any]], list[dict[str, int]]]:
    """把 ORM 图转成响应 DTO 结构（nodes / edges 两个列表）."""
    nodes = [
        {
            "id": n.id,
            "name": n.name,
            "node_type": n.node_type,
            "approver_role": n.approver_role,
            "pos_x": n.pos_x,
            "pos_y": n.pos_y,
        }
        for n in sorted(workflow.nodes, key=lambda x: (x.pos_x, x.id))
    ]
    edges = [
        {"source": e.source_node_id, "target": e.target_node_id}
        for e in db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow.id).all()
    ]
    return nodes, edges


def chain_order(db: Session, workflow_id: int) -> list[WorkflowNode]:
    """按链序返回节点列表（start → ... → end）；图异常时返回空列表."""
    nodes = db.query(WorkflowNode).filter(WorkflowNode.workflow_id == workflow_id).all()
    if not nodes:
        return []
    edges = db.query(WorkflowEdge).filter(WorkflowEdge.workflow_id == workflow_id).all()
    by_id = {n.id: n for n in nodes}
    out_edge: dict[int, int] = {}
    for e in edges:
        if e.source_node_id in by_id and e.target_node_id in by_id:
            out_edge.setdefault(e.source_node_id, e.target_node_id)
    starts = [n for n in nodes if n.node_type == NODE_TYPE_START]
    if len(starts) != 1:
        return []
    chain: list[WorkflowNode] = []
    cur: int | None = starts[0].id
    seen: set[int] = set()
    while cur is not None and cur in by_id and cur not in seen:
        seen.add(cur)
        chain.append(by_id[cur])
        cur = out_edge.get(cur)
    return chain


def first_approval_node(chain: list[WorkflowNode]) -> WorkflowNode | None:
    """取链上第一个审批节点（无则 None）."""
    for n in chain:
        if n.node_type == NODE_TYPE_APPROVAL:
            return n
    return None


__all__ = [
    "chain_order",
    "first_approval_node",
    "load_graph_dto",
    "save_graph",
    "validate_graph_payload",
]
