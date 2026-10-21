"""files 插件服务：归属记录 + 下载/删除的权限校验.

校验口径（与"文件跟随其宿主"一致）：

==================  ==========================================================
归属                 校验
==================  ==========================================================
table_id (+row_id)  对表有 ``TableAction.READ``；若记录 row_id，还要该行在
                    行级过滤范围内（表所有者/超管按既有豁免规则）
document_id         文档对调用者可见（未发布 → 仅创建者/所有者）
无记录（历史文件）   仅工作区成员（保持既有能力，键不可猜）
==================  ==========================================================
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from cndb.core.errors import NotFoundError, PermissionDeniedError
from cndb.plugins.accounts.models import User
from cndb.plugins.files.models import FileOwner


def record_owner(
    db: Session,
    *,
    file_key: str,
    workspace_id: int,
    table_id: int | None = None,
    row_id: int | None = None,
    document_id: int | None = None,
    uploaded_by_id: int | None = None,
) -> FileOwner:
    """登记文件归属（幂等：同 key 覆盖）."""
    row = db.query(FileOwner).filter(FileOwner.file_key == file_key).first()
    if row is None:
        row = FileOwner(file_key=file_key, workspace_id=workspace_id)
        db.add(row)
    row.workspace_id = workspace_id
    row.table_id = table_id
    row.row_id = row_id
    row.document_id = document_id
    row.uploaded_by_id = uploaded_by_id
    db.commit()
    return row


def owner_of(db: Session, file_key: str) -> FileOwner | None:
    return db.query(FileOwner).filter(FileOwner.file_key == file_key).first()


def forget_owner(db: Session, file_key: str) -> None:
    row = owner_of(db, file_key)
    if row is not None:
        db.delete(row)
        db.commit()


def assert_can_access(db: Session, *, workspace_id: int, file_key: str, user: User) -> None:
    """按归属校验访问权；无归属记录时视为工作区级文件（调用方已校验成员身份）."""
    owner = owner_of(db, file_key)
    if owner is None or owner.workspace_id != workspace_id:
        return

    if owner.table_id is not None:
        from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404
        from cndb.plugins.tables.services.core.records import get_row

        table = get_table_or_404(owner.table_id, workspace_id, db, user=user, action=TableAction.READ)
        if owner.row_id is not None:
            # 行级过滤挡掉的行，其附件同样不可读（所有者/超管按 row_filters_bypass 豁免）
            row = get_row(db.get_bind(), table, owner.row_id, db=db, user=user)
            if row is None:
                raise NotFoundError("附件不存在或已被清理")
        return

    if owner.document_id is not None:
        from cndb.plugins.documents.services import visibility

        visibility.get_visible_document_or_404(db, workspace_id, owner.document_id, user)
        return

    # 仅有工作区归属：成员身份已由调用方校验
    return


def assert_can_attach_table(db: Session, *, table_id: int, workspace_id: int, user: User) -> Any:
    """上传到某张表时的前置校验（需要可写该表的数据）."""
    from cndb.plugins.tables.services.core.access import TableAction, get_table_or_404

    return get_table_or_404(table_id, workspace_id, db, user=user, action=TableAction.EDIT_RECORDS)


def assert_can_attach_document(db: Session, *, document_id: int, workspace_id: int, user: User) -> Any:
    """上传到某份文档时的前置校验（可见 + 可直接写内容）.

    已发布文档的查看者走"修改申请"流程（保存转 202），而上传附件没有对应的申请形态，
    因此这里要求"可直接写"：创建者 / 工作区编辑者+ / 所有者。
    未发布文档对普通成员不可见，可见性校验会先行 404。
    """
    from cndb.plugins.documents.services import visibility
    from cndb.plugins.workspaces.models import Workspace, WorkspaceRole
    from cndb.plugins.workspaces.permissions import has_role

    doc = visibility.get_visible_document_or_404(db, workspace_id, document_id, user)
    if doc.created_by_id == user.id:
        return doc
    if visibility.is_document_admin(db, workspace_id, user):
        return doc
    ws = db.get(Workspace, workspace_id)
    if ws is not None and has_role(user, ws, WorkspaceRole.EDITOR, db):
        return doc
    raise PermissionDeniedError("无权向该文档上传附件（只读或需走修改申请）")


__all__ = [
    "assert_can_access",
    "assert_can_attach_document",
    "assert_can_attach_table",
    "forget_owner",
    "owner_of",
    "record_owner",
]
