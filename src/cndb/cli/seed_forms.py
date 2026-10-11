"""表单与审批流演示数据注入 — 依附 seed 主流程（drop_all 后重建，每次全新）.

为除「低质量数据」外的每个演示工作区注入：
1. 业务演示用户（刘洋/陈静/周伟/小梅）并按 editor/editor/admin/viewer 加入工作区，
   保证「提交 → 初审 → 终审」完整审批链可演示
2. 典型审批流（线性链 start → approval* → end），覆盖单级与两级审批
3. 典型表单（绑定数据表，可选绑定审批流），覆盖直接落库与审批后落库两种模式
4. 审批实例 + 动作流水，覆盖四种进度：待首审 / 待复审 / 已通过（落库回写 record_id）/ 已驳回

工作区缺表（如股票信息管理离线未建表）时优雅跳过，不阻断其它工作区。
"""

from __future__ import annotations

from itertools import pairwise
from typing import Any

from sqlalchemy.orm import Session

# ── 业务演示用户 ─────────────────────────────────────────

# (username, 昵称, 说明)；密码统一 <username>1234，与既有演示账号风格一致
_DEMO_USERS: list[tuple[str, str, str]] = [
    ("liuyang", "刘洋", "业务骨干（提交人）"),
    ("chenjing", "陈静", "部门主管（初审审批人）"),
    ("zhouwei", "周伟", "分管领导（终审审批人）"),
    ("xiaomei", "小梅", "普通员工（仅提交）"),
]

# 各工作区统一按此角色加入成员（owner = admin 账号已由主流程创建）
_MEMBER_ROLES: dict[str, str] = {
    "liuyang": "editor",
    "chenjing": "editor",
    "zhouwei": "admin",
    "xiaomei": "viewer",
}

# 「低质量数据」为数据治理演示工作区，不注入表单/审批流
_SKIP_WORKSPACES = {"低质量数据"}


# ── 各工作区演示计划（表单字段名与 examples/datasets 各 CSV 表头严格对齐） ──

