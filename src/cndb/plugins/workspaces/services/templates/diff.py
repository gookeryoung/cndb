"""模板版本 diff（需求 0094 C4）：把两份已归一化规格变成可读的变更清单.

diff 只描述**规格层**变化；「对已有数据会怎样」由 ``engine.preview_impact`` 计算。
两处分开后，前端可以先展示模板改了什么，再展示使用该模板的工作区会受何影响。
"""

from __future__ import annotations

from typing import Any

SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_BREAKING = "breaking"

#: 变更项严重度排序（前端按此顺序展示，breaking 最前）
SEVERITY_RANK: dict[str, int] = {SEVERITY_BREAKING: 0, SEVERITY_WARN: 1, SEVERITY_INFO: 2}


def _change(
    kind: str,
    target: str,
    message: str,
    severity: str = SEVERITY_INFO,
    *,
    detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "target": target,
        "message": message,
        "severity": severity,
        "detail": detail or {},
    }


def _diff_fields(
    old_fields: list[dict[str, Any]], new_fields: list[dict[str, Any]], form_key: str
) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    old_map = {f["name"]: f for f in old_fields}
    new_map = {f["name"]: f for f in new_fields}
    for name in new_map.keys() - old_map.keys():
        field = new_map[name]
        severity = SEVERITY_WARN if field.get("required") else SEVERITY_INFO
        suffix = "（必填，存量行需补值）" if field.get("required") else ""
        changes.append(
            _change(
                "field_added",
                f"{form_key}.{name}",
                f"表单「{form_key}」新增字段「{name}」{suffix}",
                severity,
                detail={"field": name, "type": field.get("type"), "required": bool(field.get("required"))},
            )
        )
    for name in old_map.keys() - new_map.keys():
        changes.append(
            _change(
                "field_removed",
                f"{form_key}.{name}",
                f"表单「{form_key}」移除字段「{name}」（历史列与数据保留，不再由模板管理）",
                SEVERITY_WARN,
                detail={"field": name},
            )
        )
    for name in old_map.keys() & new_map.keys():
        old, new = old_map[name], new_map[name]
        if old.get("type") != new.get("type"):
            changes.append(
                _change(
                    "field_type_changed",
                    f"{form_key}.{name}",
                    f"表单「{form_key}」字段「{name}」类型 {old.get('type')} → {new.get('type')}（需人工迁移，模板不会自动改列类型）",
                    SEVERITY_BREAKING,
                    detail={"field": name, "from": old.get("type"), "to": new.get("type")},
                )
            )
        if bool(old.get("required")) != bool(new.get("required")):
            severity = SEVERITY_WARN if new.get("required") else SEVERITY_INFO
            state = "改为必填" if new.get("required") else "改为选填"
            changes.append(
                _change(
                    "field_required_changed",
                    f"{form_key}.{name}",
                    f"表单「{form_key}」字段「{name}」{state}",
                    severity,
                    detail={"field": name, "required": bool(new.get("required"))},
                )
            )
        if old.get("config") != new.get("config"):
            changes.append(
                _change(
                    "field_config_changed",
                    f"{form_key}.{name}",
                    f"表单「{form_key}」字段「{name}」配置发生变化",
                    SEVERITY_INFO,
                    detail={"field": name},
                )
            )
    return changes


