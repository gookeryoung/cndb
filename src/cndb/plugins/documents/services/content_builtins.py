"""内容模板内置库（ADR 0185）：代码常量，只读、不入库、不进备份.

与导出模板内置 6 套（``services/export/templates.py`` 的 ``BUILTIN_TEMPLATES``）同一范式：
随应用发布、不落表、无写端点、无默认锚点。两级结构：

- :class:`BuiltinContentCategory` —— 分类（``key`` / ``name`` / ``description`` / ``sort_order``）；
- :class:`BuiltinContentTemplate` —— 分类下的模板，``ref`` 由 ``builtin:`` + ``key`` 推导。

三条不变量（ADR 0185 I2 / I3 / I4）：

- **I2 两级结构稳定**：模板 ``key`` 扁平且全库唯一，分类只是元数据；
  顺序由 ``sort_order``（同值按常量声明顺序）决定，前端不重排。
- **I3 引用格式唯一**：``builtin:<key>``，且 key 集合与导出模板的 ``BUILTIN_TEMPLATES`` 无交集，
  避免两套 ref 互相误解析。
- **I4 正文可移植**：正文只含纯 Markdown，禁止 ``{{table:…}}`` / ``[[双链]]`` /
  工作区 · 文档 · 用户 id 等动态引用，保证任意工作区新建都不产生悬空引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: 内置内容模板引用前缀（与导出模板同形，但两边 key 集合不得有交集，I3）
BUILTIN_CONTENT_PREFIX = "builtin:"

#: 正文禁用的动态引用片段（I4）：命中即视为内置库损坏
FORBIDDEN_CONTENT_SNIPPETS: tuple[str, ...] = ("{{table:", "[[", "/w/", "documents?")


@dataclass(frozen=True)
class BuiltinContentCategory:
    """内置分类（两级结构的第一级）."""

    key: str
    name: str
    description: str
    sort_order: int

    @property
    def ref(self) -> str:
        return f"category:{self.key}"


@dataclass(frozen=True)
class BuiltinContentTemplate:
    """内置模板（两级结构的第二级）；``ref`` 由 key 推导，常量里不重复存."""

    category: str
    key: str
    name: str
    description: str
    icon: str
    sort_order: int
    export_template_ref: str | None
    content_markdown: str

    @property
    def ref(self) -> str:
        return builtin_content_ref(self.key)


def builtin_content_ref(key: str) -> str:
    """``builtin:<key>``（I3）."""
    return f"{BUILTIN_CONTENT_PREFIX}{key}"


BUILTIN_CONTENT_CATEGORIES: tuple[BuiltinContentCategory, ...] = (
    BuiltinContentCategory(
        key="research-pm",
        name="科研项目管理",
        description="立项 → 执行 → 结题全过程的文档骨架",
        sort_order=10,
    ),
)

_PROJECT_PROPOSAL = """## 一、项目基本信息

| 项目名称 | （填写） |
| 项目负责人 | （填写） |
| 申报单位 | （填写） |
| 起止时间 | （填写） |
| 经费预算 | （填写） |

## 二、立项依据与研究背景

（国内外研究现状、存在的问题、立项必要性）

## 三、研究目标与研究内容

### 3.1 总体目标

（填写）

### 3.2 具体目标与考核指标

| 指标类别 | 指标内容 | 目标值 | 验收方式 |
| （填写） | （填写） | （填写） | （填写） |

### 3.3 研究内容

（填写）

## 四、研究方案与技术路线

### 4.1 研究方法

（填写）

### 4.2 技术路线

（填写）

### 4.3 创新点

（填写）

## 五、进度安排与里程碑

| 阶段 | 时间 | 主要任务 | 交付物 |
| （填写） | （填写） | （填写） | （填写） |

## 六、经费预算

| 科目 | 金额（万元） | 用途说明 |
| （填写） | （填写） | （填写） |

## 七、预期成果

- [ ] （填写：论文 / 专利 / 标准 / 软件著作权 / 样机 / 示范应用等）

## 八、风险与应对