_WS_PLANS: list[dict[str, Any]] = [
    {
        "workspace": "某企业销售管理",
        "workflows": [
            {
                "name": "出差申请审批流",
                "description": "出差申请两级审批：部门主管初审，分管副总终审，通过后自动登记到出差统计表",
                "approvals": [("部门主管审批", "editor"), ("分管副总审批", "admin")],
            },
        ],
        "forms": [
            {
                "name": "出差申请单",
                "table": "出差统计",
                "workflow": "出差申请审批流",
                "description": "员工出差申请入口，提交后进入两级审批，全部通过后自动登记到出差统计表",
                "use_role": "",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "出差事项", "required": True, "help_text": "一句话概括出差目的"},
                    {"field_name": "出差日期", "required": True},
                    {"field_name": "出差地点", "required": True},
                    {"field_name": "参与人员", "help_text": "多名人员用顿号分隔"},
                    {"field_name": "交流内容"},
                    {"field_name": "备注"},
                ],
            },
            {
                "name": "新员工入职登记",
                "table": "员工表",
                "description": "直接落库表单示例：录入即写入员工表，无需审批",
                "use_role": "editor",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "姓名", "required": True},
                    {"field_name": "工号", "required": True, "help_text": "按 E+三位流水号编制，如 E021"},
                    {"field_name": "部门", "required": True},
                    {"field_name": "职位"},
                    {"field_name": "入职日期", "required": True},
                    {"field_name": "手机号"},
                    {"field_name": "邮箱"},
                    {"field_name": "是否在职", "default_value": "是"},
                ],
            },
        ],
        "instances": [
            {
                "form": "出差申请单",
                "submitter": "xiaomei",
                "values": {
                    "出差事项": "风险排查",
                    "出差日期": "2026-10-20",
                    "出差地点": "南京",
                    "参与人员": "小梅",
                    "交流内容": "跟进南京重工风险排查应对计划的落地情况",
                    "备注": "高铁往返",
                },
                "steps": [],
            },
            {
                "form": "出差申请单",
                "submitter": "liuyang",
                "values": {
                    "出差事项": "客户回访",
                    "出差日期": "2026-10-22",
                    "出差地点": "上海",
                    "参与人员": "刘洋、陈静",
                    "交流内容": "陪同华中交通参展并收集数字孪生需求",
                },
                "steps": [("chenjing", "approve", "行程安排合理，同意")],
            },
            {
                "form": "出差申请单",
                "submitter": "xiaomei",
                "values": {
                    "出差事项": "深圳技术交流与产品演示",
                    "出差日期": "2026-10-15",
                    "出差地点": "深圳",
                    "参与人员": "小梅、刘洋",
                    "交流内容": "向南方电网演示数字孪生平台新版本",
                    "备注": "需借用演示样机",
                },
                "steps": [
                    ("chenjing", "approve", "同意"),
                    ("zhouwei", "approve", "批准，注意控制差旅成本"),
                ],
            },
            {
                "form": "出差申请单",
                "submitter": "xiaomei",
                "values": {
                    "出差事项": "合作洽谈",
                    "出差日期": "2026-11-03",
                    "出差地点": "新加坡",
                    "参与人员": "小梅",
                    "交流内容": "考察海外市场合作机会",
                    "备注": "需预支差旅费 3 万元",
                },
                "steps": [("chenjing", "reject", "海外行程预算超支，本期不建议安排")],
            },
        ],
    },
    {
        "workspace": "项目管理",
        "workflows": [
            {
                "name": "资源排期审批流",
                "description": "资源排期单级审批：资源主管确认后排期生效",
                "approvals": [("资源主管审批", "editor")],
            },
        ],
        "forms": [
            {
                "name": "资源排期申请",
                "table": "资源排期",
                "workflow": "资源排期审批流",
                "description": "各团队提交资源排期申请，主管确认后写入资源排期表",
                "use_role": "",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "排期编号", "required": True, "help_text": "按 RQ+三位流水号编制，如 RQ0101"},
                    {
                        "field_name": "团队",
                        "widget": "select",
                        "widget_config": {"options": ["研发组", "设计组", "测试组", "实施组"]},
                    },
                    {"field_name": "任务名称", "required": True},
                    {"field_name": "排期日期", "required": True},
                    {"field_name": "投入人天"},
                    {"field_name": "负责人"},
                    {
                        "field_name": "状态",
                        "widget": "select",
                        "widget_config": {"options": ["待确认", "已确认", "已取消"]},
                        "default_value": "待确认",
                    },
                ],
            },
            {
                "name": "待办事项登记",
                "table": "待办事项",
                "description": "直接落库表单示例：快速登记待办事项，无需审批",
                "use_role": "",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "编号", "required": True, "help_text": "按 TB+三位流水号编制，如 TB016"},
                    {
                        "field_name": "类别",
                        "widget": "radio",
                        "widget_config": {"options": ["需求", "设计", "开发", "测试", "部署", "文档", "沟通", "运维"]},
                    },
                    {"field_name": "事项", "required": True},
                    {"field_name": "责任人"},
                    {"field_name": "要求节点", "help_text": "完成时限"},
                    {"field_name": "备注"},
                ],
            },
        ],
        "instances": [
            {
                "form": "资源排期申请",
                "submitter": "liuyang",
                "values": {
                    "排期编号": "RQ0101",
                    "团队": "研发组",
                    "任务名称": "客户门户前端组件开发",
                    "排期日期": "2026-10-19",
                    "投入人天": 5,
                    "负责人": "陈立",
                    "状态": "待确认",
                },
                "steps": [],
            },
            {
                "form": "资源排期申请",
                "submitter": "xiaomei",
                "values": {
                    "排期编号": "RQ0102",
                    "团队": "测试组",
                    "任务名称": "灰度环境回归测试支持",
                    "排期日期": "2026-10-21",
                    "投入人天": 3,
                    "负责人": "赵倩",
                    "状态": "待确认",
                },
                "steps": [("chenjing", "approve", "排期无冲突，确认")],
            },
            {
                "form": "资源排期申请",
                "submitter": "xiaomei",
                "values": {
                    "排期编号": "RQ0103",
                    "团队": "实施组",
                    "任务名称": "生产环境服务器扩容",
                    "排期日期": "2026-10-26",
                    "投入人天": 2,
                    "负责人": "周明",
                    "状态": "待确认",
                },
                "steps": [("chenjing", "reject", "本月运维预算已冻结，下月再议")],
            },
        ],
    },
    {
        "workspace": "科研项目管理",
        "workflows": [
            {
                "name": "经费使用审批流",
                "description": "经费使用两级审批：课题负责人初审，科研管理处终审，通过后登记到科研经费表",
                "approvals": [("课题负责人审核", "editor"), ("科研管理处审批", "admin")],
            },
        ],
        "forms": [
            {
                "name": "经费使用申请",
                "table": "科研经费",
                "workflow": "经费使用审批流",
                "description": "课题组提交经费使用申请，两级审批通过后写入科研经费表",
                "use_role": "",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "经费编号", "required": True, "help_text": "按 JF+三位流水号编制，如 JF011"},
                    {"field_name": "课题编号", "required": True, "help_text": "如 KT2023001"},
                    {
                        "field_name": "预算科目",
                        "widget": "select",
                        "widget_config": {
                            "options": ["人员费", "协作费", "差旅费", "材料费", "测试化验加工费", "设备费"]
                        },
                    },
                    {"field_name": "预算金额_万元", "required": True},
                    {"field_name": "拨付日期"},
                    {
                        "field_name": "经费状态",
                        "widget": "select",
                        "widget_config": {"options": ["正常", "已结清"]},
                        "default_value": "正常",
                    },
                ],
            },
            {
                "name": "季度进展上报",
                "table": "项目进展",
                "description": "直接落库表单示例：课题组按季度上报项目进展",
                "use_role": "editor",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "进展编号", "required": True, "help_text": "按 JZ+三位流水号编制，如 JZ021"},
                    {"field_name": "课题编号", "required": True},
                    {"field_name": "报告季度", "required": True, "help_text": "格式如 2026Q4"},
                    {"field_name": "进展阶段"},
                    {"field_name": "进度百分比"},
                    {"field_name": "关键成果"},
                    {"field_name": "存在问题"},
                    {"field_name": "下一步计划"},
                    {"field_name": "报告日期"},
                ],
            },
        ],
        "instances": [
            {
                "form": "经费使用申请",
                "submitter": "liuyang",
                "values": {
                    "经费编号": "JF011",
                    "课题编号": "KT2023001",
                    "预算科目": "测试化验加工费",
                    "预算金额_万元": 12.5,
                    "拨付日期": "2026-10-18",
                    "经费状态": "正常",
                },
                "steps": [],
            },
            {
                "form": "经费使用申请",
                "submitter": "xiaomei",
                "values": {
                    "经费编号": "JF012",
                    "课题编号": "KT2023002",
                    "预算科目": "差旅费",
                    "预算金额_万元": 3.2,
                    "拨付日期": "2026-10-20",
                    "经费状态": "正常",
                },
                "steps": [("chenjing", "approve", "课题组审核通过，报科研管理处")],
            },
            {
                "form": "经费使用申请",
                "submitter": "liuyang",
                "values": {
                    "经费编号": "JF013",
                    "课题编号": "KT2023003",
                    "预算科目": "设备费",
                    "预算金额_万元": 25.0,
                    "拨付日期": "2026-10-15",
                    "经费状态": "正常",
                },
                "steps": [
                    ("chenjing", "approve", "设备清单已核对"),
                    ("zhouwei", "approve", "同意购置"),
                ],
            },
            {
                "form": "经费使用申请",
                "submitter": "xiaomei",
                "values": {
                    "经费编号": "JF014",
                    "课题编号": "KT2023001",
                    "预算科目": "材料费",
                    "预算金额_万元": 8.8,
                    "拨付日期": "2026-10-22",
                    "经费状态": "正常",
                },
                "steps": [("chenjing", "reject", "材料费超标，请压缩预算后重新提交")],
            },
        ],
    },
    {
        "workspace": "某地区数据",
        "workflows": [
            {
                "name": "观测数据修正审批流",
                "description": "气温观测补录单级审批：数据审核员确认后写入气温天气表",
                "approvals": [("数据审核员审批", "editor")],
            },
        ],
        "forms": [
            {
                "name": "气温观测补录",
                "table": "气温天气",
                "workflow": "观测数据修正审批流",
                "description": "补录或修正气温观测数据，审核通过后写入气温天气表",
                "use_role": "",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "日期", "required": True},
                    {"field_name": "城市", "required": True},
                    {"field_name": "最高温_℃"},
                    {"field_name": "最低温_℃"},
                    {"field_name": "湿度_%"},
                    {"field_name": "风速_m/s"},
                    {
                        "field_name": "天气",
                        "widget": "select",
                        "widget_config": {"options": ["晴", "多云", "阴", "小雨", "大雨", "雪"]},
                    },
                ],
            },
            {
                "name": "房价样本登记",
                "table": "房价预测",
                "description": "直接落库表单示例：录入房产样本用于房价预测分析",
                "use_role": "editor",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "面积_平米", "required": True},
                    {"field_name": "房间数"},
                    {"field_name": "楼层"},
                    {"field_name": "房龄_年"},
                    {"field_name": "距市中心_km"},
                    {
                        "field_name": "是否近地铁",
                        "widget": "radio",
                        "widget_config": {"options": [0, 1]},
                        "help_text": "1 = 近地铁，0 = 不近",
                    },
                    {
                        "field_name": "是否学区房",
                        "widget": "radio",
                        "widget_config": {"options": [0, 1]},
                        "help_text": "1 = 学区房，0 = 非学区房",
                    },
                    {"field_name": "城市", "required": True},
                    {"field_name": "房价_万元"},
                ],
            },
        ],
        "instances": [
            {
                "form": "气温观测补录",
                "submitter": "liuyang",
                "values": {
                    "日期": "2026-10-10",
                    "城市": "广州",
                    "最高温_℃": 31.5,
                    "最低温_℃": 24.2,
                    "湿度_%": 72,
                    "风速_m/s": 2.8,
                    "天气": "多云",
                },
                "steps": [],
            },
            {
                "form": "气温观测补录",
                "submitter": "xiaomei",
                "values": {
                    "日期": "2026-10-11",
                    "城市": "深圳",
                    "最高温_℃": 30.1,
                    "最低温_℃": 23.6,
                    "湿度_%": 78,
                    "风速_m/s": 3.2,
                    "天气": "晴",
                },
                "steps": [("chenjing", "approve", "数据与相邻站点一致，确认补录")],
            },
            {
                "form": "气温观测补录",
                "submitter": "xiaomei",
                "values": {
                    "日期": "2026-10-12",
                    "城市": "泸州",
                    "最高温_℃": 45.0,
                    "最低温_℃": -3.0,
                    "湿度_%": 5,
                    "风速_m/s": 18.6,
                    "天气": "晴",
                },
                "steps": [("chenjing", "reject", "单日温差超 40℃，疑似录入错误，请核对后重报")],
            },
        ],
    },
    {
        "workspace": "股票信息管理",
        "workflows": [
            {
                "name": "行情数据纠错审批流",
                "description": "行情纠错申报单级审批：数据管理员确认后写入行情表",
                "approvals": [("数据管理员审批", "editor")],
            },
        ],
        "forms": [
            {
                "name": "行情纠错申报",
                "table": "A股典型个股行情",
                "workflow": "行情数据纠错审批流",
                "description": "发现行情快照异常时申报纠错，审核通过后写入行情表",
                "use_role": "",
                "edit_role": "editor",
                "delete_role": "admin",
                "fields": [
                    {"field_name": "symbol", "required": True, "help_text": "交易所前缀+代码，如 sh600519"},
                    {"field_name": "stock_name", "required": True},
                    {"field_name": "current_price"},
                    {"field_name": "high_price"},
                    {"field_name": "low_price"},
                ],
            },
        ],
        "instances": [
            {
                "form": "行情纠错申报",
                "submitter": "liuyang",
                "values": {"symbol": "sh600519", "stock_name": "贵州茅台", "current_price": 1520.0},
                "steps": [],
            },
            {
                "form": "行情纠错申报",
                "submitter": "xiaomei",
                "values": {"symbol": "sz000001", "stock_name": "平安银行", "current_price": 11.8},
                "steps": [("chenjing", "approve", "与交易所快照核对一致")],
            },
            {
                "form": "行情纠错申报",
                "submitter": "xiaomei",
                "values": {"symbol": "sh688981", "stock_name": "中芯国际", "current_price": 0.01},
                "steps": [("chenjing", "reject", "价格明显异常，请核对数据源后重报")],
            },
        ],
    },
]


