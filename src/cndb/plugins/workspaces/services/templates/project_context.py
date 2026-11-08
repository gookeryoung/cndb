"""项目上下文辅助（ADR 0122）.

只提供无 engine 依赖的底层能力：模板 ``project`` 配置解析、表单作用域、
项目行校验、按 link 关联统计项目行数、项目文档标题渲染。生命周期判定与
清单 / 启用等编排逻辑仍在 ``engine`` 内，避免循环依赖。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from cndb.plugins.tables.models import DataField, DataTable


class ProjectContextError(LookupError):
    """项目上下文非法（路由层统一转 404，不泄露跨工作区存在性）."""


def project_config(spec: dict[str, Any] | None) -> dict[str, Any] | None:
    """读取模板顶层 ``project`` 块；旧模板返回 None."""
    if not isinstance(spec, dict):
        return None
    project = spec.get("project")
    return project if isinstance(project, dict) else None


def form_scope(spec: dict[str, Any] | None, form_key: str) -> str:
    """表单作用域：无 project 块时全部按工作区级处理（存量兼容）."""
    project = project_config(spec)
    if project is None:
        return "workspace"
    if form_key == project.get("root_form"):
        return "project"
    for form in (spec or {}).get("forms", []):
        if form.get("key") == form_key:
            return form.get("scope") or "workspace"
    return "workspace"


def link_field_for(project: dict[str, Any] | None, form_key: str) -> str:
    """取表单的关联字段名：支持单值 ``link_field`` 与按表单映射 ``link_fields``."""
    if not project:
        return ""
    mapping = project.get("link_fields") or {}
    return str(mapping.get(form_key) or project.get("link_field") or "")


def root_form_key(spec: dict[str, Any] | None) -> str | None:
    project = project_config(spec)
    return project.get("root_form") if project else None


def root_table(db: Session, ws: Any, spec: dict[str, Any] | None) -> DataTable | None:
    """根表单对应的物理表；未实例化时返回 None."""
    key = root_form_key(spec)
    if key is None:
        return None
    mapping = (ws.template_state or {}).get("form_tables") or {}
    table_id = mapping.get(key)
    if not isinstance(table_id, int):
        return None
    table = db.get(DataTable, table_id)
    if table is None or table.workspace_id != ws.id or table.trashed_at is not None:
        return None
    return table


def link_field(table: DataTable, field_name: str) -> DataField | None:
    return next(
        (f for f in table.active_fields() if f.name == field_name and f.field_type == "link"),
        None,
    )


def resolve_project_row(
    db: Session,
    ws: Any,
    spec: dict[str, Any] | None,
    project_row_id: int | None,
) -> int:
    """校验项目行属于当前工作区根表单；非法一律抛 ``ProjectContextError``."""
    if not isinstance(project_row_id, int) or project_row_id <= 0:
        raise ProjectContextError("缺少有效的项目 ID")
    table = root_table(db, ws, spec)
    if table is None:
        raise ProjectContextError("工作区尚未实例化模板根表单")
    from cndb.plugins.tables.services.core.records import get_row

    row = get_row(db.get_bind(), table, project_row_id, db)
    if row is None:
        raise ProjectContextError("项目不存在")
    return project_row_id


def project_title(db: Session, ws: Any, spec: dict[str, Any], project_row_id: int) -> str:
    """项目标题：优先 ``title_field``，回退到首个非空文本值，最后 ``#row``."""
    project = project_config(spec) or {}
    title_field = project.get("title_field")
    table = root_table(db, ws, spec)
    if table is None:
        return f"#{project_row_id}"
    from cndb.plugins.tables.services.core.records import get_row

    row = get_row(db.get_bind(), table, project_row_id, db)
    if row is None:
        return f"#{project_row_id}"
    if title_field and row.get(title_field) not in (None, ""):
        return str(row[title_field])
    for field in table.active_fields():
        value = row.get(field.name)
        if value not in (None, "", []):
            return str(value)
    return f"#{project_row_id}"


def count_project_rows(db: Session, table: DataTable, field_name: str, project_row_id: int) -> int:
    """统计 ``table`` 中关联到该项目且未软删的行数（项目门禁唯一计数口径）."""
    field = link_field(table, field_name)
    if field is None:
        return 0
    sql = text(
        f'SELECT COUNT(DISTINCT link.row_id) FROM "{field.link_table_name}" AS link '
        f'JOIN "{table.db_table_name}" AS src ON src.id = link.row_id '
        f"WHERE link.target_row_id = :pid AND src._trashed = :not_trashed"
    )
    try:
        return int(db.execute(sql, {"pid": project_row_id, "not_trashed": False}).scalar() or 0)
    except Exception:  # pragma: no cover - 物理表 / 关联表缺失时按 0 处理
        return 0


def render_doc_title(rule: dict[str, Any], title_value: str, fallback: str) -> str:
    """项目文档标题：替换 ``naming`` 中的 ``{字段名}`` 占位.

    ``naming`` 只声明占位符模板（如 ``{项目名称}-立项报告``），单项目实例化时
    用项目标题值替换；无占位时回退 ``项目名称-规则标题``。
    """
    naming = str(rule.get("naming") or "").strip()
    if naming:
        return naming.replace("{项目名称}", title_value).replace("{项目}", title_value)
    return f"{title_value}-{fallback}"


__all__ = [
    "ProjectContextError",
    "count_project_rows",
    "form_scope",
    "link_field",
    "link_field_for",
    "project_config",
    "project_title",
    "render_doc_title",
    "resolve_project_row",
    "root_form_key",
    "root_table",
]
