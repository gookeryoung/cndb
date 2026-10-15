"""add_file_owner — 上传文件的归属（表/行/文档）.

Revision ID: c3d4e5f6a7b8
Revises: b4d2e7a9c1f3
Create Date: 2026-10-16

新增 ``files_fileowner``：记录每个上传文件（``file_key``）的归属，
使下载/删除能按**归属对象**的权限校验，而不是仅凭"工作区成员 + 不可猜键"：

- 受限表（``read_role`` 高于普通成员）里的附件；
- 未发布文档里的图片；
- 被 ``row_filters`` 挡掉的行上的附件。

历史文件没有归属记录，保持既有行为（工作区级 + 键不可猜），不做回填。
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b4d2e7a9c1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "files_fileowner"
_TS_DEFAULT = sa.text("(CURRENT_TIMESTAMP)")


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建文件归属表（幂等）."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column("file_key", sa.String(length=255), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("table_id", sa.Integer(), nullable=True),
        sa.Column("row_id", sa.Integer(), nullable=True),
        sa.Column("document_id", sa.Integer(), nullable=True),
        sa.Column("uploaded_by_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces_workspace.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["table_id"], ["tables_datatable.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["documents_document.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("file_key", name="uq_files_fileowner_file_key"),
    )
    op.create_index("ix_files_fileowner_workspace_id", _TABLE, ["workspace_id"])
    op.create_index("ix_files_fileowner_table_id", _TABLE, ["table_id"])
    op.create_index("ix_files_fileowner_document_id", _TABLE, ["document_id"])


def downgrade() -> None:
    if not _table_exists(_TABLE):
        return
    for name in (
        "ix_files_fileowner_document_id",
        "ix_files_fileowner_table_id",
        "ix_files_fileowner_workspace_id",
    ):
        op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
