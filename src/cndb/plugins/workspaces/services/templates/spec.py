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
_FORM_KEYS = {"key", "name", "description", "fields"}
_DOC_KEYS = {"key", "title", "required", "naming", "content"}
_FIELD_KEYS = {"name", "type", "required", "is_unique", "config", "default_value", "hidden"}


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
        result.append(
            {
                "key": key,
                "name": name,
                "description": _require_str(
                    item.get("description", ""), f"{path}.description", max_len=2000, allow_empty=True
                ),
                "fields": _normalize_fields(item.get("fields"), f"{path}.fields"),
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
    orphan_forms = sorted(form_keys - used_forms)
    if orphan_forms:
        raise _err("forms", f"表单未被任何阶段引用：{', '.join(orphan_forms)}")
    orphan_docs = sorted(doc_keys - used_docs)
    if orphan_docs:
        raise _err("documents", f"文档规则未被任何阶段引用：{', '.join(orphan_docs)}")
    result.sort(key=lambda s: s["order"])
    return result


def normalize_spec(raw: Any) -> dict[str, Any]:
    """校验并归一化模板规格；非法时抛 :class:`TemplateSpecError`（中文可读）."""
    spec = _require_dict(raw, "spec")
    _check_keys(spec, {"forms", "documents", "stages"}, "spec")
    forms = _normalize_forms(spec.get("forms", []))
    documents = _normalize_documents(spec.get("documents", []))
    if not forms and not documents:
        raise _err("spec", "至少定义一个表单或文档规则")
    form_keys = {f["key"] for f in forms}
    doc_keys = {d["key"] for d in documents}
    stages = _normalize_stages(spec.get("stages"), form_keys, doc_keys)
    return {"forms": forms, "documents": documents, "stages": stages}


def spec_counts(spec: dict[str, Any]) -> dict[str, int]:
    """规格规模摘要（列表 / 详情展示）."""
    return {
        "stage_count": len(spec.get("stages", [])),
        "form_count": len(spec.get("forms", [])),
        "field_count": sum(len(f.get("fields", [])) for f in spec.get("forms", [])),
        "document_rule_count": len(spec.get("documents", [])),
    }


__all__ = ["TemplateSpecError", "normalize_spec", "spec_counts"]
