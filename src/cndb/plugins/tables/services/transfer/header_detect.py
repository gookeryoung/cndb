"""表头行自动识别 —— 兼容表格顶部存在标题行 / 合并行的情况.

**问题**：Excel/CSV 文件的首行不一定是表头。常见形态是顶部先有
一行（或多行）跨列合并的标题，例如::

    A1:D1  2024 年销售报表          （合并单元格，值只写在 A1）
    A2:D2  产品 | 价格 | 库存 | 备注  （真正的表头）
    A3:D3  手机 | 2999 | 100 | ...

旧实现固定把第一个非空行当表头，这类文件会把「2024 年销售报表」当成唯一
列名，其余列因空列名直接报错或整表列错位。

**本模块的做法**：对文件前 ``HEADER_SCAN_ROWS`` 个非空行逐行打分，再按
softmax 归一为概率：表头行通常「列覆盖率高、几乎全是文本、值互不重复、
与下方数据行的类型有明显反差」，标题/合并行则「只填了少数单元格」。
最终返回最优行、概率（0~1）与候选列表，前端据此提示用户并允许改选。

**单一入口**：:func:`detect_header_row`。新建表导入（``spreadsheet``）与
已有表导入（``importing.importer``）都必须复用它，避免两套判定口径漂移。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from cndb.plugins.tables.services.transfer.normalize import _infer_single_value

#: 参与打分的最大行数（只扫文件头部，避免大文件全量物化）
HEADER_SCAN_ROWS = 20
#: 候选列表最多返回的行数
MAX_CANDIDATES = 5
#: 低于该概率时标记「建议人工确认」
REVIEW_CONFIDENCE = 0.6
#: softmax 温度：越小越「赢者通吃」
_TEMPERATURE = 0.5
#: 首行先验：常规文件表头就在第一行（标题行会被 title_penalty 压掉）
_FIRST_ROW_PRIOR = 1.2
#: 预览单元格文本最大长度
_CELL_PREVIEW_LEN = 24
_MAX_CELLS = 6
#: 参与类型反差的后续数据行数
_CONTRAST_ROWS = 5

#: 视为「文本型」的单元格类型（表头几乎都是这些）
_TEXT_LIKE_TYPES = frozenset({"text", "email", "url", "phone"})
#: 视为「数值/日期型」的单元格类型（数据行的典型特征）
_VALUE_LIKE_TYPES = frozenset(
    {
        "number",
        "float",
        "percentage",
        "date",
        "datetime",
        "boolean",
        "number_text",
    }
)


@dataclass(frozen=True)
class HeaderCandidate:
    """单个候选表头行."""

    row: int
    """1 基行号（文件中的非空行序号；无空行时等于 Excel 行号）."""
    confidence: float
    """该行作为表头的概率（0~1）."""
    values: list[str] = field(default_factory=list)
    """前几个单元格的文本预览."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "confidence": round(self.confidence, 4),
            "values": list(self.values),
        }


@dataclass(frozen=True)
class HeaderDetection:
    """表头行识别结果."""

    index: int
    """0 基下标（在传入的非空行序列中的位置）."""
    confidence: float
    """识别概率（0~1）."""
    requires_review: bool
    """是否建议人工确认（概率偏低 / 缺少数据行佐证）."""
    candidates: list[HeaderCandidate] = field(default_factory=list)
    """候选表头行（按概率从高到低，最多 ``MAX_CANDIDATES`` 个）."""

    @property
    def row(self) -> int:
        """1 基行号."""
        return self.index + 1

    @property
    def skipped_rows(self) -> int:
        """表头上方被跳过的行数（标题 / 合并行）."""
        return self.index

    @property
    def message(self) -> str:
        """面向用户的中文提示."""
        percent = round(self.confidence * 100)
        if self.skipped_rows > 0:
            text = (
                f"已自动识别第 {self.row} 行为表头（置信度 {percent}%，已跳过上方 {self.skipped_rows} 行标题/合并行）"
            )
        else:
            text = f"已自动识别第 {self.row} 行为表头（置信度 {percent}%）"
        if self.requires_review:
            text += "；置信度偏低，建议核对识别结果"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "row": self.row,
            "confidence": round(self.confidence, 4),
            "requires_review": self.requires_review,
            "skipped_rows": self.skipped_rows,
            "message": self.message,
            "candidates": [c.to_dict() for c in self.candidates],
        }


# ── 单元格分类 ────────────────────────────────────


def _cell_type(value: Any) -> str:
    """把单元格值归类为推断类型（空值为 ``empty``）."""
    if value is None:
        return "empty"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    text = str(value).strip()
    if not text:
        return "empty"
    return _infer_single_value(text)