| 风险 | 可能性 | 影响 | 应对措施 |
| （填写） | （填写） | （填写） | （填写） |
"""

_PROJECT_PLAN = """## 一、项目概况

| 项目名称 | （填写） |
| 项目编号 | （填写） |
| 起止时间 | （填写） |
| 承担单位 | （填写） |

## 二、任务分解（WBS）

| 任务编号 | 任务名称 | 负责人 | 起止时间 | 交付物 |
| （填写） | （填写） | （填写） | （填写） | （填写） |

## 三、考核指标

| 指标类别 | 指标内容 | 目标值 | 验收方式 |
| （填写） | （填写） | （填写） | （填写） |

## 四、里程碑计划

| 里程碑 | 计划时间 | 完成标志 | 对应任务 |
| （填写） | （填写） | （填写） | （填写） |

## 五、组织与分工

（填写：项目组构成、角色职责、协作机制）

## 六、经费与资源保障

（填写）

## 七、风险与变更管理

| 风险 / 变更点 | 触发条件 | 处理流程 | 责任人 |
| （填写） | （填写） | （填写） | （填写） |

## 八、依据与附件

- [ ] （填写：立项批复 / 申报书 / 合同等）
"""

_PROGRESS_REPORT = """## 一、项目执行情况概述

（填写：计划任务、执行周期、总体进展）

## 二、主要进展

### 2.1 任务完成情况

| 任务编号 | 计划内容 | 完成情况 | 完成比例 |
| （填写） | （填写） | （填写） | （填写） |

### 2.2 阶段性成果

（填写）

## 三、考核指标完成情况

| 指标 | 计划值 | 当前进展 | 达成率 |
| （填写） | （填写） | （填写） | （填写） |

## 四、经费执行情况

| 科目 | 预算（万元） | 已支出（万元） | 执行率 |
| （填写） | （填写） | （填写） | （填写） |

## 五、存在的问题与偏差

（填写）

## 六、调整方案与下阶段计划

（填写）

## 七、需支持事项

（填写）
"""

_WEEKLY_REPORT = """## 一、本周进展

（填写）

## 二、关键指标与里程碑

| 事项 | 目标 | 当前 | 状态 |
| （填写） | （填写） | （填写） | （填写） |

## 三、风险与阻塞

- [ ] （填写）

## 四、下周计划

- [ ] （填写）

## 五、需协调事项

（填写）
"""

_MEETING_NOTES = """## 一、会议信息

| 时间 | （填写） |
| 地点 | （填写） |
| 主持人 | （填写） |
| 记录人 | （填写） |

## 二、参会人员

（填写）

## 三、议题与讨论

（填写）

## 四、决议事项

1. （填写）

## 五、待办事项

| 序号 | 事项 | 责任人 | 截止时间 | 状态 |
| 1 | （填写） | （填写） | （填写） | 待开始 |

## 六、下次会议安排

（填写）
"""

_FINAL_REPORT = """## 一、项目概况

| 项目名称 | （填写） |
| 项目编号 | （填写） |
| 起止时间 | （填写） |
| 承担单位 | （填写） |

## 二、任务与指标完成情况

| 指标 | 计划值 | 实际值 | 完成情况 |
| （填写） | （填写） | （填写） | （填写） |

## 三、主要研究成果

### 3.1 成果清单

| 序号 | 成果名称 | 类型 | 证明材料 |
| 1 | （填写） | （填写） | （填写） |

### 3.2 创新性与水平评价

（填写）

## 四、经费决算

| 科目 | 预算（万元） | 决算（万元） | 差异说明 |
| （填写） | （填写） | （填写） | （填写） |

## 五、成果应用与推广

（填写）

## 六、存在问题与后续工作

（填写）

## 七、结论与建议

（填写）

## 附件清单

