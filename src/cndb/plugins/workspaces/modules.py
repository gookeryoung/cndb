"""工作区模块口径（ADR 0080）：模块集合 → 开放功能的唯一判定入口.

- ``MODULE_FEATURES``：模块 → 派生功能绑定表（数据分析 / 数据源同步强绑定数据表，
  不进勾选 UI 与 API 字段，仅由此推导）；
- ``resolve_features``：模块集合 → 功能开关矩阵（后端唯一入口，与前端
  ``workspaceModules.ts`` 语义逐项一致）;
- ``legacy_type_to_modules``：旧 ``workspace_type`` 枚举 → 模块集合（迁移与
  旧备份导入共用一份映射，ADR 0080 D5/D7）；
- ``normalize_modules`` / ``workspace_modules_from_meta``：写路径校验与备份
  元数据解析（创建 / 更新 / 恢复 / 导入全部经此，空集与未知值拒绝或回退）。

后续为文档 / 设计新增子模块时只改 ``MODULE_FEATURES`` 绑定表，不改模型。
"""

from __future__ import annotations

from typing import Any

from cndb.plugins.workspaces.models import WORKSPACE_MODULES, WorkspaceModule

# 模块 → 派生功能绑定表（唯一真相源；quality 不在此表，恒开放，见 resolve_features）
MODULE_FEATURES: dict[str, frozenset[str]] = {
    WorkspaceModule.TABLES.value: frozenset({"tables", "analytics", "datasource"}),
    WorkspaceModule.DOCUMENTS.value: frozenset({"documents"}),
    WorkspaceModule.DESIGN.value: frozenset({"design"}),
}

# 功能开关矩阵的稳定输出顺序
_FEATURE_KEYS: tuple[str, ...] = ("tables", "documents", "design", "analytics", "datasource", "quality")

# 旧 workspace_type 枚举 → 模块集合（ADR 0080 D5：按现行 feature 矩阵逐项平移）
_LEGACY_TYPE_TO_MODULES: dict[str, list[str]] = {
    "data_doc": ["tables", "documents", "design"],
    "data": ["tables"],
    "doc": ["documents", "design"],
}


def normalize_modules(value: Any) -> list[str]:
    """校验并归一模块集合：非空、白名单、去重、按 ``WORKSPACE_MODULES`` 固定顺序.

    Raises:
        ValueError: 空集合 / 非列表 / 含白名单外的值。
    """
    if not isinstance(value, (list, tuple)) or len(value) == 0:
        raise ValueError("modules 不能为空，至少勾选一个功能模块")
    known = set(WORKSPACE_MODULES)
    for item in value:
        if not isinstance(item, str) or item not in known:
            raise ValueError(f"modules 含未知模块：{item!r}（可选：{'、'.join(WORKSPACE_MODULES)}）")
    deduped = set(value)
    return [m for m in WORKSPACE_MODULES if m in deduped]


def resolve_features(modules: list[str]) -> dict[str, bool]:
    """模块集合 → 功能开关矩阵（quality 恒开放，ADR 0080 D4）."""
    enabled = {m for m in modules if m in MODULE_FEATURES}
    features: dict[str, bool] = {}
    for key in _FEATURE_KEYS:
        if key == "quality":
            features[key] = True
        else:
            features[key] = any(key in MODULE_FEATURES[m] for m in enabled)
    return features


def legacy_type_to_modules(workspace_type: str) -> list[str]:
    """旧 workspace_type 枚举 → 模块集合；未知值回退全三模块."""
    mapped = _LEGACY_TYPE_TO_MODULES.get(workspace_type)
    return list(mapped) if mapped is not None else list(WORKSPACE_MODULES)


def workspace_modules_from_meta(meta: dict[str, Any]) -> tuple[list[str], str | None]:
    """从备份 workspace 元数据解析模块集合.

    v12 写 ``modules``；≤v11 只有 ``workspace_type``，按 D5 映射；映射 / 校验
    失败（未知枚举值、非法 modules）回退全三模块并返回告警文案（记入导入
    ``errors``，不静默）。返回 ``(modules, warning)``，``warning`` 为 ``None``
    表示无异常。
    """
    if "modules" in meta:
        try:
            return normalize_modules(meta["modules"]), None
        except ValueError:
            return (
                list(WORKSPACE_MODULES),
                f"备份中的 modules 字段非法（{meta['modules']!r}），已回退为全模块",
            )
    if "workspace_type" in meta:
        raw = meta["workspace_type"]
        if isinstance(raw, str) and raw in _LEGACY_TYPE_TO_MODULES:
            return legacy_type_to_modules(raw), None
        return list(WORKSPACE_MODULES), f"备份中的 workspace_type 未知（{raw!r}），已回退为全模块"
    return list(WORKSPACE_MODULES), None


__all__ = [
    "MODULE_FEATURES",
    "legacy_type_to_modules",
    "normalize_modules",
    "resolve_features",
    "workspace_modules_from_meta",
]