def _cell_text(value: Any) -> str:
    """单元格 → 去空白文本（空值返回空串）."""
    if value is None:
        return ""
    return str(value).strip()


def _preview_values(row: Sequence[Any]) -> list[str]:
    """截取一行前若干个单元格做预览（过长截断，空值保留空串占位）."""
    out: list[str] = []
    for value in row[:_MAX_CELLS]:
        text = _cell_text(value)
        out.append(text[:_CELL_PREVIEW_LEN])
    return out


# ── 打分 ─────────────────────────────────────────


def _row_metrics(
    rows: Sequence[Sequence[Any]],
    index: int,
    width: int,
) -> dict[str, float]:
    """计算单行的表头可能性指标（全部归一化到 0~1，反差项 -1~1）."""
    row = rows[index]
    cells = [_cell_text(v) for v in row]
    types = [_cell_type(v) for v in row]

    nonblank = [i for i, (text, typ) in enumerate(zip(cells, types, strict=False)) if text and typ != "empty"]
    count = len(nonblank)
    if count == 0:
        return {"empty": 1.0}

    coverage = min(1.0, count / width)
    text_like = sum(1 for i in nonblank if types[i] in _TEXT_LIKE_TYPES)
    value_like = sum(1 for i in nonblank if types[i] in _VALUE_LIKE_TYPES)
    text_ratio = text_like / count
    value_ratio = value_like / count

    # 唯一性：表头列名通常互不重复；数据行（如部门 / 状态）常有重复
    unique_ratio = len({cells[i].casefold() for i in nonblank}) / count

    # 短文本比例：表头一般简短
    short_ratio = sum(1 for i in nonblank if len(cells[i]) <= 40) / count

    # 表头单元格中间的空洞比例（标题行常见「只在 A 列写值」）
    last_filled = max(nonblank)
    span = last_filled + 1
    filled_in_span = sum(1 for i in range(span) if i in set(nonblank))
    hole_ratio = 1.0 - filled_in_span / span

    # 与下方数据行的类型反差：表头是文本、数据是数值/日期 → +；反之 →
    below = rows[index + 1 : index + 1 + _CONTRAST_ROWS]
    contrast = 0.0
    compared = 0
    for col in nonblank:
        if types[col] not in _TEXT_LIKE_TYPES:
            continue
        below_types = [_cell_type(r[col]) if col < len(r) else "empty" for r in below]
        below_nonblank = [t for t in below_types if t != "empty"]
        if not below_nonblank:
            continue
        compared += 1
        value_share = sum(1 for t in below_nonblank if t in _VALUE_LIKE_TYPES) / len(below_nonblank)
        if value_share >= 0.5:
            contrast += 1.0
        elif value_share == 0:
            contrast -= 0.5
    if compared:
        contrast /= compared
    contrast = max(-1.0, min(1.0, contrast))

    # 上方行越稀疏，越像「标题行 + 表头」；上方同样密则首个非空行更可能是表头
    above_coverages = []
    for prev in rows[:index]:
        prev_count = sum(1 for v in prev if _cell_text(v))
        above_coverages.append(min(1.0, prev_count / width))
    above_bonus = 0.0
    if above_coverages:
        above_avg = sum(above_coverages) / len(above_coverages)
        if above_avg <= coverage - 0.2:
            above_bonus = 1.0
        elif above_avg >= coverage - 0.05:
            above_bonus = -0.3

    # 标题/合并行：本行稀疏但紧邻下一行很密
    title_penalty = 0.0
    next_coverage = 0.0
    if index + 1 < len(rows):
        next_count = sum(1 for v in rows[index + 1] if _cell_text(v))
        next_coverage = min(1.0, next_count / width)
    if coverage <= 0.4 and next_coverage >= 0.75:
        title_penalty = 1.0

    no_data_below = 0.0 if below else 1.0

    return {
        "empty": 0.0,
        "coverage": coverage,
        "text_ratio": text_ratio,
        "value_ratio": value_ratio,
        "unique_ratio": unique_ratio,
        "short_ratio": short_ratio,
        "hole_ratio": hole_ratio,
        "contrast": contrast,
        "above_bonus": above_bonus,
        "title_penalty": title_penalty,
        "no_data_below": no_data_below,
        "count": float(count),
    }


def _score(metrics: Mapping[str, float], index: int) -> float:
    """把指标压成单一分数；越像表头越高."""
    if metrics.get("empty", 0.0) == 1.0:
        return -math.inf
    detail = (
        2.2 * metrics["coverage"]
        + 2.6 * metrics["text_ratio"]
        + 1.2 * metrics["unique_ratio"]
        + 0.8 * metrics["short_ratio"]
        + 1.3 * metrics["contrast"]
        + 0.8 * metrics["above_bonus"]
        - 1.8 * metrics["hole_ratio"]
        - 1.5 * metrics["title_penalty"]
        - 0.5 * metrics["value_ratio"]
        - 0.8 * metrics["no_data_below"]
    )
    # 首行先验 + 平局时偏向更靠前的行（文件顶部默认是表头）
    prior = _FIRST_ROW_PRIOR if index == 0 else 0.0
    return detail + prior + 0.15 / (1 + index)


