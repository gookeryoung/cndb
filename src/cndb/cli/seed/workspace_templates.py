"""工作区模板种子：科研项目全生命周期管理（需求 0094）.

模板口径：三个阶段（立项申报 → 过程实施 → 结题验收），每个阶段绑定表单
（数据表结构）与文档规则（立项申请书 / 中期检查 / 结题报告等占位文档）。
内置模板由系统管理员维护，普通用户可复制后自定义。
"""

from __future__ import annotations

from typing import Any

RESEARCH_LIFECYCLE_SPEC: dict[str, Any] = {
    "forms": [
        {
            "key": "project_application",
            "name": "项目申报",
            "description": "立项申报阶段的主表，一条记录对应一个科研项目",
            "flow": {
                "list_fields": ["项目名称", "项目编号", "项目类别", "负责人", "起止时间", "预算金额（万元）"],
                "search_fields": ["项目名称", "项目编号", "负责人", "依托单位"],
                "form_groups": [
                    {"title": "基本信息", "fields": ["项目名称", "项目编号", "项目类别", "负责人", "依托单位"]},
                    {"title": "计划与预算", "fields": ["起止时间", "预算金额（万元）"]},
                    {"title": "研究内容", "fields": ["研究内容"]},
                ],
                "hints": {
                    "项目编号": "按「年度-类别-序号」填写，例如 2026-GJ-001",
                    "预算金额（万元）": "只填数字，单位万元",
                },
                "default_sort": {"field": "项目名称", "order": "asc"},
            },
            "fields": [
                {"name": "项目名称", "type": "text", "required": True, "is_unique": True},
                {"name": "项目编号", "type": "text", "required": True},
                {
                    "name": "项目类别",
                    "type": "select",
                    "required": True,
                    "config": {"options": ["国家级", "省部级", "市级", "横向课题", "自主立项"]},
                },
                {"name": "负责人", "type": "text", "required": True},
                {"name": "依托单位", "type": "text"},
                {"name": "起止时间", "type": "text"},
                {"name": "预算金额（万元）", "type": "number"},
                {"name": "研究内容", "type": "longtext"},
            ],
        },
        {
            "key": "project_progress",
            "name": "项目进展",
            "description": "过程实施阶段的定期进展填报",
            "flow": {
                "list_fields": ["所属项目", "填报日期", "进展状态", "完成度", "阶段进展"],
                "search_fields": ["阶段进展", "存在问题与措施"],
                "form_groups": [
                    {"title": "关联信息", "fields": ["所属项目", "填报日期", "进展状态", "完成度"]},
                    {"title": "进展说明", "fields": ["阶段进展", "存在问题与措施"]},
                ],
                "hints": {"完成度": "填写 0~100 的百分比（界面会显示为百分比）"},
                "default_sort": {"field": "填报日期", "order": "desc"},
            },
            "fields": [
                {
                    "name": "所属项目",
                    "type": "link",
                    "required": True,
                    "config": {"target_form": "project_application", "multiple": False},
                },
                {"name": "填报日期", "type": "date", "required": True},
                {
                    "name": "进展状态",
                    "type": "select",
                    "required": True,
                    "config": {"options": ["正常", "延期", "存在风险", "已完成"]},
                },
                {"name": "完成度", "type": "percentage"},
                {"name": "阶段进展", "type": "longtext", "required": True},
                {"name": "存在问题与措施", "type": "longtext"},
            ],
        },
        {
            "key": "project_budget",
            "name": "经费使用",
            "description": "过程实施阶段的经费支出台账",
            "flow": {
                "list_fields": ["所属项目", "支出日期", "支出科目", "金额（元）", "用途说明", "凭证编号"],
                "search_fields": ["用途说明", "凭证编号"],
                "form_groups": [
                    {"title": "支出信息", "fields": ["所属项目", "支出日期", "支出科目", "金额（元）"]},
                    {"title": "说明与凭证", "fields": ["用途说明", "凭证编号"]},
                ],
                "hints": {"金额（元）": "只填数字，单位元"},
                "default_sort": {"field": "支出日期", "order": "desc"},
            },
            "fields": [
                {
                    "name": "所属项目",
                    "type": "link",
                    "required": True,
                    "config": {"target_form": "project_application", "multiple": False},
                },
                {"name": "支出日期", "type": "date", "required": True},
                {
                    "name": "支出科目",
                    "type": "select",
                    "required": True,
                    "config": {"options": ["设备费", "材料费", "测试化验加工费", "差旅费", "劳务费", "其他"]},
                },
                {"name": "金额（元）", "type": "number", "required": True},
                {"name": "用途说明", "type": "text"},
                {"name": "凭证编号", "type": "text"},
            ],
        },
        {
            "key": "project_closure",
            "name": "结题验收",
            "description": "结题验收阶段的结论与成果登记",
            "flow": {
                "list_fields": ["所属项目", "验收日期", "验收结论", "成果类型", "成果摘要"],
                "search_fields": ["成果摘要"],
                "form_groups": [
                    {"title": "验收信息", "fields": ["所属项目", "验收日期", "验收结论"]},
                    {"title": "成果登记", "fields": ["成果类型", "成果摘要"]},
                ],
                "hints": {"验收结论": "未通过时请补充整改计划"},
                "default_sort": {"field": "验收日期", "order": "desc"},
            },
            "fields": [
                {
                    "name": "所属项目",
                    "type": "link",
                    "required": True,
                    "config": {"target_form": "project_application", "multiple": False},
                },
                {"name": "验收日期", "type": "date", "required": True},
                {
                    "name": "验收结论",
                    "type": "select",
                    "required": True,
                    "config": {"options": ["通过", "整改后通过", "不通过"]},
                },
                {"name": "成果摘要", "type": "longtext"},
                {
                    "name": "成果类型",
                    "type": "multiselect",
                    "config": {"options": ["论文", "专利", "标准", "软件著作权", "样机", "报告"]},
                },
            ],
        },
        {
            "key": "expense_claim",
            "name": "经费报销",
            "description": "项目经费报销申请，审批通过后登记到经费使用台账",
            "fields": [
                {
                    "name": "所属项目",
                    "type": "link",
                    "required": True,
                    "config": {"target_form": "project_application", "multiple": False},
                },
                {"name": "报销人", "type": "text", "required": True},
                {"name": "报销日期", "type": "date", "required": True},
                {
                    "name": "报销科目",
                    "type": "select",
                    "required": True,
                    "config": {"options": ["设备费", "材料费", "测试化验加工费", "差旅费", "劳务费", "其他"]},
                },
                {"name": "金额（元）", "type": "number", "required": True},
                {"name": "报销事由", "type": "longtext", "required": True},
                {
                    "name": "审批状态",
                    "type": "select",
                    "required": True,
                    "config": {"options": ["待审批", "已通过", "已驳回"]},
                },
                {"name": "审批意见", "type": "text"},
            ],
            "flow": {
                "list_fields": ["所属项目", "报销日期", "报销科目", "金额（元）", "审批状态"],
                "search_fields": ["报销人", "报销事由", "审批意见"],
                "form_groups": [
                    {"title": "报销信息", "fields": ["所属项目", "报销人", "报销日期", "报销科目", "金额（元）"]},
                    {"title": "事由与审批", "fields": ["报销事由", "审批状态", "审批意见"]},
                ],
                "hints": {"金额（元）": "只填数字，单位元", "审批状态": "审批完成后回填"},
                "default_values": {"审批状态": "待审批"},
                "default_sort": {"field": "报销日期", "order": "desc"},
            },
        },
        {
            "key": "achievement_registry",
            "name": "成果登记",
            "description": "项目成果登记与归档清单维护",
            "fields": [
                {
                    "name": "所属项目",
                    "type": "link",
                    "required": True,
                    "config": {"target_form": "project_application", "multiple": False},
                },
                {"name": "成果名称", "type": "text", "required": True},
                {
                    "name": "成果类型",
                    "type": "multiselect",
                    "config": {"options": ["论文", "专利", "标准", "软件著作权", "样机", "报告"]},
                },
                {"name": "完成人", "type": "text"},
                {"name": "登记日期", "type": "date"},
                {"name": "归档位置", "type": "text"},
                {"name": "备注", "type": "longtext"},
            ],
            "flow": {
                "list_fields": ["所属项目", "成果名称", "成果类型", "完成人", "登记日期"],
                "search_fields": ["成果名称", "完成人", "备注"],
                "form_groups": [
                    {"title": "成果信息", "fields": ["所属项目", "成果名称", "成果类型", "完成人"]},
                    {"title": "归档信息", "fields": ["登记日期", "归档位置", "备注"]},
                ],
                "hints": {"成果类型": "可多选；论文 / 专利 / 标准等"},
                "default_sort": {"field": "登记日期", "order": "desc"},
            },
        },
        {
            "key": "project_change",
            "name": "项目变更",
            "description": "项目负责人 / 周期 / 预算等变更申请与审批",
            "fields": [
                {
                    "name": "所属项目",
                    "type": "link",
                    "required": True,
                    "config": {"target_form": "project_application", "multiple": False},
                },
                {
                    "name": "变更类型",
                    "type": "select",
                    "required": True,
                    "config": {"options": ["负责人变更", "周期变更", "预算变更", "研究内容变更", "其他"]},
                },
                {"name": "申请日期", "type": "date", "required": True},
                {"name": "变更内容", "type": "longtext", "required": True},
                {"name": "变更原因", "type": "longtext"},
                {
                    "name": "审批状态",
                    "type": "select",
                    "required": True,
                    "config": {"options": ["待审批", "已通过", "已驳回"]},
                },
            ],
            "flow": {
                "list_fields": ["所属项目", "变更类型", "申请日期", "审批状态"],
                "search_fields": ["变更内容", "变更原因"],
                "form_groups": [
                    {"title": "变更申请", "fields": ["所属项目", "变更类型", "申请日期"]},
                    {"title": "变更说明与审批", "fields": ["变更内容", "变更原因", "审批状态"]},
                ],
                "default_values": {"审批状态": "待审批"},
                "default_sort": {"field": "申请日期", "order": "desc"},
            },
        },
    ],
    "documents": [
        {
            "key": "proposal_doc",
            "title": "立项申请书",
            "required": True,
            "naming": "{项目名称}-立项申请书",
            "content": "# 立项申请书\n\n## 一、项目基本信息\n\n## 二、研究背景与意义\n\n## 三、研究目标与内容\n\n## 四、技术路线与实施方案\n\n## 五、预期成果\n\n## 六、经费预算\n",
        },
        {
            "key": "midterm_doc",
            "title": "中期检查报告",
            "required": True,
            "naming": "{项目名称}-中期检查报告",
            "content": "# 中期检查报告\n\n## 一、计划执行情况\n\n## 二、阶段性成果\n\n## 三、经费使用情况\n\n## 四、存在问题与下一步计划\n",
        },
        {
            "key": "budget_doc",
            "title": "经费决算表",
            "required": True,
            "naming": "{项目名称}-经费决算表",
            "content": "# 经费决算表\n\n| 科目 | 预算金额 | 实际支出 | 差异说明 |\n|---|---|---|---|\n| 设备费 | | | |\n| 材料费 | | | |\n| 差旅费 | | | |\n| 劳务费 | | | |\n",
        },
        {
            "key": "closure_doc",
            "title": "结题报告",
            "required": True,
            "naming": "{项目名称}-结题报告",
            "content": "# 结题报告\n\n## 一、项目概况\n\n## 二、任务完成情况\n\n## 三、主要成果\n\n## 四、经费使用情况\n\n## 五、后续工作建议\n",
        },
        {
            "key": "archive_doc",
            "title": "成果归档清单",
            "required": False,
            "naming": "{项目名称}-成果归档清单",
            "content": "# 成果归档清单\n\n| 序号 | 成果名称 | 类型 | 存放位置 | 备注 |\n|---|---|---|---|---|\n",
        },
    ],
    "flows": [
        {
            "key": "project_lifecycle",
            "name": "科研项目全生命周期",
            "description": "从立项申报、过程实施到结题验收的主流程",
            "steps": [
                {"key": "apply", "name": "立项申报", "form": "project_application", "documents": ["proposal_doc"]},
                {"key": "progress", "name": "进展填报", "form": "project_progress", "documents": ["midterm_doc"]},
                {"key": "budget", "name": "经费执行", "form": "project_budget", "documents": ["budget_doc"]},
                {
                    "key": "closure",
                    "name": "结题验收",
                    "form": "project_closure",
                    "documents": ["closure_doc", "archive_doc"],
                },
            ],
        },
        {
            "key": "expense_reimbursement",
            "name": "经费报销",
            "description": "报销申请 → 审批确认 → 财务入账",
            "steps": [
                {"key": "claim", "name": "填报报销", "form": "expense_claim"},
                {"key": "approve", "name": "审批确认", "description": "项目负责人 / 财务审核报销事由与金额"},
                {"key": "post", "name": "财务入账", "form": "project_budget", "documents": ["budget_doc"]},
            ],
        },
        {
            "key": "achievement_registration",
            "name": "成果登记",
            "description": "成果登记 → 归档确认",
            "steps": [
                {"key": "register", "name": "登记成果", "form": "achievement_registry"},
                {
                    "key": "archive",
                    "name": "归档确认",
                    "description": "核对成果原件与归档清单",
                    "documents": ["archive_doc"],
                },
            ],
        },
        {
            "key": "project_change",
            "name": "项目变更",
            "description": "变更申请 → 审批生效",
            "steps": [
                {"key": "submit", "name": "提交变更", "form": "project_change"},
                {"key": "approve", "name": "审批生效", "description": "管理部门审批通过后更新项目信息"},
            ],
        },
    ],
    "stages": [
        {
            "key": "proposal",
            "name": "立项申报",
            "description": "完成项目申报表填写与立项申请书撰写，通过评审后进入实施阶段",
            "order": 1,
            "forms": ["project_application"],
            "documents": ["proposal_doc"],
        },
        {
            "key": "execution",
            "name": "过程实施",
            "description": "按计划开展研究，定期填报进展与经费使用，提交中期检查与经费决算",
            "order": 2,
            "forms": ["project_progress", "project_budget"],
            "documents": ["midterm_doc", "budget_doc"],
        },
        {
            "key": "completion",
            "name": "结题验收",
            "description": "提交结题报告与成果归档清单，完成验收登记",
            "order": 3,
            "forms": ["project_closure"],
            "documents": ["closure_doc", "archive_doc"],
        },
    ],
}