# ── 用户与成员 ───────────────────────────────────────────


def _ensure_demo_users(db: Session) -> dict[str, Any]:
    """创建 4 个业务演示用户（幂等：按 username 查重），返回 username -> User 映射."""
    from cndb.plugins.accounts.models import User, UserRole

    users: dict[str, Any] = {}
    for username, nickname, _desc in _DEMO_USERS:
        user = db.query(User).filter(User.username == username).first()
        if user is None:
            user = User(
                username=username,
                email=f"{username}@example.com",
                nickname=nickname,
                role=UserRole.USER.value,
            )
            user.set_password(f"{username}1234")
            db.add(user)
            db.commit()
            db.refresh(user)
            print(f"[seed-表单] 创建用户: {username} / {username}1234  ({nickname})")
        users[username] = user
    return users


def _add_workspace_members(db: Session, ws_map: dict[str, Any], users: dict[str, Any]) -> int:
    """把演示用户按固定角色加入各业务工作区（低质量数据除外），返回新增成员数."""
    from cndb.plugins.workspaces.models import WorkspaceMember

    added = 0
    for ws_name, ws in ws_map.items():
        if ws_name in _SKIP_WORKSPACES:
            continue
        for username, role in _MEMBER_ROLES.items():
            exists = (
                db.query(WorkspaceMember)
                .filter(WorkspaceMember.workspace_id == ws.id, WorkspaceMember.user_id == users[username].id)
                .first()
            )
            if exists is not None:
                continue
            db.add(WorkspaceMember(workspace_id=ws.id, user_id=users[username].id, role=role))
            added += 1
    db.commit()
    if added:
        print(f"[seed-表单] 添加工作区成员 {added} 条（liuyang/chenjing=editor, zhouwei=admin, xiaomei=viewer）")
    return added


