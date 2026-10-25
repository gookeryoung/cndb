"""典型示例静态清单（ADR 0029 §1）.

本清单是帮助示例的**唯一**来源：场景元信息、表清单与下载白名单都在这里；
前端只渲染接口返回值，不维护第二份示例清单。`rows` 为示例说明用的近似行数，
不做实时统计。
"""

from __future__ import annotations

from typing import TypedDict


class HelpExampleTable(TypedDict):
    """示例中的一张 CSV 表."""

    file: str
    title: str
    description: str
    rows: int


class HelpExample(TypedDict):
    """一个示例场景."""

    key: str
    name: str
    summary: str
    tables: list[HelpExampleTable]
    highlights: list[str]
    steps: list[str]


HELP_EXAMPLE_MANIFEST: list[HelpExample] = [
    {
        "key": "sales",
        "name": "某企业销售管理",
        "summary": "从销售明细、客户流失到营销活动与日常待办的完整销售运营示例。",
        "tables": [
            {
                "file": "电商销售.csv",
                "title": "电商销售",
                "description": "订单级销售明细：订单号、用户 ID、商品类别、单价、数量、支付方式、评分、销售额、日期。",
                "rows": 500,
            },
            {
                "file": "客户流失.csv",
                "title": "客户流失",
                "description": "客户维度：在网月数、月消费、订购服务数、客服呼叫次数、合约类型、套餐名称、是否流失。",
                "rows": 500,
            },
            {
                "file": "营销活动.csv",
                "title": "营销活动",
                "description": "活动维度：渠道类型、活动状态、预算与实际花费、线索数、转化率、负责人。",
                "rows": 14,
            },
            {
                "file": "日常待办.csv",
                "title": "日常待办",
                "description": "团队待办：负责人、待办类型、优先级、截止与完成日期、状态。",
                "rows": 30,
            },
        ],
        "highlights": [
            "图表视图看月度销售额与渠道构成",
            "看板视图跟踪客户流失回访状态",
            "数据分析模板：商品类别占比与客单价",
        ],
        "steps": [
            "下载需要的示例 CSV",
            "新建数据表并导入 CSV",
            "按字段类型核对后创建视图",
            "用图表 / 看板视图与数据分析模板复盘",
        ],
    },
    {
        "key": "research",
        "name": "科研项目管理",
        "summary": "围绕课题立项、任务分解、经费与资源排期组织数据，适合练习层级与关联字段。",
        "tables": [
            {
                "file": "科研项目.csv",
                "title": "科研项目",
                "description": "课题主数据：课题编号、项目名称、项目类别、承担单位、立项年份、项目状态、经费总额、结题日期。",
                "rows": 40,
            },
            {
                "file": "科研任务分解.csv",
                "title": "科研任务分解",
                "description": "任务层级：任务 ID、父任务 ID、任务名称、负责人、状态、进度、工期、交付物。",
                "rows": 31,
            },
            {
                "file": "科研经费.csv",
                "title": "科研经费",
                "description": "经费台账：课题编号、预算科目、预算 / 已拨 / 已支金额、拨付日期、经费状态。",
                "rows": 220,
            },
            {
                "file": "科研资源排期.csv",
                "title": "科研资源排期",
                "description": "资源投入：团队、任务名称、排期日期、投入人天、负责人、状态、课题编号。",
                "rows": 26,
            },
        ],
        "highlights": [
            "工作分解视图按「课题 → 任务 → 子任务」组织层级",
            "甘特图查看资源排期与工期",
            "关联字段串起课题、任务与经费",
        ],
        "steps": [
            "下载科研项目与任务分解等 CSV",
            "分别导入为数据表",
            "用关联字段连接课题与任务",
            "用工作分解视图 / 甘特图查看计划",
        ],
    },
    {
        "key": "datasource",
        "name": "数据源示例",
        "summary": "把外部数据按计划写入数据表，覆盖资讯、美食与天气三类内容，适合练习数据接入与画廊阅读。",
        "tables": [
            {
                "file": "国际形势发展动态.csv",
                "title": "国际形势发展动态",
                "description": "资讯条目：日期、地区、来源、摘要、标题、主题、趋势判断、链接。",
                "rows": 12,
            },
            {
                "file": "美食推荐做法.csv",
                "title": "美食推荐做法",
                "description": "菜谱：菜名、菜系、难度、烹饪时长、主要食材、分步做法、小贴士。",
                "rows": 8,
            },
            {
                "file": "天气每日.csv",
                "title": "天气每日",
                "description": "天气观测：城市、日期、最高 / 最低 / 平均气温、降水量。",
                "rows": 276,
            },
        ],
        "highlights": [
            "画廊视图阅读资讯与菜谱",
            "数据源同步按 cron 周期抓取并去重入库",
            "分析页做天气趋势与地区分布统计",
        ],
        "steps": [
            "下载示例 CSV 并导入数据表",
            "核对字段类型与去重键",
            "在数据源同步中配置周期任务",
            "用画廊视图与分析页阅读数据",
        ],
    },
]

# 场景 key → examples/datasets 下的目录名（仅服务端使用，接口不暴露）
SCENARIO_DIRECTORIES: dict[str, str] = {
    "sales": "工作区-某企业销售管理",
    "research": "工作区-科研项目管理",
    "datasource": "工作区-数据源示例",
}


def find_example(scenario: str) -> HelpExample | None:
    """按场景 key 查清单；未知场景返回 None."""
    return next((item for item in HELP_EXAMPLE_MANIFEST if item["key"] == scenario), None)


__all__ = [
    "HELP_EXAMPLE_MANIFEST",
    "SCENARIO_DIRECTORIES",
    "HelpExample",
    "HelpExampleTable",
    "find_example",
]