TEMPLATE_NAME = "科研项目全生命周期管理"
TEMPLATE_CATEGORY = "科研管理"


def _seed_research_template(db: Any, owner_id: int | None) -> int:
    """写入内置科研模板（含 v1 版本快照）；同名已存在则跳过."""
    from cndb.plugins.workspaces.models import WorkspaceTemplate, WorkspaceTemplateRevision

    existing = db.query(WorkspaceTemplate).filter(WorkspaceTemplate.name == TEMPLATE_NAME).first()
    if existing is not None:
        return 0
    template = WorkspaceTemplate(
        name=TEMPLATE_NAME,
        description=(
            "覆盖科研项目立项、实施、结题三个阶段，并提供项目全生命周期 / 经费报销 / 成果登记 /"
            " 项目变更四条端到端流程；内置申报 / 进展 / 经费 / 结题 / 报销 / 成果 / 变更七张表单，"
            "以及立项申请书、中期检查、经费决算、结题报告等文档规则，阶段推进按门禁校验。"
        ),
        category=TEMPLATE_CATEGORY,
        modules=["tables", "documents", "design"],
        spec=RESEARCH_LIFECYCLE_SPEC,
        version=1,
        is_builtin=True,
        created_by_id=owner_id,
        updated_by_id=owner_id,
    )
    db.add(template)
    db.flush()
    db.add(
        WorkspaceTemplateRevision(
            template_id=template.id,
            version=1,
            spec=RESEARCH_LIFECYCLE_SPEC,
            change_summary="内置科研项目生命周期模板",
            created_by_id=owner_id,
        )
    )
    db.commit()
    print(f"[seed] 创建工作区模板: {TEMPLATE_NAME} (id={template.id})")
    return 1