# ── 审批流 / 表单 / 实例 ─────────────────────────────────


def _create_workflow(db: Session, ws: Any, spec: dict[str, Any], order: int) -> Any:
    """按计划创建审批流：Workflow + 线性链整图（复用图校验与保存服务）."""
    from cndb.plugins.workflows.models import Workflow
    from cndb.plugins.workflows.schemas.models import WorkflowEdgeSave, WorkflowNodeSave
    from cndb.plugins.workflows.services.graph import save_graph, validate_graph_payload

    approvals = spec["approvals"]
    node_saves = [WorkflowNodeSave(key="start", name="提交申请", node_type="start", pos_x=0, pos_y=100)]
    for i, (node_name, role) in enumerate(approvals, start=1):
        node_saves.append(
            WorkflowNodeSave(
                key=f"approval{i}",
                name=node_name,
                node_type="approval",
                approver_role=role,
                pos_x=i * 180,
                pos_y=100,
            )
        )
    node_saves.append(
        WorkflowNodeSave(key="end", name="结束", node_type="end", pos_x=(len(approvals) + 1) * 180, pos_y=100)
    )
    edge_saves = [WorkflowEdgeSave(source=a.key, target=b.key) for a, b in pairwise(node_saves)]

    errors = validate_graph_payload(node_saves, edge_saves)
    if errors:
        raise ValueError(f"审批流 '{spec['name']}' 图校验失败: {'; '.join(errors)}")

    wf = Workflow(workspace_id=ws.id, name=spec["name"], description=spec.get("description", ""), order=order)
    db.add(wf)
    db.commit()
    db.refresh(wf)
    save_graph(db, wf, node_saves, edge_saves)
    db.commit()
    print(f"[seed-表单] 创建审批流: {ws.name}/{wf.name}（{len(approvals)} 级审批）")
    return wf