def _softmax(scores: Sequence[float]) -> list[float]:
    """数值稳定的 softmax；-inf 得 0."""
    finite = [s / _TEMPERATURE for s in scores if math.isfinite(s)]
    if not finite:
        return [0.0 for _ in scores]
    top = max(finite)
    exps = [math.exp(s / _TEMPERATURE - top) if math.isfinite(s) else 0.0 for s in scores]
    total = sum(exps)
    if total <= 0:  # pragma: no cover - 理论上不会发生
        return [0.0 for _ in scores]
    return [e / total for e in exps]


def detect_header_row(
    rows: Sequence[Sequence[Any]],
    *,
    max_scan: int = HEADER_SCAN_ROWS,
    preferred_index: int | None = None,
) -> HeaderDetection | None:
    """识别表头所在行并给出概率.

    Args:
        rows: **非空行**的原始单元格序列（与列对齐，允许长度参差）；
            调用方应已跳过完全空白的行。
        max_scan: 参与打分的最大行数。
        preferred_index: 用户指定的表头行下标（0 基）。传入时以该行为最终结果，
            但概率仍按打分模型计算，用于展示。

    Returns:
        :class:`HeaderDetection`；``rows`` 为空时返回 ``None``。
    """
    scanned = [list(r) for r in rows[: max(1, max_scan)]]
    if not scanned:
        return None

    width = max((len(r) for r in scanned), default=0)
    if width <= 0:
        return None

    metrics = [_row_metrics(scanned, index, width) for index in range(len(scanned))]
    scores = [_score(metric, index) for index, metric in enumerate(metrics)]
    # 文件最后一个非空行不可能是表头（除非整份文件只有一行）：
    # 这一先验专门兜住「表头有空洞 → 检测误选下方全文本数据行」的情况，
    # 让空列名/重复列名等结构守卫继续在真正的表头行上报错。
    if len(scanned) > 1 and len(scanned) < max(1, max_scan):
        last = len(scanned) - 1
        if math.isfinite(scores[last]):
            scores[last] -= 1.2

    probabilities = _softmax(scores)
    best = max(range(len(scores)), key=lambda i: scores[i])
    if preferred_index is not None:
        if not 0 <= preferred_index < len(scanned):
            raise ValueError(f"表头行下标 {preferred_index + 1} 超出可识别范围（共 {len(scanned)} 个非空行）")
        if not math.isfinite(scores[preferred_index]):
            raise ValueError(f"第 {preferred_index + 1} 行为空行，不能作为表头")
        best = preferred_index
    confidence = probabilities[best] if math.isfinite(scores[best]) else 0.0

    # 校准：绝对合理性（仅有相对概率不足以说明"这是表头"）
    has_data_below = best + 1 < len(scanned)
    best_metrics = metrics[best]
    if not has_data_below:
        # 没有后续数据行佐证时，概率不应显得过于确定
        confidence = min(confidence, 0.55)
    if width < 2:
        confidence = min(confidence, 0.7)
    if best_metrics["text_ratio"] < 0.5 and best_metrics["value_ratio"] > 0.5:
        # 整行几乎都是数值/日期 —— 更像表头缺失的数据行
        confidence = min(confidence, 0.45)
    confidence = max(0.0, min(0.99, confidence))
    requires_review = confidence < REVIEW_CONFIDENCE or not has_data_below

    ranked = sorted(
        (i for i in range(len(scanned)) if math.isfinite(scores[i])),
        key=lambda i: scores[i],
        reverse=True,
    )[:MAX_CANDIDATES]
    if best not in ranked:  # 用户指定行不在 Top N 时也要出现在候选里
        ranked = [best, *ranked[: MAX_CANDIDATES - 1]]
    candidates = [
        HeaderCandidate(
            row=i + 1,
            # 最优候选与最终校准后的概率保持一致，避免 UI 出现"100% 但提示置信度偏低"
            confidence=confidence if i == best else probabilities[i],
            values=_preview_values(scanned[i]),
        )
        for i in ranked
    ]

    return HeaderDetection(
        index=best,
        confidence=confidence,
        requires_review=requires_review,
        candidates=candidates,
    )


__all__ = [
    "HEADER_SCAN_ROWS",
    "MAX_CANDIDATES",
    "REVIEW_CONFIDENCE",
    "HeaderCandidate",
    "HeaderDetection",
    "detect_header_row",
]
