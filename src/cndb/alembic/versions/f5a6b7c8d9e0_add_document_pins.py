"""add_document_pins — 文档个人置顶表.

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-10-15 16:00:00.000000

置顶为**个人偏好**（与 WorkspaceMember.pinned 一致）：每个用户维护自己的置顶集合，
(document_id, user_id) 唯一；随文档 / 用户级联删除。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f5a6b7c8d9e0'
down_revision: Union[str, Sequence[str], None] = 'e4f5a6b7c8d9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'documents_pin'
_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """创建文档置顶表."""
    if not _table_exists(_TABLE):
        op.create_table(
            _TABLE,
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('document_id', sa.Integer(), nullable=False, index=True),
            sa.Column('user_id', sa.Integer(), nullable=False, index=True),
            sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
            sa.ForeignKeyConstraint(['document_id'], ['documents_document.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['user_id'], ['accounts_user.id'], ondelete='CASCADE'),
            sa.UniqueConstraint('document_id', 'user_id', name='uq_documents_pin_doc_user'),
        )


def downgrade() -> None:
    """删除文档置顶表."""
    if _table_exists(_TABLE):
        op.drop_table(_TABLE)
