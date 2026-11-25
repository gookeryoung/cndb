"""导出模板读写服务（ADR 0152）.

职责边界：
- **唯一解析入口**在 ``services/export/templates.resolve_export_template``；
- 这里只做「工作区级 CRUD + 默认唯一 + 序列化」，不参与渲染；
- 内置预设想改只能「另存为」——对 ``builtin:<key>`` 的写操作一律 400。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, NotFoundError
from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import ExportTemplate
from cndb.plugins.documents.services.export import templates as template_cfg

BUILTIN_SOURCE = "builtin"
CUSTOM_SOURCE = "custom"


def _builtin_items() -> list[dict[str, Any]]:
    return [
        {
            "ref": template.ref,
            "name": template.name,
            "description": template.description,
            "source": BUILTIN_SOURCE,
            "is_default": False,
            "config": template_cfg.config_to_dict(template.config),
            "updated_at": None,
        }
        for template in template_cfg.BUILTIN_TEMPLATES.values()
    ]


def _row_item(row: ExportTemplate) -> dict[str, Any]:
    return {
        "ref": str(row.id),
        "name": row.name,
        "description": row.description or "",
        "source": CUSTOM_SOURCE,
        "is_default": bool(row.is_default),
        "config": row.config or {},
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def default_ref(db: Session, workspace_id: int) -> str:
    """当前工作区实际生效的默认模板引用（未设默认即内置 standard）."""
    row = _default_row(db, workspace_id)
    return str(row.id) if row is not None else template_cfg.DEFAULT_TEMPLATE_REF


def _default_row(db: Session, workspace_id: int) -> ExportTemplate | None:
    return (
        db.execute(
            select(ExportTemplate)
            .where(ExportTemplate.workspace_id == workspace_id, ExportTemplate.is_default.is_(True))
            .order_by(ExportTemplate.id)
        )
        .scalars()
        .first()
    )


def list_templates(db: Session, workspace_id: int) -> dict[str, Any]:
    """内置预设（只读）+ 工作区自定义模板，附当前默认引用."""
    rows = (
        db.execute(
            select(ExportTemplate)
            .where(ExportTemplate.workspace_id == workspace_id)
            .order_by(ExportTemplate.is_default.desc(), ExportTemplate.id)
        )
        .scalars()
        .all()
    )
    items = _builtin_items()
    items.extend(_row_item(row) for row in rows)
    return {"items": items, "default_ref": default_ref(db, workspace_id)}


def get_template(db: Session, workspace_id: int, ref: str) -> dict[str, Any]:
    """按引用取单个模板：内置 key 或本工作区行 id；跨工作区一律 404."""
    try:
        normalized = template_cfg.normalize_ref(ref)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    if normalized is None:
        raise NotFoundError("模板不存在")
    builtin = template_cfg.resolve_builtin(normalized)
    if builtin is not None:
        return {
            "ref": builtin.ref,
            "name": builtin.name,
            "description": builtin.name,
            "source": BUILTIN_SOURCE,
            "is_default": False,
            "config": template_cfg.config_to_dict(builtin.config),
            "updated_at": None,
        }
    if normalized.startswith("builtin:"):
        raise NotFoundError("模板不存在")
    row = _get_row(db, workspace_id, int(normalized))
    return _row_item(row)


def _get_row(db: Session, workspace_id: int, template_id: int) -> ExportTemplate:
    row = db.get(ExportTemplate, template_id)
    if row is None or row.workspace_id != workspace_id:
        raise NotFoundError("模板不存在")
    return row


def _ensure_name_free(db: Session, workspace_id: int, name: str, *, exclude_id: int | None = None) -> None:
    exist = (
        db.execute(
            select(ExportTemplate).where(ExportTemplate.workspace_id == workspace_id, ExportTemplate.name == name)
        )
        .scalars()
        .first()
    )
    if exist is not None and exist.id != exclude_id:
        raise BadRequestError(f"同工作区已存在同名模板：{name}")


def _set_default(db: Session, workspace_id: int, row: ExportTemplate) -> None:
    """默认唯一：先清同工作区其它默认，再置本条（同一事务内）."""
    others = (
        db.execute(
            select(ExportTemplate).where(
                ExportTemplate.workspace_id == workspace_id,
                ExportTemplate.is_default.is_(True),
                ExportTemplate.id != row.id,
            )
        )
        .scalars()
        .all()
    )
    for other in others:
        other.is_default = False
    row.is_default = True


def create_template(
    db: Session,
    workspace_id: int,
    user: User,
    *,
    name: str,
    description: str = "",
    preset_key: str | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从内置预设另存为，或直接用提交的 config 新建."""
    clean_name = (name or "").strip()
    if not clean_name:
        raise BadRequestError("模板名称不能为空")
    _ensure_name_free(db, workspace_id, clean_name)

    if config is not None:
        resolved_config = _validated(config)
    elif preset_key:
        builtin = template_cfg.BUILTIN_TEMPLATES.get(preset_key.strip())
        if builtin is None:
            raise BadRequestError(f"未知的内置模板: {preset_key}")
        resolved_config = builtin.config
    else:
        resolved_config = template_cfg.BUILTIN_TEMPLATES[template_cfg.DEFAULT_TEMPLATE_KEY].config

    row = ExportTemplate(
        workspace_id=workspace_id,
        name=clean_name,
        description=(description or "").strip(),
        config=template_cfg.config_to_dict(resolved_config),
        is_default=False,
        created_by_id=user.id,
    )
    db.add(row)
    _commit(db, clean_name)
    db.refresh(row)
    return _row_item(row)


