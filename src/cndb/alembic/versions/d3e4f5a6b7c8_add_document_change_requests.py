"""add_document_change_requests — 文档修改申请表（双轨制写入载体）.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-10-15 08:05:00.000000

viewer（或关闭直编的 editor）保存文档时不再直接落库，而是生成一条待审修改申请，
通过后才写入 document_versions；本迁移创建该申请表与其索引。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = 'c2d3e4f5a6b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'documents_changerequest'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过，兼容 create_all 时代旧库）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建 documents_changerequest 表与索引."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('document_id', sa.Integer(), nullable=False, index=True),
        sa.Column('workspace_id', sa.Integer(), nullable=False, index=True),
        sa.Column('title', sa.String(255), nullable=False, server_default=''),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('proposed_content', sa.Text(), nullable=False, server_default=''),
        sa.Column('proposed_size', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('change_summary', sa.String(500), nullable=False, server_default=''),
        sa.Column('base_version_number', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('status', sa.String(16), nullable=False, server_default='open', index=True),
        sa.Column('stale', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('submitted_by_id', sa.Integer(), nullable=True, index=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_comment', sa.Text(), nullable=False, server_default=''),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.ForeignKeyConstraint(['document_id'], ['documents_document.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submitted_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
    )
    # 同一文档的待审申请检索（列表按状态过滤）走复合索引
    op.create_index('ix_documents_changerequest_doc_status', _TABLE, ['document_id', 'status'])


def downgrade() -> None:
    """删除文档修改申请表."""
    if not _table_exists(_TABLE):
        return
    op.drop_table(_TABLE)