- [ ] （填写）
"""

#: 内置模板（扁平 key 全局唯一，I2）；顺序由 sort_order 决定
BUILTIN_CONTENT_TEMPLATES: dict[str, BuiltinContentTemplate] = {
    template.key: template
    for template in (
        BuiltinContentTemplate(
            category="research-pm",
            key="research-pm.project-proposal",
            name="项目立项申请书",
            description="申报 / 立项评审用的论证材料：依据、目标、方案、预算与风险",
            icon="📝",
            sort_order=10,
            export_template_ref="builtin:official",
            content_markdown=_PROJECT_PROPOSAL,
        ),
        BuiltinContentTemplate(
            category="research-pm",
            key="research-pm.project-plan",
            name="项目任务书与实施计划",
            description="立项后任务分解、考核指标与里程碑安排",
            icon="📋",
            sort_order=20,
            export_template_ref="builtin:official",
            content_markdown=_PROJECT_PLAN,
        ),
        BuiltinContentTemplate(
            category="research-pm",
            key="research-pm.progress-report",
            name="项目中期检查报告",
            description="中期检查 / 阶段汇报：进展、指标、经费与调整方案",
            icon="📈",
            sort_order=30,
            export_template_ref="builtin:research",
            content_markdown=_PROGRESS_REPORT,
        ),
        BuiltinContentTemplate(
            category="research-pm",
            key="research-pm.weekly-report",
            name="项目周报",
            description="周度进展同步：本周进展、指标状态、风险与下周计划",
            icon="🗓️",
            sort_order=40,
            export_template_ref=None,
            content_markdown=_WEEKLY_REPORT,
        ),
        BuiltinContentTemplate(
            category="research-pm",
            key="research-pm.meeting-notes",
            name="项目会议纪要",
            description="例会 / 评审会记录：议题、决议、待办与下次安排",
            icon="🧾",
            sort_order=50,
            export_template_ref=None,
            content_markdown=_MEETING_NOTES,
        ),
        BuiltinContentTemplate(
            category="research-pm",
            key="research-pm.final-report",
            name="项目结题验收报告",
            description="结题 / 验收材料：指标完成情况、成果、经费决算与结论",
            icon="✅",
            sort_order=60,
            export_template_ref="builtin:research",
            content_markdown=_FINAL_REPORT,
        ),
    )
}


def builtin_content_template(key: str) -> BuiltinContentTemplate | None:
    """按 key 取内置模板；未知 key 返回 ``None``（端点一期不暴露单条）."""
    return BUILTIN_CONTENT_TEMPLATES.get(key)


def _ordered_categories() -> list[BuiltinContentCategory]:
    return sorted(BUILTIN_CONTENT_CATEGORIES, key=lambda category: (category.sort_order, category.key))


def _ordered_templates(category: BuiltinContentCategory) -> list[BuiltinContentTemplate]:
    return sorted(
        (t for t in BUILTIN_CONTENT_TEMPLATES.values() if t.category == category.key),
        key=lambda template: (template.sort_order, template.key),
    )


def serialize_builtin_template(template: BuiltinContentTemplate) -> dict[str, Any]:
    """单条内置模板载荷（正文随列表一次返回，避免 N+1，D4）."""
    return {
        "ref": template.ref,
        "key": template.key,
        "name": template.name,
        "description": template.description,
        "icon": template.icon,
        "sort_order": template.sort_order,
        "export_template_ref": template.export_template_ref,
        "content_markdown": template.content_markdown,
    }


def builtin_content_library() -> dict[str, Any]:
    """内置库载荷：``{categories: [...]}``，分类与模板都已按 sort_order 排序（I2）."""
    return {
        "categories": [
            {
                "key": category.key,
                "name": category.name,
                "description": category.description,
                "sort_order": category.sort_order,
                "templates": [serialize_builtin_template(t) for t in _ordered_templates(category)],
            }
            for category in _ordered_categories()
        ]
    }


__all__ = [
    "BUILTIN_CONTENT_CATEGORIES",
    "BUILTIN_CONTENT_PREFIX",
    "BUILTIN_CONTENT_TEMPLATES",
    "FORBIDDEN_CONTENT_SNIPPETS",
    "BuiltinContentCategory",
    "BuiltinContentTemplate",
    "builtin_content_library",
    "builtin_content_ref",
    "builtin_content_template",
    "serialize_builtin_template",
]
