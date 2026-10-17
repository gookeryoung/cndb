"""add_analytics_plugin — 数据分析插件模板表.

新建：
- analytics_template  分析模板主表（工作区级，存公式清单 + 可视化配置 JSON）

Revision ID: a7c1e3b5d9f2
Revises: b5c6d7e8f9a0
Create Date: 2026-10-17 10:00:00.000000

"""

from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a7c1e3b5d9f2'
down_revision: Union[str, Sequence[str], None] = 'b5c6d7e8f9a0'
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
    """创建 analytics_template 表."""
    _make_table(
        'analytics_template',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('workspace_id', sa.Integer(), nullable=False, index=True),
        sa.Column('table_id', sa.Integer(), nullable=True, index=True),
        sa.Column('name', sa.String(200), nullable=False),
        sa.Column('description', sa.Text(), nullable=False, server_default=''),
        sa.Column('config', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=_TS_DEFAULT),
        sa.Column('created_by_id', sa.Integer(), nullable=True, index=True),
        sa.Column('updated_by_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['table_id'], ['tables_datatable.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['updated_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
    )
    op.create_index(
        'ix_analytics_template_ws_updated',
        'analytics_template',
        ['workspace_id', 'updated_at'],
    )


def downgrade() -> None:
    """回滚：删除 analytics_template 表."""
    if _table_exists('analytics_template'):
        op.drop_table('analytics_template')
