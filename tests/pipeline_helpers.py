"""pipeline 插件测试共用工厂（非 ``test_`` 前缀，不被 pytest 收集）."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from cndb.plugins.accounts.models import User
from cndb.plugins.documents.models import (
    CONTENT_TYPE_MARKDOWN,
    DOC_STATUS_DRAFT,
    Document,
    DocumentVersion,
)
from cndb.plugins.tables.models import DataField, DataTable
from cndb.plugins.tables.services.core import ddl
from cndb.plugins.tables.services.core.records import bulk_create
from cndb.plugins.workspaces.models import Workspace, WorkspaceMember, WorkspaceRole


def make_user(db: Session, username: str, *, password: str = "passw0rd") -> User:
    """建一个可直接登录的用户."""
    user = User(username=username, nickname=username)
    user.set_password(password)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def make_workspace(db: Session, owner: User, name: str) -> Workspace:
    """建工作区并把 ``owner`` 登记为 OWNER."""
    workspace = Workspace(name=name, created_by_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role=WorkspaceRole.OWNER))
    db.commit()
    db.refresh(workspace)
    return workspace


def add_member(db: Session, workspace: Workspace, user: User, role: WorkspaceRole) -> None:
    """追加工作区成员."""
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role))
    db.commit()


def login(client: TestClient, user: User, *, password: str = "passw0rd") -> dict[str, str]:
    """登录并返回 Authorization 头."""
    resp = client.post("/api/v1/accounts/auth/login", json={"login": user.username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def make_table(db: Session, workspace: Workspace, name: str, fields: list[tuple[str, str]]) -> DataTable:
    """建数据表元数据 + 物理表（字段顺序即展示顺序）."""
    table = DataTable(workspace_id=workspace.id, name=name)
    table.ensure_db_name()
    db.add(table)
    db.flush()
    for order, (field_name, field_type) in enumerate(fields):
        field = DataField(table_id=table.id, name=field_name, field_type=field_type, order=order)
        field.ensure_db_name()
        db.add(field)
    db.commit()
    db.refresh(table)
    ddl.create_table(db.get_bind(), table)
    return table


def add_rows(db: Session, table: DataTable, rows: list[dict[str, Any]]) -> list[int]:
    """写入物理行."""
    return bulk_create(db.get_bind(), table, rows, db=db)


def make_document(
    db: Session,
    workspace: Workspace,
    title: str,
    content: str,
    *,
    user: User | None = None,
    status: str = DOC_STATUS_DRAFT,
    is_folder: bool = False,
) -> Document:
    """建文档 + 最新版本（正文内联存储）."""
    size = len(content.encode("utf-8"))
    doc = Document(
        workspace_id=workspace.id,
        title=title,
        content_type=CONTENT_TYPE_MARKDOWN,
        status=status,
        is_folder=is_folder,
        created_by_id=user.id if user is not None else None,
        content_size=size,
    )
    db.add(doc)
    db.flush()
    db.add(
        DocumentVersion(
            document_id=doc.id,
            version_number=1,
            content=content,
            content_size=size,
            created_by_id=user.id if user is not None else None,
        )
    )
    db.commit()
    db.refresh(doc)
    return doc