def _create_form(
    db: Session,
    ws: Any,
    table: Any,
    spec: dict[str, Any],
    workflow_by_name: dict[str, Any],
    order: int,
) -> Any:
    """按计划创建表单定义；field_config 经 FormFieldConfig 校验保证与 API 载荷一致."""
    from cndb.plugins.forms.models import FormDefinition
    from cndb.plugins.forms.schemas.models import FormFieldConfig

    wf_name = spec.get("workflow")
    workflow = workflow_by_name.get(wf_name) if wf_name else None
    form = FormDefinition(
        workspace_id=ws.id,
        table_id=table.id,
        name=spec["name"],
        description=spec.get("description", ""),
        field_config=[FormFieldConfig(**f).model_dump(exclude_none=True) for f in spec.get("fields", [])],
        layout={"columns": 1},
        use_role=spec.get("use_role", ""),
        edit_role=spec.get("edit_role", ""),
        delete_role=spec.get("delete_role", ""),
        approval_workflow_id=workflow.id if workflow is not None else None,
        order=order,
    )
    db.add(form)
    db.commit()
    db.refresh(form)
    mode = f"审批后落库（{wf_name}）" if workflow is not None else "直接落库"
    print(f"[seed-表单] 创建表单: {ws.name}/{form.name} → {table.name}（{mode}）")
    return form


