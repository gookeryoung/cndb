"""设计版本差异服务（ADR 0113 §2 / D5 / D8）.

- 文本差异走 ``cndb.core.textdiff.unified_diff``（I2 单一 diff 入口）；
- 结构摘要读两版 ``compiled`` IR 快照现场计算（零重编译）；任一侧缺 ``nodes``
  时 ``available=false``，文本 diff 照常返回；
- 顶层装配取 ``compiled["outline"]["children"]`` 中 system / assembly / group 的
  ``name`` 集合差（group 无 name 时忽略）。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.core.errors import NotFoundError
from cndb.core.textdiff import unified_diff
from cndb.plugins.design.models import DesignDesign, DesignDesignVersion

_ASSEMBLY_KINDS = {"system", "assembly", "group"}


def _params_map(compiled: dict[str, Any]) -> dict[str, Any]:
    """IR ``params`` 列表 → name → value（非列表 / 非法项忽略）."""
    raw = compiled.get("params")
    if not isinstance(raw, list):
        return {}
    result: dict[str, Any] = {}
    for item in raw:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result[item["name"]] = item.get("value")
    return result


def _assembly_names(compiled: dict[str, Any]) -> set[str]:
    """顶层装配名集合（outline 缺失或节点无名时为空）."""
    outline = compiled.get("outline")
    children = outline.get("children") if isinstance(outline, dict) else None
    if not isinstance(children, list):
        return set()
    names: set[str] = set()
    for node in children:
        if isinstance(node, dict) and node.get("kind") in _ASSEMBLY_KINDS:
            name = node.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def _summary_available(compiled: Any) -> bool:
    """IR 快照可读（dict 且含 nodes 列表；v1 老快照 / 损坏视为不可用）."""
    return isinstance(compiled, dict) and isinstance(compiled.get("nodes"), list)


def _empty_summary(*, available: bool) -> dict[str, Any]:
    """结构摘要空壳（保持响应字段稳定）."""
    return {
        "available": available,
        "params": {"added": [], "removed": [], "changed": []},
        "nodes": {"base": 0, "head": 0},
        "assemblies": {"added": [], "removed": []},
    }


def structure_summary(base: dict[str, Any] | None, head: dict[str, Any] | None) -> dict[str, Any]:
    """两版 IR 快照的结构变化摘要（参数 / 节点数 / 顶层装配）."""
    if not _summary_available(base) or not _summary_available(head):
        return _empty_summary(available=False)
    base_compiled: dict[str, Any] = base or {}
    head_compiled: dict[str, Any] = head or {}

    base_params = _params_map(base_compiled)
    head_params = _params_map(head_compiled)
    changed = [
        {"name": name, "base": base_params[name], "head": head_params[name]}
        for name in base_params.keys() & head_params.keys()
        if base_params[name] != head_params[name]
    ]
    changed.sort(key=lambda item: item["name"])

    base_assemblies = _assembly_names(base_compiled)
    head_assemblies = _assembly_names(head_compiled)

    return {
        "available": True,
        "params": {
            "added": sorted(head_params.keys() - base_params.keys()),
            "removed": sorted(base_params.keys() - head_params.keys()),
            "changed": changed,
        },
        "nodes": {
            "base": len(base_compiled["nodes"]),
            "head": len(head_compiled["nodes"]),
        },
        "assemblies": {
            "added": sorted(head_assemblies - base_assemblies),
            "removed": sorted(base_assemblies - head_assemblies),
        },
    }


def design_diff(
    db: Session,
    design: DesignDesign,
    base_version: int,
    head_version: int,
) -> dict[str, Any]:
    """两版本对比：unified diff + 增删行数 + 结构变化摘要（任一侧缺失 404）."""
    rows = (
        db.query(DesignDesignVersion)
        .filter(
            DesignDesignVersion.design_id == design.id,
            DesignDesignVersion.version_number.in_([base_version, head_version]),
        )
        .all()
    )
    by_number = {row.version_number: row for row in rows}
    base = by_number.get(base_version)
    head = by_number.get(head_version)
    if base is None or head is None:
        raise NotFoundError("设计版本不存在", code="design_version_not_found")

    diff_text, added, removed = unified_diff(base.content, head.content)
    return {
        "base_version": base_version,
        "head_version": head_version,
        "diff": diff_text,
        "added": added,
        "removed": removed,
        "summary": structure_summary(base.compiled, head.compiled),
    }


__all__ = ["design_diff", "structure_summary"]