def update_template(
    db: Session,
    workspace_id: int,
    template_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    config: dict[str, Any] | None = None,
    is_default: bool | None = None,
) -> dict[str, Any]:
    row = _get_row(db, workspace_id, template_id)
    if name is not None:
        clean_name = name.strip()
        if not clean_name:
            raise BadRequestError("模板名称不能为空")
        _ensure_name_free(db, workspace_id, clean_name, exclude_id=row.id)
        row.name = clean_name
    if description is not None:
        row.description = description.strip()
    if config is not None:
        row.config = template_cfg.config_to_dict(_validated(config))
    if is_default is True:
        _set_default(db, workspace_id, row)
    elif is_default is False:
        row.is_default = False
    _commit(db, row.name)
    db.refresh(row)
    return _row_item(row)


def delete_template(db: Session, workspace_id: int, template_id: int) -> dict[str, Any]:
    """删除自定义模板；默认模板被删后回落内置 standard（不报错）."""
    row = _get_row(db, workspace_id, template_id)
    was_default = bool(row.is_default)
    db.delete(row)
    db.commit()
    return {"deleted": True, "default_ref": default_ref(db, workspace_id), "was_default": was_default}


def _validated(config: dict[str, Any]) -> template_cfg.ExportTemplateConfig:
    try:
        return template_cfg.validate_config(config)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc


def _commit(db: Session, name: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - 并发同名，唯一约束兜底
        db.rollback()
        raise BadRequestError(f"同工作区已存在同名模板：{name}") from exc


def render_preview(
    db: Session,
    workspace_id: int,
    *,
    fmt: str,
    config: dict[str, Any] | None = None,
    ref: str | None = None,
) -> bytes:
    """按给定配置（未保存）或已存在的模板 ref 渲染示例件，不落库."""
    if fmt not in ("docx", "pdf"):
        raise BadRequestError("示例预览只支持 docx / pdf")
    if config is not None:
        resolved = template_cfg.ResolvedTemplate(
            ref="preview", name="示例预览", source=CUSTOM_SOURCE, config=_validated(config)
        )
    else:
        resolved = template_cfg.resolve_export_template(db, workspace_id, ref)
    return template_cfg.render_sample(fmt, resolved.config)


__all__ = [
    "create_template",
    "default_ref",
    "delete_template",
    "get_template",
    "list_templates",
    "render_preview",
    "update_template",
]