EXAMPLE_WORKSPACE_NAME = "科研项目管理（模板示例）"


def _seed_research_example(db: Any, owner: Any, template: Any) -> int:
    """用科研模板建一个示例工作区，并写入各阶段的典型记录 / 文档内容.

    数据流程模块（需求 0095）需要一个可直接体验的真实工作区：立项申报表 3 个项目、
    过程实施 3 条进展 + 4 条经费、结题验收 1 条结论，阶段文档填入示例正文。
    """
    from cndb.plugins.documents.models import Document
    from cndb.plugins.documents.services.content import update_content
    from cndb.plugins.tables.models import DataTable
    from cndb.plugins.tables.services.core.records import create_row
    from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole, WorkspaceVisibility
    from cndb.plugins.workspaces.services.templates.engine import apply_spec_to_workspace
    from cndb.plugins.workspaces.services.templates.spec import normalize_spec

    if db.query(Workspace).filter(Workspace.name == EXAMPLE_WORKSPACE_NAME).first() is not None:
        return 0
    ws = Workspace(
        name=EXAMPLE_WORKSPACE_NAME,
        description="内置科研项目全生命周期模板的示例数据，可直接在「数据流程」中体验增删查改。",
        visibility=WorkspaceVisibility.MEMBER,
        tags=["科研", "示例", "模板"],
        modules=list(template.modules),
        template_id=template.id,
        created_by_id=owner.id,
    )
    db.add(ws)
    db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(ws)
    apply_spec_to_workspace(db, ws, normalize_spec(template.spec), owner, template=template, version=template.version)
    db.refresh(ws)

    def table(key: str) -> DataTable:
        table_id = (ws.template_state or {}).get("form_tables", {}).get(key)
        return db.get(DataTable, table_id)

    engine = db.get_bind()
    application = table("project_application")
    progress = table("project_progress")
    budget = table("project_budget")
    closure = table("project_closure")

    projects = [
        {
            "项目名称": "面向高端装备的智能监测关键技术研究",
            "项目编号": "2026-GJ-001",
            "项目类别": "国家级",
            "负责人": "张伟",
            "依托单位": "某大学机械工程学院",
            "起止时间": "2026-01 至 2028-12",
            "预算金额（万元）": 120,
            "研究内容": "研究复杂工况下高端装备多源信号采集、故障特征提取与剩余寿命预测方法，形成可移植的智能监测软件模块。",
        },
        {
            "项目名称": "工业软件可靠性评测方法研究",
            "项目编号": "2026-SB-014",
            "项目类别": "省部级",
            "负责人": "李娜",
            "依托单位": "某工业技术研究院",
            "起止时间": "2026-03 至 2027-12",
            "预算金额（万元）": 60,
            "研究内容": "建立工业软件可靠性指标体系与自动化评测流程，覆盖单元、集成与系统三个层级。",
        },
        {
            "项目名称": "多源异构数据融合平台",
            "项目编号": "2026-HX-007",
            "项目类别": "横向课题",
            "负责人": "王强",
            "依托单位": "某科技有限公司",
            "起止时间": "2026-02 至 2027-06",
            "预算金额（万元）": 45,
            "研究内容": "面向企业多业务系统，构建数据接入、清洗、主数据对齐与指标服务能力。",
        },
    ]
    created_projects: list[dict[str, Any]] = []
    for values in projects:
        row = create_row(engine, application, values)
        assert row is not None
        created_projects.append(row)

    progress_rows = [
        (
            created_projects[0],
            "2026-04-15",
            "正常",
            0.25,
            "完成需求调研与总体方案设计，关键传感器选型通过评审。",
            "样机联调窗口与实验室排期冲突，已申请夜间时段。",
        ),
        (
            created_projects[1],
            "2026-05-20",
            "正常",
            0.40,
            "完成可靠性指标初稿与两个典型模块的测试用例。",
            "部分历史缺陷数据缺失，采用同类项目数据补充。",
        ),
        (
            created_projects[2],
            "2026-05-08",
            "存在风险",
            0.30,
            "完成三个业务系统的数据接入，主数据对齐规则待确认。",
            "客户侧口径未统一，需在 5 月底前完成确认。",
        ),
    ]
    for project, day, state, percent, summary, issue in progress_rows:
        assert project is not None
        create_row(
            engine,
            progress,
            values={
                "所属项目": [project["id"]],
                "填报日期": day,
                "进展状态": state,
                "完成度": percent,
                "阶段进展": summary,
                "存在问题与措施": issue,
            },
        )

    budget_rows = [
        (created_projects[0], "2026-02-10", "设备费", 180000, "采购高频振动传感器与采集卡", "PZ-2026-0007"),
        (created_projects[0], "2026-03-18", "差旅费", 12600, "项目启动会与现场调研差旅", "CL-2026-0031"),
        (created_projects[1], "2026-04-02", "测试化验加工费", 86000, "第三方可靠性测试服务", "CS-2026-0012"),
        (created_projects[2], "2026-03-25", "劳务费", 42000, "数据治理与接入开发劳务", "LW-2026-0009"),
    ]
    for project, day, subject, amount, purpose, voucher in budget_rows:
        assert project is not None
        create_row(
            engine,
            budget,
            values={
                "所属项目": [project["id"]],
                "支出日期": day,
                "支出科目": subject,
                "金额（元）": amount,
                "用途说明": purpose,
                "凭证编号": voucher,
            },
        )

    create_row(
        engine,
        closure,
        values={
            "所属项目": [created_projects[2]["id"]],
            "验收日期": "2027-06-30",
            "验收结论": "通过",
            "成果摘要": "完成多源异构数据融合平台建设，接入 3 个业务系统，形成 1 项软件著作权与 2 项企业标准。",
            "成果类型": ["软件著作权", "标准"],
        },
    )

    expense = table("expense_claim")
    achievement = table("achievement_registry")
    change = table("project_change")
    expense_rows = [
        (created_projects[0], "张伟", "2026-05-06", "材料费", 8600, "采购传感器标定耗材", "待审批", ""),
        (created_projects[1], "李娜", "2026-05-12", "差旅费", 3200, "参加可靠性评测标准研讨会", "已通过", "同意报销"),
    ]
    for project, person, day, subject, amount, reason, status, opinion in expense_rows:
        assert project is not None
        create_row(
            engine,
            expense,
            values={
                "所属项目": [project["id"]],
                "报销人": person,
                "报销日期": day,
                "报销科目": subject,
                "金额（元）": amount,
                "报销事由": reason,
                "审批状态": status,
                "审批意见": opinion,
            },
        )

    achievement_rows = [
        (created_projects[0], "复杂工况设备故障诊断方法", ["论文", "专利"], "张伟、王磊", "2026-06-18", "档案室 A-03"),
        (created_projects[2], "多源异构数据融合平台 V1.0", ["软件著作权"], "王强", "2027-05-20", "档案室 B-01"),
    ]
    for project, title, kinds, authors, day, location in achievement_rows:
        assert project is not None
        create_row(
            engine,
            achievement,
            values={
                "所属项目": [project["id"]],
                "成果名称": title,
                "成果类型": kinds,
                "完成人": authors,
                "登记日期": day,
                "归档位置": location,
            },
        )

    create_row(
        engine,
        change,
        values={
            "所属项目": [created_projects[1]["id"]],
            "变更类型": "周期变更",
            "申请日期": "2026-07-01",
            "变更内容": "项目结束时间由 2027-12 延长至 2028-03，增加现场验证环节。",
            "变更原因": "客户现场环境比预期复杂，需要补充一轮验证。",
            "审批状态": "待审批",
        },
    )

    doc_state = (ws.template_state or {}).get("documents", {})
    doc_samples = {
        "proposal_doc": """# 立项申请书

## 一、项目基本信息

- 项目名称：面向高端装备的智能监测关键技术研究
- 项目编号：2026-GJ-001
- 负责人：张伟
- 依托单位：某大学机械工程学院

## 二、研究背景与意义

高端装备服役环境复杂，现有监测手段对早期故障识别不足。

## 三、研究目标与内容

形成多源信号融合、故障特征提取与剩余寿命预测三项关键技术。
""",
        "midterm_doc": """# 中期检查报告

## 一、计划执行情况

已完成总体方案与传感器选型，进度符合计划。

## 二、阶段性成果

完成监测原型系统 v0.1，申请发明专利 1 项。

## 三、经费使用情况

设备费支出 18 万元，差旅费 1.26 万元。

## 四、存在问题与下一步计划

加快样机联调，按节点完成数据采集与算法验证。
""",
    }
    for key, content in doc_samples.items():
        doc_id = doc_state.get(key)
        if isinstance(doc_id, int) and db.get(Document, doc_id) is not None:
            update_content(db, ws.id, doc_id, owner, content=content, change_summary="写入示例内容")

    db.commit()
    print(f"[seed] 创建模板示例工作区: {EXAMPLE_WORKSPACE_NAME} (id={ws.id})")
    return 1


def _seed_workspace_templates(db: Any, owner: Any = None, owner_id: int | None = None) -> int:
    """写入内置模板与示例工作区；返回创建数量."""
    if owner is not None:
        owner_id = owner.id
    created = _seed_research_template(db, owner_id)
    template = (
        db.query(__import__("cndb").plugins.workspaces.models.WorkspaceTemplate).filter_by(name=TEMPLATE_NAME).first()
    )
    if owner is not None and template is not None:
        created += _seed_research_example(db, owner, template)
    return created


__all__ = [
    "EXAMPLE_WORKSPACE_NAME",
    "RESEARCH_LIFECYCLE_SPEC",
    "TEMPLATE_NAME",
    "_seed_workspace_templates",
]
