"""逐行校验器 —— 导入流水线的"守门员"阶段.

职责：对已解析成行 dict 的数据逐行逐字段校验，捕获 ValueError/TypeError，
收集成 Issue 列表；不抛异常，不让任何单行失败阻塞其他行的校验结果。

复用 :mod:`cndb.plugins.tables.field_types` 的 ``default_registry``，
每个字段类型的 ``validate_value`` 做实际的类型强转 + 业务规则校验；
RowValidator 只负责调度、空值宽松处理、link 值预解析、以及结果收集。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from cndb.plugins.tables.field_types import default_registry
from cndb.plugins.tables.links import is_link_field
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
    """

    def __init__(self, table: DataTable, *, skip_unknown_columns: bool = False) -> None:
        self.table = table
        self.skip_unknown_columns = skip_unknown_columns
        self._fields: list[DataField] = table.active_fields()
        self._field_map: dict[str, DataField] = {f.name: f for f in self._fields}
        self._required_names: set[str] = {f.name for f in self._fields if f.required}

    # ── 公共 API ──────────────────────────────────

    def validate_all(self, rows: list[dict[str, Any]]) -> list[ValidationResult]:
        """批量校验，返回与输入等长的结果列表."""
        return [self.validate_row(row, row_number) for row_number, row in enumerate(rows, start=1)]

    def validate_row(self, row: dict[str, Any], row_number: int) -> ValidationResult:
        """校验单行，返回 ValidationResult（永远不抛异常）."""
        result = ValidationResult(row_number=row_number, values=dict(row))
        self._check_field_set(row, result)
        self._check_each_field(row, result)
        self._finalize_status(result)
        return result

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
