"""add_documents_plugin — 文档管理插件六张表 + FTS5 虚拟表.

新建：
- documents_document        文档主表（含文件夹层级/软删除/元数据）
- documents_documentversion 版本快照表
- documents_tag             标签表
- documents_documenttag     文档-标签关联表
- documents_permission      文档级权限覆盖表
- documents_share           分享链接表
- documents_fts             FTS5 全文检索虚拟表（documents FK 无 ORM 映射，
  检索同步由 services 层显式执行，不建触发器）

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-10-13 22:00:00.000000

"""

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'e9f0a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    """目标表是否存在（幂等：已存在时跳过，兼容 create_all 时代旧库）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _make_table(table: str, *args: Any, **kwargs: Any) -> None:
    """存在则跳过的建表包装（透传 op.create_table 参数）."""
    if not _table_exists(table):
        op.create_table(table, *args, **kwargs)


def upgrade() -> None:
    """创建 documents 插件全部表 + FTS5 虚拟表."""
    _make_table(
        'documents_document',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('workspace_id', sa.Integer(), nullable=False, index=True),
        sa.Column('parent_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(500), nullable=False, server_default=''),
        sa.Column('slug', sa.String(500), nullable=True),
        sa.Column('content_type', sa.String(32), nullable=False, server_default='markdown'),
        sa.Column('author', sa.String(200), nullable=False, server_default=''),
        sa.Column('summary', sa.Text(), nullable=False, server_default=''),
        sa.Column('toc_json', sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column('status', sa.String(20), nullable=False, server_default='draft'),
        sa.Column('is_folder', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.Column('content_path', sa.String(1024), nullable=True),
        sa.Column('content_size', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_id'], ['documents_document.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
    )
    # 复合索引（列级 index=True 生成的单列索引已由 create_table 自动创建）
    op.create_index(
        'ix_documents_document_ws_parent',
        'documents_document',
        ['workspace_id', 'parent_id', 'sort_order'],
    )

    _make_table(
        'documents_documentversion',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('document_id', sa.Integer(), nullable=False, index=True),
        sa.Column('version_number', sa.Integer(), nullable=False, server_default=sa.text('1')),
        sa.Column('content', sa.Text(), nullable=False, server_default=''),
        sa.Column('content_html', sa.Text(), nullable=True),
        sa.Column('content_size', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('content_hash', sa.String(64), nullable=True),
        sa.Column('change_summary', sa.String(500), nullable=False, server_default=''),
        sa.Column('change_type', sa.String(20), nullable=False, server_default='manual'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents_document.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('document_id', 'version_number', name='uq_docver_doc_num'),
    )

    _make_table(
        'documents_tag',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('workspace_id', sa.Integer(), nullable=False, index=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('color', sa.String(7), nullable=False, server_default="'#1890FF'"),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('doc_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('workspace_id', 'name', name='uq_documents_tag_ws_name'),
    )

    _make_table(
        'documents_documenttag',
        sa.Column('document_id', sa.Integer(), primary_key=True),
        sa.Column('tag_id', sa.Integer(), primary_key=True, index=True),
        sa.Column('tagged_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('tagged_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents_document.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tag_id'], ['documents_tag.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['tagged_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
    )

    _make_table(
        'documents_permission',
        sa.Column('document_id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.Integer(), primary_key=True, index=True),
        sa.Column('role', sa.String(20), nullable=False),
        sa.ForeignKeyConstraint(['document_id'], ['documents_document.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['accounts_user.id'], ondelete='CASCADE'),
    )

    _make_table(
        'documents_share',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('document_id', sa.Integer(), nullable=False, index=True),
        sa.Column('token', sa.String(64), nullable=False),
        sa.Column('permission', sa.String(20), nullable=False, server_default="'viewer'"),
        sa.Column('password_hash', sa.String(200), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('view_count', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('1')),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['document_id'], ['documents_document.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
    )
    # token 唯一索引（列定义未带 index=True，需手动建）
    op.create_index('ix_documents_share_token', 'documents_share', ['token'], unique=True)

    # FTS5 虚拟表（幂等；不存在时才建）
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5("
        "title, content, summary, author, tokenize='unicode61')"
    )


def downgrade() -> None:
    """回滚：drop FTS 虚拟表 + 六张业务表（依赖倒序）."""
    op.execute('DROP TABLE IF EXISTS documents_fts')
    for table in (
        'documents_share',
        'documents_permission',
        'documents_documenttag',
        'documents_tag',
        'documents_documentversion',
        'documents_document',
    ):
        if _table_exists(table):
            op.drop_table(table)
