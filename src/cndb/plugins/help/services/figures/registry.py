"""帮助图示清单与指纹（ADR 0030 §2）.

清单是图示的**唯一**注册点：`key` 是接口路径与前端引用的唯一标识；
`build` 生成 SVG；`data_digest` 汇报「图依赖的数据源」当前摘要。

指纹 = `sha1(构建函数源码 + 数据源摘要)`：

- 编排代码改了（改配色、改文案、加节点）→ 源码变 → 指纹变 → 自动重建；
- 数据源变了（新增字段类型、改了示例 CSV、加了调度模式）→ 摘要变 → 自动重建。

这条规则就是「图示不会随代码更新而过期」的机制保证：不依赖人工记得刷新。
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import lru_cache

from cndb.plugins.help.services.examples import HELP_EXAMPLE_MANIFEST, SCENARIO_DIRECTORIES
from cndb.plugins.help.services.figures import builders


def _hash(*parts: str) -> str:
    digest = hashlib.sha1()
    for part in parts:
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


@lru_cache(maxsize=64)
def _code_digest(fn: Callable[[], str]) -> str:
    """构建函数源码摘要（`inspect` 失败时退化为函数名，不影响可用性）."""
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        return getattr(fn, "__qualname__", repr(fn))
    return _hash(source)


def _field_types_digest() -> str:
    """字段类型注册表摘要：新增 / 改名 / 换分类都会变."""
    from cndb.plugins.tables.field_types import default_registry

    return _hash("|".join(f"{ft.name}:{ft.label}:{ft.category}" for ft in default_registry.all()))


def _enum_digest(*enums: object) -> str:
    """枚举成员摘要：成员增删或改名都会变."""
    chunks: list[str] = []
    for enum_cls in enums:
        members = getattr(enum_cls, "__members__", {})
        chunks.append("|".join(f"{name}={member.value}" for name, member in members.items()))
    return _hash(*chunks)


def _csv_digest(scenario: str, filename: str) -> str:
    """示例 CSV 摘要：大小 + 修改时间 + 表头（避免每次全量读文件）."""
    from cndb.plugins.help.services.assets import resolve_example_file

    path = resolve_example_file(scenario, filename)
    if path is None:
        return "missing"
    stat = path.stat()
    header = ""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        header = handle.readline().strip()
    return _hash(str(stat.st_size), str(stat.st_mtime_ns), header)


@dataclass(frozen=True)
class FigureSpec:
    """一张帮助图示的定义."""

    key: str
    title: str
    caption: str
    section: str
    build: Callable[[], str]
    data_digest: Callable[[], str] = field(default=lambda: "")

    def fingerprint(self) -> str:
        """当前源码 + 数据源指纹；与磁盘快照不一致即需重建."""
        return _hash(_code_digest(self.build), self.data_digest())


def _static_spec(key: str, title: str, caption: str, section: str, build: Callable[[], str]) -> FigureSpec:
    return FigureSpec(key=key, title=title, caption=caption, section=section, build=build)


def _build_specs() -> list[FigureSpec]:
    from cndb.plugins.datasource.models import ScheduleMode
    from cndb.plugins.tables.models import ViewVisibility
    from cndb.plugins.workspaces.models import WorkspaceRole

    specs: list[FigureSpec] = [
        _static_spec(
            "quick-start-flow",
            "五步上手流程",
            "从创建工作区到协作授权的最小路径，每一步都能在帮助文档里找到对应主题。",
            "quick-start",
            builders.build_quick_start_flow,
        ),
        _static_spec(
            "workspace-structure",
            "工作区结构",
            "数据表管数据、文档管知识、成员管权限，三者都在同一个工作区里。",
            "quick-start",
            builders.build_workspace_structure,
        ),
        FigureSpec(
            key="field-types",
            title="字段类型一览",
            caption="按分类列出当前版本支持的全部字段类型；新增类型会自动出现在这张图里。",
            section="tutorials",
            build=builders.build_field_types,
            data_digest=_field_types_digest,
        ),
        FigureSpec(
            key="permission-model",
            title="权限与角色",
            caption="工作区三角色与视图三档可见性，取自权限模型的实际枚举。",
            section="tutorials",
            build=builders.build_permission_model,
            data_digest=lambda: _enum_digest(WorkspaceRole, ViewVisibility),
        ),
        _static_spec(
            "import-flow",
            "导入流程",
            "导入不是「上传即入库」：表头识别、类型推断与预览确认都会影响落表结果。",
            "tutorials",
            builders.build_import_flow,
        ),
        FigureSpec(
            key="datasource-sync",
            title="数据源同步链路",
            caption="四种调度模式与从抓取到落表的执行链路，取自数据源模块的实际枚举。",
            section="configuration",
            build=builders.build_datasource_sync,
            data_digest=lambda: _enum_digest(ScheduleMode),
        ),
    ]

    # 每个示例表一张「真实数据预览」：CSV 改了，图自动重建
    for example in HELP_EXAMPLE_MANIFEST:
        scenario = example["key"]
        for index, table in enumerate(example["tables"], start=1):
            filename = table["file"]
            specs.append(
                FigureSpec(
                    key=f"example-{scenario}-table-{index}",
                    title=f"{table['title']}示例预览",
                    caption=f"{table['description']}（预览取自 examples/datasets 的真实 CSV）",
                    section="examples",
                    build=lambda scenario=scenario, filename=filename: builders.build_example_preview(
                        scenario, filename
                    ),
                    data_digest=lambda scenario=scenario, filename=filename: _csv_digest(scenario, filename),
                )
            )
    return specs


FIGURE_SPECS: list[FigureSpec] = _build_specs()
FIGURE_SPEC_BY_KEY: dict[str, FigureSpec] = {spec.key: spec for spec in FIGURE_SPECS}


def find_spec(key: str) -> FigureSpec | None:
    """按 key 查图示定义；未知 key 返回 None（接口据此 404）."""
    return FIGURE_SPEC_BY_KEY.get(key)


def scenario_directory(scenario: str) -> str | None:
    """场景 → 示例目录名（仅测试与排障使用）."""
    return SCENARIO_DIRECTORIES.get(scenario)


__all__ = ["FIGURE_SPECS", "FIGURE_SPEC_BY_KEY", "FigureSpec", "find_spec", "scenario_directory"]
