"""模板规格（spec）校验与归一化（需求 0094 C2/C3）.

规格是模板的唯一真相源（JSON），结构：

```
{
  "forms": [{"key","name","description","fields":[{"name","type","required","config"}]}],
  "documents": [{"key","title","required","naming","content"}],
  "stages": [{"key","name","description","order","forms":[key],"documents":[key]}]
}
```

校验在**写路径**统一执行：保存草稿、预览影响、创建模板都先过 ``normalize_spec``，
因此运行期（实例化 / 门禁 / diff）不会遇到结构错误。
"""

from __future__ import annotations

import re
from typing import Any

from cndb.plugins.tables.field_types import default_registry, normalize_field_type

#: key 允许字母 / 数字 / 下划线 / 连字符 / 中文（模板作者可读），不超过 64 字符
_KEY_RE = re.compile(r"^[\w\u4e00-\u9fff-]{1,64}$")
_STAGE_KEYS = {"key", "name", "description", "order", "forms", "documents"}
_FORM_KEYS = {"key", "name", "description", "fields", "flow"}
_DOC_KEYS = {"key", "title", "required", "naming", "content"}
_FIELD_KEYS = {"name", "type", "required", "is_unique", "config", "default_value", "hidden"}
_FORM_FLOW_KEYS = {
    "enabled",
    "list_fields",
    "search_fields",
    "form_groups",
    "detail_groups",
    "hints",
    "default_values",
    "allow_create",
    "allow_edit",
    "allow_delete",
    "default_sort",
    "empty_text",
}
_GROUP_KEYS = {"title", "fields"}
_DATA_FLOW_KEYS = {"key", "name", "description", "stage", "steps"}
_STEP_KEYS = {"key", "name", "description", "form", "documents"}


class TemplateSpecError(ValueError):
    """模板规格非法（路由层转 422）."""


def _err(path: str, message: str) -> TemplateSpecError:
    return TemplateSpecError(f"{path}：{message}")


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _err(path, "必须是对象")
    return value


