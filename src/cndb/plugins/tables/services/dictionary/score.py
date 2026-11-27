"""标准符合度指标（ADR 0188 C4）.

把「数据标准」从一份文档变成可度量的一组数字 —— 这是让治理长期有效的唯一办法：
文档能读，但只有指标能进周会。

六项指标，全部是「有 / 无」二值的占比（不做加权评分，避免造出一个没人信服的分数）：

| 指标 | 分母 | 分子 |
|---|---|---|
| 业务说明覆盖 | 全部字段 | `business_meaning` 非空 |
| 枚举受控率 | 全部字段 | 枚举字段（select / multiselect）占非空字段的比例 —— 此项衡量「该用枚举的用了枚举」 |
| 命名规范命中 | 全部字段 | 不含空格 / 标点，且长度 ≤ 64 |
| 必填覆盖 | 全部字段 | `required` 或配置了 `required_when` |
| 敏感级标注 | 全部字段 | `sensitivity` 显式设置（非 NULL） |
| 示例值覆盖 | 全部字段 | `example_value` 非空 |

每项都返回 `covered` / `total` / `ratio` 与 `missing_fields`（缺口字段名，便于点击跳转补录）。
"""

from __future__ import annotations

import re
from typing import Any

from cndb.plugins.tables.models import DataField

#: 命名规范：不含空白与标点，长度 1..64（与 ADR 0019 的中文字段口径一致：中文短名与 snake_case 都可）
_NAME_PATTERN = re.compile(r"^[^\s\W]{1,64}$", re.UNICODE)
#: 允许出现在字段名里的分隔符（snake_case / kebab 都算合规）
_NAME_ALLOWED_EXTRA = re.compile(r"^[\w\-]{1,64}$", re.UNICODE)

#: 指标键 → 中文名（前端直接展示）
METRIC_LABELS: dict[str, str] = {
    "business_meaning": "业务说明覆盖",
    "enum_controlled": "枚举受控率",
    "naming": "命名规范命中",
    "required": "必填覆盖",
    "sensitivity": "敏感级标注",
    "example_value": "示例值覆盖",
}


def _name_ok(name: str) -> bool:
    """字段名是否合规：中文 / 字母 / 数字，允许 `_` 与 `-`，无空格标点，长度 ≤ 64."""
    if not name or len(name) > 64:
        return False
    # 先排掉任何空白 / 标点（`\W` 在 unicode 下把中文视为 word 字符，符合中文短名口径）
    if _NAME_PATTERN.match(name):
        return True
    return bool(_NAME_ALLOWED_EXTRA.match(name))


def _metric(covered: list[str], total: list[str]) -> dict[str, Any]:
    """组装单项指标（covered / total / ratio / missing_fields）."""
    total_count = len(total)
    ratio = round(len(covered) / total_count, 4) if total_count else 1.0
    missing = [name for name in total if name not in set(covered)]
    return {
        "covered": len(covered),
        "total": total_count,
        "ratio": ratio,
        "missing_fields": missing,
    }


def compute_score(fields: list[DataField]) -> dict[str, Any]:
    """计算符合度指标（fields 须为已按可见性裁剪后的字段列表）.

    Returns:
        ``{"metrics": {key: {...}}, "overall": {...}, "field_count": N}``；
        ``overall.ratio`` 是六项指标的平均值（纯参考，不参与任何门禁）。
    """
    names = [f.name for f in fields]
    meaning = [f.name for f in fields if (f.business_meaning or "").strip()]
    enums = [f.name for f in fields if f.field_type in ("select", "multiselect")]
    naming = [f.name for f in fields if _name_ok(f.name)]
    required = [f.name for f in fields if f.required or isinstance((f.config or {}).get("required_when"), dict)]
    sensitivity = [f.name for f in fields if (f.sensitivity or "").strip()]
    example = [f.name for f in fields if (f.example_value or "").strip()]

    metrics = {
        "business_meaning": _metric(meaning, names),
        "enum_controlled": _metric(enums, names),
        "naming": _metric(naming, names),
        "required": _metric(required, names),
        "sensitivity": _metric(sensitivity, names),
        "example_value": _metric(example, names),
    }
    ratios = [m["ratio"] for m in metrics.values()]
    overall_ratio = round(sum(ratios) / len(ratios), 4) if ratios else 1.0
    return {
        "field_count": len(fields),
        "metrics": metrics,
        "metric_labels": METRIC_LABELS,
        "overall": {
            "ratio": overall_ratio,
            "covered": sum(m["covered"] for m in metrics.values()),
            "total": sum(m["total"] for m in metrics.values()),
        },
    }


__all__ = ["METRIC_LABELS", "compute_score"]
