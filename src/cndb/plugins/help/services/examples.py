"""典型示例静态清单（ADR 0029 §1）.

本清单是帮助示例的**唯一**来源：场景元信息、表清单与下载白名单都在这里；
前端只渲染接口返回值，不维护第二份示例清单。`rows` 为示例说明用的近似行数，
不做实时统计。
"""

from __future__ import annotations

from typing import NotRequired, TypedDict


class HelpExampleTable(TypedDict):
    """示例中的一张 CSV 表."""

    file: str
    title: str
    description: str
    rows: int


class HelpExampleDesign(TypedDict):
    """示例中的一份结构设计文件（`.cnmd`，ADR 0079）."""

    file: str
    title: str
    description: str
    kind: str
    folder: str


class HelpExample(TypedDict):
    """一个示例场景.

    ``designs`` 为可选的结构设计清单（仅「机械设计示例」场景使用）：与 ``tables``
    互斥——该场景不含数据表，只提供可下载的 `.cnmd` 与说明。
    """

    key: str
    name: str
    summary: str
    tables: list[HelpExampleTable]
    highlights: list[str]
    steps: list[str]
    designs: NotRequired[list[HelpExampleDesign]]


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
        "key": "mechanical",
        "name": "机械设计示例",
        "summary": "全套结构设计示例：从单零件、四轮小车到行星减速器、离心风机叶轮与自动化立体仓库，覆盖 DSG 的全部语法与规模边界。仅含设计文件，不含数据表。",
        "tables": [],
        "designs": [
            {
                "file": "法兰板.cnmd",
                "title": "法兰板",
                "description": "最小起步：`param` + 单个 `box` 减孔阵列。适合第一次打开设计编辑器时对照。",
                "kind": "assembly",
                "folder": "",
            },
            {
                "file": "L型支座.cnmd",
                "title": "L型支座",
                "description": "两个 `box` 并集 + 减孔，演示布尔顺序与 `translate` 定位。",
                "kind": "assembly",
                "folder": "",
            },
            {
                "file": "四轮小车.cnmd",
                "title": "四轮小车",
                "description": "与新建默认模板同构：`system` → 组件 → 布尔分组 → 图元，三级大纲的最小完整形态。",
                "kind": "assembly",
                "folder": "",
            },
            {
                "file": "六轴机械臂.cnmd",
                "title": "六轴机械臂",
                "description": "一份设计两个并列 `system` 根；组件内嵌套子装配（`forearm` 下挂 `link` / `joint`），演示「系统 → 组件 → 子装配 → 分组 → 零件」五层。",
                "kind": "assembly",
                "folder": "",
            },
            {
                "file": "分文件装配示例.cnmd",
                "title": "分文件装配示例",
                "description": '用 `use "轮毂"` 引用 `parts/` 下的零件文件，并演示同一零件多实例（实参覆盖顶层 `param`）。',
                "kind": "assembly",
                "folder": "",
            },
            {
                "file": "行星减速器.cnmd",
                "title": "行星减速器",
                "description": "派生参数链（`r_sun` / `r_planet` / `r_carrier` 随齿数联动）+ 三角函数极坐标布齿 + 三级子装配 + 完整约束链（12 条 `coincident` / `concentric` / `fixed`）。",
                "kind": "assembly",
                "folder": "",
            },
            {
                "file": "离心风机叶轮.cnmd",
                "title": "离心风机叶轮",
                "description": "`intersection` 造回转曲面（前盘导流罩）、`mirror` 生成对称半壳、`torus` 集流器、`cone` 导流帽，六种图元全覆盖。",
                "kind": "assembly",
                "folder": "",
            },
            {
                "file": "自动化立体仓库.cnmd",
                "title": "自动化立体仓库",
                "description": "分文件零件批量实例化的规模示例：84 个货位实例引用 `parts/货架单元.cnmd`，展开约 1412 个图元，用于观察编译与预览在大装配下的表现（闭包预算上限 2000）。",
                "kind": "assembly",
                "folder": "",
            },
            {
                "file": "轮毂.cnmd",
                "title": "轮毂",
                "description": "零件文件（`parts/`）：阶梯轴套 + 减重孔，被「分文件装配示例」以 `use` 引用。",
                "kind": "part",
                "folder": "parts",
            },
            {
                "file": "底板.cnmd",
                "title": "底板",
                "description": "零件文件（`parts/`）：带减重与安装孔的底板，被「分文件装配示例」复用。",
                "kind": "part",
                "folder": "parts",
            },
            {
                "file": "货架单元.cnmd",
                "title": "货架单元",
                "description": "零件文件（`parts/`）：单组货位（立柱 + 层板 + 地脚），被「自动化立体仓库」批量实例化。",
                "kind": "part",
                "folder": "parts",
            },
        ],
        "highlights": [
            "同一套 DSL 覆盖单零件、多系统装配与千图元规模",
            "分文件零件 + `use` 实参覆盖，实现「一份零件、多处不同参数」",
            "约束求解（`coincident` / `concentric` / `distance` / `fixed`）让位姿由参数单一决定",
        ],
        "steps": [
            "下载感兴趣的 .cnmd 文件",
            "在设计模块「新建」一份设计，把内容粘进去",
            "改顶层 param 看几何联动（如行星减速器的齿数 m / z_sun）",
            "分文件示例需把 parts/ 下的零件先建成零件文件，再用 use 引用",
        ],
    },
]

# 场景 key → 示例资产目录名（仅服务端使用，接口不暴露）
# research 的下载资产已从 datasets 迁到 examples/help，避免 seed 再建同名工作区；
# sales 仍复用 datasets 下的示例工作区目录。
SCENARIO_DIRECTORIES: dict[str, str] = {
    "sales": "工作区-某企业销售管理",
    "research": "科研项目管理",
    "mechanical": "工作区-机械设计示例",
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
