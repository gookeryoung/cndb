"""逐行校验器 —— 导入流水线的"守门员"阶段.

职责：对已解析成行 dict 的数据逐行逐字段校验，捕获 ValueError/TypeError，
收集成 Issue 列表；不抛异常，不让任何单行失败阻塞其他行的校验结果。

复用 :mod:`cndb.plugins.tables.field_types` 的 ``default_registry``，
每个字段类型的 ``validate_value`` 做实际的类型强转 + 业务规则校验；
RowValidator 只负责调度、空值宽松处理、link 值预解析、字段映射、缺口填充、以及结果收集.

字段映射（field_mapping）：
- ``{源字段名: 目标字段名}`` — 行 dict 的 key 会先按映射重命名再校验
- 未显式列出的字段按 源名 == 目标名 自动匹配（保守默认）
- 映射值为 None 表示该源字段跳过

缺口填充（GapFilling）：
- 当目标侧某些必填字段在源侧找不到对应列时，按策略处理：
  "empty"（默认）→ 留空，后续必填校验会标为 error
  "default"      → 用字段的 default_value 填充
  "value"        → 用用户指定的固定值填充（fill_values 参数）
  "error"        → 直接报 error，整行拒绝
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from cndb.plugins.tables.services.importing.field_mapping import (
    GapFilling,
    apply_gap_filling,
    apply_user_mapping,
    build_default_mapping,
    remap_row,
)
from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.services.core.links import is_link_field
from cndb.plugins.tables.models import DataField, DataTable

# ── 类型别名 ──────────────────────────────────────

_IssueLevel = Literal["warning", "error"]
_RowStatus = Literal["valid", "warning", "error"]


# ── 数据结构 ──────────────────────────────────────


@dataclass
class Issue:
    """单字段校验问题（warning 或 error）."""

    field: str
    level: _IssueLevel
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {"field": self.field, "level": self.level, "message": self.message}


@dataclass
class ValidationResult:
    """单行校验结果."""

    row_number: int
    values: dict[str, Any]
    status: _RowStatus = "valid"
    issues: list[Issue] = field(default_factory=list)
    # 经 validate_value 归一化后的值（与 records._normalize_values 逻辑一致）
    normalized: dict[str, Any] = field(default_factory=dict)

    def has_error(self) -> bool:
        return any(i.level == "error" for i in self.issues)

    def has_warning(self) -> bool:
        return any(i.level == "warning" for i in self.issues)

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_number": self.row_number,
            "status": self.status,
            "issues": [i.to_dict() for i in self.issues],
        }


# ── RowValidator ──────────────────────────────────


class RowValidator:
    """逐行逐字段校验器.

    Args:
        table: 目标数据表（使用其 ``active_fields()`` 定义做校验）.
        skip_unknown_columns: 文件中有但表中没有的列 → warning；设为 True 则完全忽略.
            默认 False（保留 warning，让 DiffReporter 汇总展示）.
        field_mapping: 可选的源列 → 目标字段映射，用于把源数据的列对齐到目标表字段.
            ``{源列名: 目标字段名}``；值为 None 表示跳过该源列；
            未列出的源列按 源名 == 目标名 自动匹配.
        gap_filling: 目标侧缺失字段的填充策略 — "empty" / "default" / "value" / "error".
        fill_values: gap_filling="value" 时按目标字段名指定固定填充值.
    """

    def __init__(
        self,
        table: DataTable,
        *,
        skip_unknown_columns: bool = False,
        field_mapping: dict[str, str | None] | None = None,
        gap_filling: GapFilling = "empty",
        fill_values: dict[str, Any] | None = None,
    ) -> None:
        self.table = table
        self.skip_unknown_columns = skip_unknown_columns
        self.gap_filling = gap_filling
        self.fill_values = fill_values or {}
        self._fields: list[DataField] = table.active_fields()
        self._field_map: dict[str, DataField] = {f.name: f for f in self._fields}
        self._required_names: set[str] = {f.name for f in self._fields if f.required}
        # 预编译用户 field_mapping —— 给 validate_row 直接用
        self._compiled_mapping: dict[str, str] | None = None
        self._unmapped_target: list[str] = []
        self._field_mapping = field_mapping
        if field_mapping is not None:
            # 编译：默认同名 → 用户覆盖
            # 这里假设 validate_row 的输入 row dict 的 key 是源侧列名
            # 目标侧哪些字段是 mapping 覆盖不到的（即源侧没有对应列）
            # 先在 validate_row 里按实际 row.keys() 来算更准确
            pass

    # ── 公共 API ──────────────────────────────────

    def validate_all(self, rows: list[dict[str, Any]]) -> list[ValidationResult]:
        """批量校验，返回与输入等长的结果列表."""
        return [self.validate_row(row, row_number) for row_number, row in enumerate(rows, start=1)]

    def validate_row(self, row: dict[str, Any], row_number: int) -> ValidationResult:
        """校验单行，返回 ValidationResult（永远不抛异常）."""
        result = ValidationResult(row_number=row_number, values=dict(row))

        # 1. 应用 field_mapping（或保守默认）— 把源侧 key 重命名为目标侧 key
        effective_row, unmapped_target = self._apply_mapping(row)
        result.values = effective_row

        # 2. 目标侧缺失 → 按 gap_filling 策略处理（始终生效，与 field_mapping 是否传入无关）
        if unmapped_target:
            try:
                effective_row = apply_gap_filling(
                    effective_row,
                    unmapped_target,
                    self._field_map,
                    strategy=self.gap_filling,
                    fill_values=self.fill_values,
                )
                result.values = effective_row
            except ValueError as exc:
                # strategy="error" 且存在缺失 → 直接记录 error 并提前返回
                for name in unmapped_target:
                    result.issues.append(Issue(field=name, level="error", message=str(exc)))
                result.status = "error"
                return result

        self._check_field_set(effective_row, result)
        self._check_each_field(effective_row, result)
        self._finalize_status(result)
        return result

    def _apply_mapping(self, row: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
        """把源侧 row 按 field_mapping（或保守默认）重命名为目标侧 key.

        始终被调用 —— 即使 field_mapping=None，也会走保守默认（源名 == 目标名）.

        Returns:
            (重命名后的 row dict, 目标侧缺失字段名列表).
        """
        src_cols = list(row.keys())
        # 默认：源名 == 目标名
        base = build_default_mapping(src_cols)
        if self._field_mapping:
            merged = apply_user_mapping(base, self._field_mapping, src_cols)
        else:
            merged = base

        # 重命名行 dict
        remapped = remap_row(row, merged)

        # 目标侧字段中，哪些在 merged.values() 里找不到
        mapped_dst = set(merged.values())
        unmapped_target = [name for name in self._field_map if name not in mapped_dst]
        return remapped, unmapped_target

    # ── 内部：字段集合校验 ────────────────────────

    def _check_field_set(self, row: dict[str, Any], result: ValidationResult) -> None:
        """检查未匹配列和缺失必填列."""
        if not self.skip_unknown_columns:
            unknown = set(row.keys()) - set(self._field_map.keys())
            for name in unknown:
                result.issues.append(Issue(field=name, level="warning", message="文件中有但表中无此字段，已忽略"))

        # 缺失必填列（仅当该必填字段在文件中完全不存在）
        present_keys = set(row.keys())
        for name in self._required_names:
            if name not in present_keys:
                result.issues.append(Issue(field=name, level="error", message="必填字段缺失"))

    # ── 内部：逐字段校验 ────────────────────────────

    def _check_each_field(self, row: dict[str, Any], result: ValidationResult) -> None:
        """对表中每个字段尝试做类型校验；异常记为 Issue."""
        for field_name, f in self._field_map.items():
            if f.trashed:  # 防御性检查，active_fields() 应已过滤
                continue
            raw = row.get(field_name)
            self._validate_one_field(f, raw, result)

    def _validate_one_field(self, f: DataField, raw: Any, result: ValidationResult) -> None:
        """对单个字段执行 validate_value；空值宽松处理；link 预解析."""
        # 1. 空值宽松处理
        if self._is_empty(raw):
            if f.required:
                result.issues.append(Issue(field=f.name, level="error", message="必填字段不能为空"))
            return

        try:
            # 2. link 字段：先把分号/逗号分隔串解析为 list[int]，再调 validate_value
            if is_link_field(f):
                parsed = self._parse_link_value(raw)
                normalized = default_registry.get("link").validate_value(parsed, f.config)  # type: ignore[union-attr]
                result.normalized[f.db_column_name] = normalized
                return

            # 3. 普通字段：直接调 validate_value
            ft = default_registry.get(f.field_type)
            if ft is None:
                result.issues.append(Issue(field=f.name, level="error", message=f"未知字段类型: {f.field_type}"))
                return
            normalized = ft.validate_value(raw, f.config)
            # validation 结果为 None 时不写入 normalized（与 _normalize_values 行为一致）
            if normalized is not None:
                result.normalized[f.db_column_name] = normalized
        except (ValueError, TypeError) as exc:
            result.issues.append(Issue(field=f.name, level="error", message=str(exc)))

    # ── 内部：状态归并 ────────────────────────────

    @staticmethod
    def _finalize_status(result: ValidationResult) -> None:
        """根据 issues 列表归并该行状态."""
        if result.has_error():
            result.status = "error"
        elif result.has_warning():
            result.status = "warning"
        else:
            result.status = "valid"

    # ── 内部：辅助 ─────────────────────────────────

    @staticmethod
    def _is_empty(value: Any) -> bool:
        """宽松空值判断：None / 空字符串 / 空 bytes 视为空."""
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        return bool(isinstance(value, (bytes, bytearray)) and not value.strip())

    @staticmethod
    def _parse_link_value(raw: Any) -> Any:
        """把 CSV/JSON 导入场景中的 link 值归一为 list[int].

        支持：
        - list[int]（已是结构化格式，如 JSON 导入）
        - 单值 int / str
        - 分号/逗号/空格分隔的字符串
        """
        if isinstance(raw, list):
            try:
                return [int(x) for x in raw]
            except (ValueError, TypeError) as exc:
                raise ValueError(f"link 字段解析失败: {raw!r}") from exc
        if isinstance(raw, int):
            return [raw]
        if isinstance(raw, str):
            text = raw.strip().replace(",", ";").replace(" ", "")
            if not text:
                return list[int]()
            try:
                return [int(part) for part in text.split(";")]
            except ValueError as exc:
                raise ValueError(f"link 字段值必须是分号分隔的行 id: {raw!r}") from exc
        raise ValueError(f"link 字段值类型不支持: {type(raw)!r}")


__all__ = ["Issue", "RowValidator", "ValidationResult"]