def _values_finalize_error(table: Any, values: dict[str, Any]) -> str | None:
    """预校验场景值能否通过审批终态落库校验；返回错误消息或 None.

    背景项目引擎（SQLite isolation_level=None）下语句即提交、ROLLBACK 无法
    撤销守卫更新，若终态落库校验失败会留下 status=approved 但无 record_id
    的脏实例 —— 因此提交前先按字段类型逐项校验，不合法场景直接跳过。
    """
    from cndb.plugins.tables.field_types import default_registry

    field_map = {f.name: f for f in table.fields if not f.trashed}
    for name, raw in values.items():
        field = field_map.get(name)
        if field is None:
            return f"字段 {name} 不存在"
        ft = default_registry.get(field.field_type)
        if ft is None:
            continue
        try:
            ft.validate_value(raw, field.config)
        except Exception as exc:
            return f"字段 {name}({field.field_type}) 值校验失败: {exc}"
    return None


def _run_instances(
    db: Session, users: dict[str, Any], form: Any, table: Any, workflow: Any, scenarios: list[dict[str, Any]]
) -> tuple[int, int]:
    """按场景用真实审批服务产生各进度实例；单个场景失败不阻断其它.

    Returns:
        (成功实例数, 已通过并落库的实例数).
    """
    from cndb.plugins.workflows.services.approval import act_on_instance, submit_for_approval

    created = 0
    finalized = 0
    for sc in scenarios:
        error = _values_finalize_error(table, sc["values"])
        if error is not None:
            print(f"[seed-表单] 审批实例跳过: {form.name} 场景 '{sc.get('submitter')}': {error}")
            continue
        try:
            submitter = users[sc["submitter"]]
            inst = submit_for_approval(db, form, table, workflow, dict(sc["values"]), submitter)
            db.commit()
            created += 1
            for actor_key, action, comment in sc.get("steps", []):
                act_on_instance(db, inst.id, users[actor_key], action, comment)
                db.commit()
            if inst.status == "approved":
                finalized += 1
            summary = next(iter(sc["values"].values()), "")
            print(f"[seed-表单] 审批实例: {form.name}『{summary}』→ {inst.status}")
        except Exception as exc:
            db.rollback()
            print(f"[seed-表单] 审批实例跳过: {form.name} 场景 '{sc.get('submitter')}': {exc}")
    return created, finalized


