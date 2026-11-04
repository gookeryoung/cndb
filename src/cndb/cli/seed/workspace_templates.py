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
            "覆盖科研项目立项、实施、结题三个阶段：内置项目申报 / 进展 / 经费 / 结题四张表单，"
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


def _seed_workspace_templates(db: Any, owner_id: int | None = None) -> int:
    """写入内置模板；返回创建数量."""
    return _seed_research_template(db, owner_id)


__all__ = ["RESEARCH_LIFECYCLE_SPEC", "TEMPLATE_NAME", "_seed_workspace_templates"]
