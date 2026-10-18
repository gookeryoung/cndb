"""add_document_drafts — 文档个人工作草稿表（保存与提交解耦）.

Revision ID: b8c9d0e1f2a3
Revises: a7c1e3b5d9f2
Create Date: 2026-10-18 09:00:00.000000

此前「保存」会直接生成文档版本（或修改申请），误操作成本高。本迁移新增
``documents_draft``：保存只写个人草稿，显式提交时才落库为版本 / 修改申请。
每位用户对每篇文档至多一份，随文档或用户级联删除。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7c1e3b5d9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'documents_draft'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过，兼容 create_all 时代旧库）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建 documents_draft 表与唯一约束/索引."""
    if _table_exists(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('document_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('content_size', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('content_hash', sa.String(64), nullable=False, server_default=''),
        sa.Column('base_version_number', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.ForeignKeyConstraint(['document_id'], ['documents_document.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['accounts_user.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('document_id', 'user_id', name='uq_documents_draft_doc_user'),
    )
    # 与 ORM 的 index=True 对齐：按文档查草稿 / 按用户清理
    op.create_index(f'ix_{_TABLE}_document_id', _TABLE, ['document_id'])
    op.create_index(f'ix_{_TABLE}_user_id', _TABLE, ['user_id'])


def downgrade() -> None:
    """删除文档草稿表."""
    if not _table_exists(_TABLE):
        return
    op.drop_table(_TABLE)
