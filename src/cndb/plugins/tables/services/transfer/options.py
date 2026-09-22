"""select options 与样本值规整 — options 字典化、decimals 配置推断、样本去重."""

from __future__ import annotations

from typing import Any


def _options_strings_to_dicts(options: list[str]) -> list[dict[str, Any]]:
    """把 list[str] 格式的 select options 转为 [{label, value}] 字典格式.

    供 transfer / importer 在持久化 DataField.config 前调用，保证与
    SelectFieldConfig._normalize_options 及前端消费方约定一致。
    """
    return [{"label": o, "value": o} for o in options]


def _infer_decimals_config(field_type: str, sample_values: list[Any]) -> dict[str, Any]:
    """按样本推断 float/number 字段的 decimals 配置.

    根因：NumberFieldConfig.decimals 默认 0，float 字段不设置时
    ``round(5.5, 0) == 6``，导入的小数会被静默取整丢失精度.
    """
    if field_type not in ("float", "number"):
        return {}
    max_dec = 0
    for s in sample_values[:50]:
        text = str(s)
        if "." not in text:
            continue
        try:
            dec = len(text.split(".", 1)[1])
        except (TypeError, ValueError):
            continue
        max_dec = max(max_dec, dec)
    return {"decimals": min(max_dec, 10) if max_dec > 0 else 2}


def _dedupe_samples(samples: list[str], limit: int = 5) -> list[str]:
    """按首次出现顺序去重，取前 limit 个作为预览样本值.

    样本的意义在于"代表性"：前 N 个原始值大量重复时（如排序后的低基数列），
    重复值不提供额外信息，反而挤占样本位。仅去重展示层，收集端保持原样，
    不影响类型推断与 select/multiselect 提升的比例语义。
    """
    seen: set[str] = set()
    out: list[str] = []
    for v in samples:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
        if len(out) >= limit:
            break
    return out