def _require_list(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        raise _err(path, "必须是数组")
    return value


def _require_str(value: Any, path: str, *, max_len: int = 500, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise _err(path, "必须是字符串")
    text = value.strip()
    if not text and not allow_empty:
        raise _err(path, "不能为空")
    if len(text) > max_len:
        raise _err(path, f"长度不能超过 {max_len}")
    return text


def _check_keys(raw: dict[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise _err(path, f"含未知字段：{', '.join(unknown)}")


def _normalize_key(value: Any, path: str) -> str:
    key = _require_str(value, path, max_len=64)
    if not _KEY_RE.fullmatch(key):
        raise _err(path, "只能包含字母 / 数字 / 下划线 / 连字符 / 中文，且不超过 64 字符")
    return key


def _normalize_fields(raw_fields: Any, path: str) -> list[dict[str, Any]]:
    fields = _require_list(raw_fields, path)
    if not fields:
        raise _err(path, "至少定义一个字段")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, raw in enumerate(fields):
        item_path = f"{path}[{idx}]"
        item = _require_dict(raw, item_path)
        _check_keys(item, _FIELD_KEYS, item_path)
        name = _require_str(item.get("name"), f"{item_path}.name", max_len=255)
        if name in seen:
            raise _err(f"{item_path}.name", f"字段名重复：{name}")
        seen.add(name)
        field_type = _require_str(item.get("type"), f"{item_path}.type", max_len=32)
        normalized_type = normalize_field_type(field_type)
        if default_registry.get(normalized_type) is None:
            choices = "、".join(name for name, _ in default_registry.choices())
            raise _err(f"{item_path}.type", f"未知字段类型：{field_type}（可选：{choices}）")
        config = item.get("config", {})
        if not isinstance(config, dict):
            raise _err(f"{item_path}.config", "必须是对象")
        normalized: dict[str, Any] = {
            "name": name,
            "type": normalized_type,
            "required": bool(item.get("required", False)),
            "is_unique": bool(item.get("is_unique", False)),
            "config": config,
            "hidden": bool(item.get("hidden", False)),
        }
        if "default_value" in item:
            normalized["default_value"] = item["default_value"]
        result.append(normalized)
    return result


def _default_flow(fields: list[dict[str, Any]]) -> dict[str, Any]:
    """未配置 flow 时派生一份可用默认值（列表前 6 字段、全部字段一组）."""
    names = [f["name"] for f in fields if not f.get("hidden")]
    all_names = [f["name"] for f in fields]
    searchable = [
        f["name"]
        for f in fields
        if not f.get("hidden")
        and f.get("type") in {"text", "longtext", "email", "url", "phone", "select", "multiselect"}
    ]
    return {
        "enabled": True,
        "list_fields": names[:6] or all_names[:6],
        "search_fields": searchable[:3] or names[:3],
        "form_groups": [{"title": "基本信息", "fields": names or all_names}],
        "detail_groups": [{"title": "基本信息", "fields": names or all_names}],
        "hints": {},
        "default_values": {},
        "allow_create": True,
        "allow_edit": True,
        "allow_delete": True,
        "default_sort": None,
        "empty_text": "",
    }


def _normalize_field_refs(
    value: Any,
    field_names: set[str],
    path: str,
    *,
    default: list[str],
) -> list[str]:
    if value is None:
        return list(default)
    refs = _require_list(value, path)
    if not refs:
        return list(default)
    result: list[str] = []
    for ref in refs:
        name = _require_str(ref, path, max_len=255)
        if name not in field_names:
            raise _err(path, f"引用了不存在的字段：{name}")
        if name not in result:
            result.append(name)
    return result


def _normalize_groups(
    value: Any,
    fields: list[dict[str, Any]],
    path: str,
    *,
    fallback: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    field_names = {f["name"] for f in fields}
    if value is None:
        return [
            {"title": g["title"], "fields": list(g["fields"])}
            for g in (fallback or _default_flow(fields)["form_groups"])
        ]
    groups = _require_list(value, path)
    if not groups:
        return [
            {"title": g["title"], "fields": list(g["fields"])}
            for g in (fallback or _default_flow(fields)["form_groups"])
        ]
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    for idx, raw in enumerate(groups):
        item_path = f"{path}[{idx}]"
        item = _require_dict(raw, item_path)
        _check_keys(item, _GROUP_KEYS, item_path)
        title = _require_str(item.get("title"), f"{item_path}.title", max_len=120)
        names = _require_list(item.get("fields"), f"{item_path}.fields")
        if not names:
            raise _err(f"{item_path}.fields", "至少包含一个字段")
        group_fields: list[str] = []
        for ref in names:
            name = _require_str(ref, f"{item_path}.fields", max_len=255)
            if name not in field_names:
                raise _err(f"{item_path}.fields", f"引用了不存在的字段：{name}")
            if name in used:
                raise _err(f"{item_path}.fields", f"字段重复分组：{name}")
            used.add(name)
            group_fields.append(name)
        result.append({"title": title, "fields": group_fields})
    # 新加字段未纳入配置时自动补进「其他信息」，避免数据流程里看不到字段
    remaining = [f["name"] for f in fields if f["name"] not in used and not f.get("hidden")]
    if remaining:
        result.append({"title": "其他信息", "fields": remaining})
    return result


def _normalize_flow(raw: Any, fields: list[dict[str, Any]], path: str) -> dict[str, Any]:
    """表单数据流程配置（可配置的增删查改界面）."""
    default = _default_flow(fields)
    if raw is None:
        return default
    flow = _require_dict(raw, path)
    _check_keys(flow, _FORM_FLOW_KEYS, path)
    field_names = {f["name"] for f in fields}
    list_fields = _normalize_field_refs(
        flow.get("list_fields"), field_names, f"{path}.list_fields", default=default["list_fields"]
    )
    search_fields = _normalize_field_refs(
        flow.get("search_fields"), field_names, f"{path}.search_fields", default=default["search_fields"]
    )
    form_groups = _normalize_groups(flow.get("form_groups"), fields, f"{path}.form_groups", fallback=None)
    detail_groups = _normalize_groups(flow.get("detail_groups"), fields, f"{path}.detail_groups", fallback=form_groups)
    hints_raw = flow.get("hints", {})
    if not isinstance(hints_raw, dict):
        raise _err(f"{path}.hints", "必须是对象（字段名 → 提示文案）")
    hints: dict[str, str] = {}
    for key, value in hints_raw.items():
        if key not in field_names:
            raise _err(f"{path}.hints", f"引用了不存在的字段：{key}")
        hints[str(key)] = _require_str(value, f"{path}.hints.{key}", max_len=500, allow_empty=True)
    defaults_raw = flow.get("default_values", {})
    if not isinstance(defaults_raw, dict):
        raise _err(f"{path}.default_values", "必须是对象（字段名 → 默认值）")
    default_values: dict[str, Any] = {}
    for key, value in defaults_raw.items():
        if key not in field_names:
            raise _err(f"{path}.default_values", f"引用了不存在的字段：{key}")
        default_values[str(key)] = value
    default_sort: dict[str, str] | None = None
    sort_raw = flow.get("default_sort")
    if sort_raw is not None:
        sort = _require_dict(sort_raw, f"{path}.default_sort")
        _check_keys(sort, {"field", "order"}, f"{path}.default_sort")
        field = _require_str(sort.get("field"), f"{path}.default_sort.field", max_len=255)
        if field not in field_names:
            raise _err(f"{path}.default_sort.field", f"引用了不存在的字段：{field}")
        order = _require_str(sort.get("order", "asc"), f"{path}.default_sort.order", max_len=8)
        if order not in {"asc", "desc"}:
            raise _err(f"{path}.default_sort.order", "只能是 asc / desc")
        default_sort = {"field": field, "order": order}
    return {
        "enabled": bool(flow.get("enabled", True)),
        "list_fields": list_fields,
        "search_fields": search_fields,
        "form_groups": form_groups,
        "detail_groups": detail_groups,
        "hints": hints,
        "default_values": default_values,
        "allow_create": bool(flow.get("allow_create", True)),
        "allow_edit": bool(flow.get("allow_edit", True)),
        "allow_delete": bool(flow.get("allow_delete", True)),
        "default_sort": default_sort,
        "empty_text": _require_str(flow.get("empty_text", ""), f"{path}.empty_text", max_len=200, allow_empty=True),
    }


def _normalize_forms(raw_forms: Any) -> list[dict[str, Any]]:
    forms = _require_list(raw_forms, "forms")
    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_names: set[str] = set()
    for idx, raw in enumerate(forms):
        path = f"forms[{idx}]"
        item = _require_dict(raw, path)
        _check_keys(item, _FORM_KEYS, path)
        key = _normalize_key(item.get("key"), f"{path}.key")
        if key in seen_keys:
            raise _err(f"{path}.key", f"表单 key 重复：{key}")
        seen_keys.add(key)
        name = _require_str(item.get("name"), f"{path}.name", max_len=255)
        if name in seen_names:
            raise _err(f"{path}.name", f"表单名重复：{name}")
        seen_names.add(name)
        fields = _normalize_fields(item.get("fields"), f"{path}.fields")
        result.append(
            {
                "key": key,
                "name": name,
                "description": _require_str(
                    item.get("description", ""), f"{path}.description", max_len=2000, allow_empty=True
                ),
                "fields": fields,
                "flow": _normalize_flow(item.get("flow"), fields, f"{path}.flow"),
            }
        )
    return result


def _normalize_documents(raw_documents: Any) -> list[dict[str, Any]]:
    documents = _require_list(raw_documents, "documents")
    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_titles: set[str] = set()
    for idx, raw in enumerate(documents):
        path = f"documents[{idx}]"
        item = _require_dict(raw, path)
        _check_keys(item, _DOC_KEYS, path)
        key = _normalize_key(item.get("key"), f"{path}.key")
        if key in seen_keys:
            raise _err(f"{path}.key", f"文档 key 重复：{key}")
        seen_keys.add(key)
        title = _require_str(item.get("title"), f"{path}.title", max_len=500)
        if title in seen_titles:
            raise _err(f"{path}.title", f"文档标题重复：{title}")
        seen_titles.add(title)
        result.append(
            {
                "key": key,
                "title": title,
                "required": bool(item.get("required", True)),
                "naming": _require_str(item.get("naming", ""), f"{path}.naming", max_len=500, allow_empty=True),
                "content": _require_str(item.get("content", ""), f"{path}.content", max_len=200_000, allow_empty=True),
            }
        )
    return result


def _normalize_data_flows(
    raw_flows: Any, form_keys: set[str], doc_keys: set[str], stage_keys: set[str]
) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    """端到端流程：一条流程 = 有序步骤；步骤可绑定表单（数据 CRUD）/ 文档规则.

    与生命周期 ``stages`` 解耦：stages 负责阶段门禁，flows 负责业务过程展示。
    表单 / 文档只要被 stages 或 flows 任一引用即不算孤儿。
    """
    if raw_flows is None:
        return [], set(), set()
    flows = _require_list(raw_flows, "flows")
    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    used_forms: set[str] = set()
    used_docs: set[str] = set()
    for idx, raw in enumerate(flows):
        path = f"flows[{idx}]"
        item = _require_dict(raw, path)
        _check_keys(item, _DATA_FLOW_KEYS, path)
        key = _normalize_key(item.get("key"), f"{path}.key")
        if key in seen_keys:
            raise _err(f"{path}.key", f"流程 key 重复：{key}")
        seen_keys.add(key)
        stage_key = item.get("stage")
        if stage_key is not None:
            stage_key = _require_str(stage_key, f"{path}.stage", max_len=64)
            if stage_key not in stage_keys:
                raise _err(f"{path}.stage", f"引用了不存在的阶段：{stage_key}")
        steps_raw = _require_list(item.get("steps"), f"{path}.steps")
        if not steps_raw:
            raise _err(f"{path}.steps", "至少定义一个流程步骤")
        steps: list[dict[str, Any]] = []
        seen_steps: set[str] = set()
        for s_idx, raw_step in enumerate(steps_raw):
            step_path = f"{path}.steps[{s_idx}]"
            step = _require_dict(raw_step, step_path)
            _check_keys(step, _STEP_KEYS, step_path)
            step_key = _normalize_key(step.get("key"), f"{step_path}.key")
            if step_key in seen_steps:
                raise _err(f"{step_path}.key", f"步骤 key 重复：{step_key}")
            seen_steps.add(step_key)
            form_key = step.get("form")
            if form_key is not None:
                form_key = _require_str(form_key, f"{step_path}.form", max_len=64)
                if form_key not in form_keys:
                    raise _err(f"{step_path}.form", f"引用了不存在的表单：{form_key}")
                used_forms.add(form_key)
            doc_refs = _require_list(step.get("documents", []), f"{step_path}.documents")
            step_docs: list[str] = []
            for ref in doc_refs:
                doc_key = _require_str(ref, f"{step_path}.documents", max_len=64)
                if doc_key not in doc_keys:
                    raise _err(f"{step_path}.documents", f"引用了不存在的文档规则：{doc_key}")
                if doc_key not in step_docs:
                    step_docs.append(doc_key)
                used_docs.add(doc_key)
            steps.append(
                {
                    "key": step_key,
                    "name": _require_str(step.get("name"), f"{step_path}.name", max_len=120),
                    "description": _require_str(
                        step.get("description", ""), f"{step_path}.description", max_len=2000, allow_empty=True
                    ),
                    "form": form_key,
                    "documents": step_docs,
                }
            )
        result.append(
            {
                "key": key,
                "name": _require_str(item.get("name"), f"{path}.name", max_len=120),
                "description": _require_str(
                    item.get("description", ""), f"{path}.description", max_len=2000, allow_empty=True
                ),
                "stage": stage_key,
                "steps": steps,
            }
        )
    return result, used_forms, used_docs


def _normalize_stages(raw_stages: Any, form_keys: set[str], doc_keys: set[str]) -> list[dict[str, Any]]:
    stages = _require_list(raw_stages, "stages")
    if not stages:
        raise _err("stages", "至少定义一个生命周期阶段")
    result: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    seen_orders: set[int] = set()
    used_forms: set[str] = set()
    used_docs: set[str] = set()
    for idx, raw in enumerate(stages):
        path = f"stages[{idx}]"
        item = _require_dict(raw, path)
        _check_keys(item, _STAGE_KEYS, path)
        key = _normalize_key(item.get("key"), f"{path}.key")
        if key in seen_keys:
            raise _err(f"{path}.key", f"阶段 key 重复：{key}")
        seen_keys.add(key)
        order = item.get("order", idx + 1)
        if not isinstance(order, int) or isinstance(order, bool) or order < 1:
            raise _err(f"{path}.order", "必须是 ≥1 的整数")
        if order in seen_orders:
            raise _err(f"{path}.order", f"阶段顺序重复：{order}")
        seen_orders.add(order)

        form_refs = _require_list(item.get("forms", []), f"{path}.forms")
        doc_refs = _require_list(item.get("documents", []), f"{path}.documents")
        stage_forms: list[str] = []
        for ref in form_refs:
            ref_key = _require_str(ref, f"{path}.forms", max_len=64)
            if ref_key not in form_keys:
                raise _err(f"{path}.forms", f"引用了不存在的表单：{ref_key}")
            if ref_key in stage_forms:
                raise _err(f"{path}.forms", f"表单重复引用：{ref_key}")
            stage_forms.append(ref_key)
            used_forms.add(ref_key)
        stage_docs: list[str] = []
        for ref in doc_refs:
            ref_key = _require_str(ref, f"{path}.documents", max_len=64)
            if ref_key not in doc_keys:
                raise _err(f"{path}.documents", f"引用了不存在的文档规则：{ref_key}")
            if ref_key in stage_docs:
                raise _err(f"{path}.documents", f"文档规则重复引用：{ref_key}")
            stage_docs.append(ref_key)
            used_docs.add(ref_key)
        result.append(
            {
                "key": key,
                "name": _require_str(item.get("name"), f"{path}.name", max_len=120),
                "description": _require_str(
                    item.get("description", ""), f"{path}.description", max_len=2000, allow_empty=True
                ),
                "order": order,
                "forms": stage_forms,
                "documents": stage_docs,
            }
        )
    result.sort(key=lambda s: s["order"])
    return result


def normalize_spec(raw: Any) -> dict[str, Any]:
    """校验并归一化模板规格；非法时抛 :class:`TemplateSpecError`（中文可读）."""
    spec = _require_dict(raw, "spec")
    _check_keys(spec, {"forms", "documents", "stages", "flows"}, "spec")
    forms = _normalize_forms(spec.get("forms", []))
    documents = _normalize_documents(spec.get("documents", []))
    if not forms and not documents:
        raise _err("spec", "至少定义一个表单或文档规则")
    form_keys = {f["key"] for f in forms}
    doc_keys = {d["key"] for d in documents}
    stages = _normalize_stages(spec.get("stages"), form_keys, doc_keys)
    flows, flow_forms, flow_docs = _normalize_data_flows(
        spec.get("flows"), form_keys, doc_keys, {stage["key"] for stage in stages}
    )
    used_forms = {ref for stage in stages for ref in stage["forms"]} | flow_forms
    used_docs = {ref for stage in stages for ref in stage["documents"]} | flow_docs
    orphan_forms = sorted(form_keys - used_forms)
    if orphan_forms:
        raise _err("forms", f"表单未被任何阶段 / 流程引用：{', '.join(orphan_forms)}")
    orphan_docs = sorted(doc_keys - used_docs)
    if orphan_docs:
        raise _err("documents", f"文档规则未被任何阶段 / 流程引用：{', '.join(orphan_docs)}")
    return {"forms": forms, "documents": documents, "stages": stages, "flows": flows}


def spec_counts(spec: dict[str, Any]) -> dict[str, int]:
    """规格规模摘要（列表 / 详情展示）."""
    return {
        "stage_count": len(spec.get("stages", [])),
        "form_count": len(spec.get("forms", [])),
        "field_count": sum(len(f.get("fields", [])) for f in spec.get("forms", [])),
        "document_rule_count": len(spec.get("documents", [])),
        "flow_count": len(spec.get("flows", [])),
        "step_count": sum(len(f.get("steps", [])) for f in spec.get("flows", [])),
    }


__all__ = ["TemplateSpecError", "normalize_spec", "spec_counts"]