# ── 主入口 ───────────────────────────────────────────────


def _seed_workspace_plan(
    db: Session, ws: Any, tables: dict[str, Any], plan: dict[str, Any], users: dict[str, Any]
) -> dict[str, int]:
    """对单个工作区执行演示计划：审批流 → 表单 → 审批实例.

    Returns:
        {workflows, forms, instances, approved} 计数.
    """
    counts = {"workflows": 0, "forms": 0, "instances": 0, "approved": 0}

    workflow_by_name: dict[str, Any] = {}
    for i, wf_spec in enumerate(plan.get("workflows", [])):
        try:
            wf = _create_workflow(db, ws, wf_spec, order=i)
            workflow_by_name[wf_spec["name"]] = wf
            counts["workflows"] += 1
        except Exception as exc:
            db.rollback()
            print(f"[seed-表单] 审批流跳过: {ws.name}/{wf_spec['name']}: {exc}")

    forms_by_name: dict[str, Any] = {}
    for i, form_spec in enumerate(plan.get("forms", [])):
        table = tables.get(form_spec["table"])
        if table is None:
            print(f"[seed-表单] 表单跳过: {ws.name}/{form_spec['name']}（表 '{form_spec['table']}' 不存在）")
            continue
        try:
            form = _create_form(db, ws, table, form_spec, workflow_by_name, order=i)
            forms_by_name[form_spec["name"]] = form
            counts["forms"] += 1
        except Exception as exc:
            db.rollback()
            print(f"[seed-表单] 表单跳过: {ws.name}/{form_spec['name']}: {exc}")

    for sc in plan.get("instances", []):
        form = forms_by_name.get(sc["form"])
        if form is None:
            print(f"[seed-表单] 审批实例跳过：表单 '{sc['form']}' 不存在")
            continue
        workflow = next(
            (wf for wf in workflow_by_name.values() if wf.id == form.approval_workflow_id),
            None,
        )
        if workflow is None:
            print(f"[seed-表单] 审批实例跳过：表单 '{sc['form']}' 未绑定审批流")
            continue
        created, finalized = _run_instances(db, users, form, form.table, workflow, [sc])
        counts["instances"] += created
        counts["approved"] += finalized
    return counts


def seed_forms_and_workflows(db: Session, ws_map: dict[str, Any], tables_map: dict[str, Any]) -> dict[str, int]:
    """向各业务工作区注入典型表单、审批流与各进度审批实例.

    Args:
        db: 数据库会话。
        ws_map: 工作区显示名 -> Workspace 映射（来自 seed 主流程）。
        tables_map: 工作区显示名 -> {表名: DataTable} 映射。

    Returns:
        汇总计数 {workflows, forms, instances, approved}。
    """
    users = _ensure_demo_users(db)
    _add_workspace_members(db, ws_map, users)

    totals = {"workflows": 0, "forms": 0, "instances": 0, "approved": 0}
    for plan in _WS_PLANS:
        ws_name = plan["workspace"]
        ws = ws_map.get(ws_name)
        if ws is None:
            print(f"[seed-表单] 工作区 '{ws_name}' 不存在，跳过该工作区的表单/审批流注入")
            continue
        counts = _seed_workspace_plan(db, ws, tables_map.get(ws_name, {}), plan, users)
        for key in totals:
            totals[key] += counts[key]
    print(
        f"[seed-表单] 完成：{totals['workflows']} 条审批流、{totals['forms']} 个表单、"
        f"{totals['instances']} 条审批实例（其中已通过 {totals['approved']} 条）"
    )
    return totals


__all__ = ["_WS_PLANS", "seed_forms_and_workflows"]