def _diff_named(
    old_items: list[dict[str, Any]],
    new_items: list[dict[str, Any]],
    *,
    kind: str,
    label: str,
    name_key: str,
    extra_compare: tuple[str, ...] = (),
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    old_map = {i["key"]: i for i in old_items}
    new_map = {i["key"]: i for i in new_items}
    result: dict[str, list[dict[str, Any]]] = {"added": [], "removed": [], "modified": []}
    changes: list[dict[str, Any]] = []
    for key in new_map.keys() - old_map.keys():
        item = new_map[key]
        result["added"].append({"key": key, "name": item.get(name_key, key)})
        changes.append(_change(f"{kind}_added", key, f"新增{label}「{item.get(name_key, key)}」"))
    for key in old_map.keys() - new_map.keys():
        item = old_map[key]
        result["removed"].append({"key": key, "name": item.get(name_key, key)})
        changes.append(
            _change(
                f"{kind}_removed",
                key,
                f"移除{label}「{item.get(name_key, key)}」（存量数据保留）",
                SEVERITY_WARN,
                detail={"key": key},
            )
        )
    for key in old_map.keys() & new_map.keys():
        old, new = old_map[key], new_map[key]
        changed: list[str] = []
        if old.get(name_key) != new.get(name_key):
            changed.append(f"{name_key}：{old.get(name_key)} → {new.get(name_key)}")
        for field in extra_compare:
            if old.get(field) != new.get(field):
                changed.append(f"{field} 变化")
        if changed:
            result["modified"].append({"key": key, "name": new.get(name_key, key), "changes": changed})
            changes.append(
                _change(
                    f"{kind}_modified",
                    key,
                    f"修改{label}「{new.get(name_key, key)}」：{'；'.join(changed)}",
                    detail={"key": key},
                )
            )
    return result, changes


def diff_specs(old_spec: dict[str, Any], new_spec: dict[str, Any]) -> dict[str, Any]:
    """比较两份规格，返回分组 diff + 扁平变更清单（含严重度）.

    ``requires_force`` 仅针对**必须人工介入**的破坏性变更（目前是字段类型切换）；
    其余变更一律「保留存量数据、只增量补齐」，不需要 force。
    """
    old_forms = {f["key"]: f for f in old_spec.get("forms", [])}
    new_forms = {f["key"]: f for f in new_spec.get("forms", [])}
    forms, changes = _diff_named(
        list(old_forms.values()), list(new_forms.values()), kind="form", label="表单", name_key="name"
    )
    # 字段级差异（仅对同 key 表单）
    for key in old_forms.keys() & new_forms.keys():
        field_changes = _diff_fields(old_forms[key].get("fields", []), new_forms[key].get("fields", []), key)
        if field_changes:
            forms["modified"].append(
                {
                    "key": key,
                    "name": new_forms[key]["name"],
                    "changes": [c["message"] for c in field_changes],
                }
            )
            changes.extend(field_changes)

    documents, doc_changes = _diff_named(
        list(old_spec.get("documents", [])),
        list(new_spec.get("documents", [])),
        kind="document",
        label="文档规则",
        name_key="title",
        extra_compare=("required", "naming", "content"),
    )
    changes.extend(doc_changes)

    old_stages = {s["key"]: s for s in old_spec.get("stages", [])}
    new_stages = {s["key"]: s for s in new_spec.get("stages", [])}
    stages, stage_changes = _diff_named(
        list(old_stages.values()),
        list(new_stages.values()),
        kind="stage",
        label="阶段",
        name_key="name",
        extra_compare=("order", "description"),
    )
    changes.extend(stage_changes)
    for key in old_stages.keys() | new_stages.keys():
        old = old_stages.get(key, {})
        new = new_stages.get(key, {})
        for ref_field, ref_label in (("forms", "表单"), ("documents", "文档规则")):
            old_refs = set(old.get(ref_field, []))
            new_refs = set(new.get(ref_field, []))
            added = sorted(new_refs - old_refs)
            removed = sorted(old_refs - new_refs)
            if added or removed:
                parts = []
                if added:
                    parts.append(f"新增{ref_label} {', '.join(added)}")
                if removed:
                    parts.append(f"移除{ref_label} {', '.join(removed)}")
                changes.append(
                    _change(
                        "stage_refs_changed",
                        key,
                        f"阶段「{new.get('name') or old.get('name') or key}」{'；'.join(parts)}",
                        SEVERITY_WARN if removed else SEVERITY_INFO,
                        detail={"stage": key, "added": added, "removed": removed},
                    )
                )
    changes.sort(key=lambda c: (SEVERITY_RANK.get(c["severity"], 9), c["kind"], c["target"]))
    requires_force = any(c["severity"] == SEVERITY_BREAKING for c in changes)

    counts = {
        "added": len(forms["added"]) + len(documents["added"]) + len(stages["added"]),
        "removed": len(forms["removed"]) + len(documents["removed"]) + len(stages["removed"]),
        "modified": len(forms["modified"]) + len(documents["modified"]) + len(stages["modified"]),
        "total": len(changes),
    }
    return {
        "forms": forms,
        "documents": documents,
        "stages": stages,
        "changes": changes,
        "counts": counts,
        "requires_force": requires_force,
    }


__all__ = ["SEVERITY_BREAKING", "SEVERITY_INFO", "SEVERITY_WARN", "diff_specs"]
