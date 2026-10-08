"""add_governance — MANAGE_DATA 权限字段与 GovernanceTask 表.

Revision ID: a7b8c9d0e1f2
Revises: e5f6a7b8c9d0
Create Date: 2026-10-08 11:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a7b8c9d0e1f2'
down_revision: str | Sequence[str] | None = 'e5f6a7b8c9d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """新增数据治理权限阈值列与治理任务表.

    tables_tablepermission 加 manage_data_role（空 = 未配置，回退工作区默认 ADMIN）；
    新建 tables_governancetask 承载检测/合并/清洗异步任务的状态、进度与报告.
    """
    op.add_column(
        'tables_tablepermission',
        sa.Column(
            'manage_data_role',
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    op.create_table(
        'tables_governancetask',
        sa.Column('table_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False, server_default=sa.text("'detect'")),
        sa.Column('status', sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column('progress', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('config', sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column('report', sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column('error_message', sa.Text(), nullable=False, server_default=sa.text("''")),
        sa.Column('total_groups', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('done_groups', sa.Integer(), nullable=False, server_default=sa.text('0')),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['table_id'], ['tables_datatable.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tables_governancetask_table_id'), 'tables_governancetask', ['table_id'])
    op.create_index(op.f('ix_tables_governancetask_user_id'), 'tables_governancetask', ['user_id'])
    op.create_index(op.f('ix_tables_governancetask_status'), 'tables_governancetask', ['status'])


def downgrade() -> None:
    """降级：删除治理任务表与 manage_data_role 列."""
    op.drop_index(op.f('ix_tables_governancetask_status'), table_name='tables_governancetask')
    op.drop_index(op.f('ix_tables_governancetask_user_id'), table_name='tables_governancetask')
    op.drop_index(op.f('ix_tables_governancetask_table_id'), table_name='tables_governancetask')
    op.drop_table('tables_governancetask')
    op.drop_column('tables_tablepermission', 'manage_data_role')
