"""add_document_issues — 文档问题清单表（文档级 Issue + 评论 + 状态事件）.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-10-15 08:30:00.000000

文档二级导航的「问题清单」入口需要文档级问题载体：与数据表问题清单同构
（类别 / 状态取值一致），但挂在 document_id 上并随文档级联删除。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ISSUE = 'documents_issue'
_COMMENT = 'documents_issuecomment'
_EVENT = 'documents_issueevent'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过，兼容 create_all 时代旧库）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建文档问题清单三张表."""
    if not _table_exists(_ISSUE):
        op.create_table(
            _ISSUE,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('workspace_id', sa.Integer(), nullable=False, index=True),
            sa.Column('document_id', sa.Integer(), nullable=False, index=True),
            sa.Column('title', sa.String(255), nullable=False),
            sa.Column('description', sa.Text(), nullable=False, server_default=''),
            sa.Column('category', sa.String(32), nullable=False, server_default='other'),
            sa.Column('status', sa.String(16), nullable=False, server_default='open', index=True),
            sa.Column('created_by_id', sa.Integer(), nullable=True, index=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['document_id'], ['documents_document.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        )
        op.create_index('ix_documents_issue_ws_status', _ISSUE, ['workspace_id', 'status'])

    if not _table_exists(_COMMENT):
        op.create_table(
            _COMMENT,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('issue_id', sa.Integer(), nullable=False, index=True),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('created_by_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.ForeignKeyConstraint(['issue_id'], ['documents_issue.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        )

    if not _table_exists(_EVENT):
        op.create_table(
            _EVENT,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('issue_id', sa.Integer(), nullable=False, index=True),
            sa.Column('action', sa.String(16), nullable=False),
            sa.Column('actor_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(['issue_id'], ['documents_issue.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['actor_id'], ['accounts_user.id'], ondelete='SET NULL'),
        )


def downgrade() -> None:
    """删除文档问题清单三张表（先删子表）."""
    for table in (_EVENT, _COMMENT, _ISSUE):
        if _table_exists(table):
            op.drop_table(table)
