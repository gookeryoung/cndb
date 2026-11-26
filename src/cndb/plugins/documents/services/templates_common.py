"""文档模板公共契约层（ADR 0177 C4 / D5）.

两类模板（导出模板 `ExportTemplate` / 内容模板 `ContentTemplate`）语义与字段完全不同，
**不合并模型**；这里只收敛它们在 CRUD 面上重复的那几件事：

- 工作区内名称唯一（写入前检查 + 并发撞唯一约束兜底转 400）；
- 跨工作区 / 不存在的单条按 404；
- 列表 envelope 统一（`{items, total}`，导出模板额外带 `default_ref`）；
- 读门槛（工作区成员）。

业务校验（排版配置合法性 / Markdown 正文）留在各自服务里，不放到这里 ——
否则就要在公共层里写 `kind` 分支，等价于部分合并（D5 已否决）。

`model` 参数传 SQLAlchemy 模型类（`ExportTemplate` / `ContentTemplate`），本层只依赖
两者的共同列（`workspace_id` / `name` / `id`）。
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cndb.core.errors import BadRequestError, NotFoundError
from cndb.plugins.accounts.models import User

ModelT = TypeVar("ModelT")

DUPLICATE_NAME_MESSAGE = "同工作区已存在同名模板：{name}"


def ensure_name_free(
    db: Session,
    model: Any,
    workspace_id: int,
    name: str,
    *,
    exclude_id: int | None = None,
) -> None:
    """工作区内名称唯一（重名 400）."""
    stmt = select(model.id).where(model.name == name, model.workspace_id == workspace_id)
    if exclude_id is not None:
        stmt = stmt.where(model.id != exclude_id)
    if db.execute(stmt).first() is not None:
        raise BadRequestError(DUPLICATE_NAME_MESSAGE.format(name=name))


def commit_or_conflict(db: Session, name: str) -> None:
    """提交并把并发撞唯一约束转成 400（预检查之后的兜底）."""
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - 并发同名，唯一约束兜底
        db.rollback()
        raise BadRequestError(DUPLICATE_NAME_MESSAGE.format(name=name)) from exc


def get_or_404(
    db: Session,
    model: Any,
    workspace_id: int,
    obj_id: int,
    message: str = "模板不存在",
) -> Any:
    """按 id 取单条；跨工作区与不存在统一 404（不区分原因）."""
    row = db.get(model, obj_id)
    if row is None or row.workspace_id != workspace_id:
        raise NotFoundError(message)
    return row


def list_envelope(items: list[dict[str, Any]], *, default_ref: str | None = None) -> dict[str, Any]:
    """列表统一载荷：`{items, total}`；导出模板额外带 `default_ref`."""
    payload: dict[str, Any] = {"items": items, "total": len(items)}
    if default_ref is not None:
        payload["default_ref"] = default_ref
    return payload


def require_member(db: Session, workspace_id: int, user: User) -> None:
    """读门槛：工作区数据面成员（与文档读取同口径，H64）."""
    from cndb.plugins.workspaces.models import Workspace
    from cndb.plugins.workspaces.permissions import raise_permission_denied, workspace_data_role

    ws = db.get(Workspace, workspace_id)
    if ws is None:
        raise NotFoundError("工作区不存在")
    if workspace_data_role(user, ws, db) is None:
        raise_permission_denied(db, ws, user)


__all__ = [
    "DUPLICATE_NAME_MESSAGE",
    "commit_or_conflict",
    "ensure_name_free",
    "get_or_404",
    "list_envelope",
    "require_member",
]
