"""add_table_owner_and_member

Revision ID: 6955718a847b
Revises: b2c3d4e5f6a7
Create Date: 2026-09-14 13:55:25.555112

移除 workflows 三张表，新增 DataTable.owner_id 与 TableMember 表。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6955718a847b'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # 1. 删除 workflows 三张表（先删带 FK 的子表）
    op.drop_index(op.f('ix_workflows_workflowedge_source_node_id'), table_name='workflows_workflowedge')
    op.drop_index(op.f('ix_workflows_workflowedge_target_node_id'), table_name='workflows_workflowedge')
    op.drop_index(op.f('ix_workflows_workflowedge_workflow_id'), table_name='workflows_workflowedge')
    op.drop_table('workflows_workflowedge')

    op.drop_index(op.f('ix_workflows_workflownode_table_id'), table_name='workflows_workflownode')
    op.drop_index(op.f('ix_workflows_workflownode_workflow_id'), table_name='workflows_workflownode')
    op.drop_table('workflows_workflownode')

    op.drop_index(op.f('ix_workflows_workflow_workspace_id'), table_name='workflows_workflow')
    op.drop_table('workflows_workflow')

    # 2. DataTable 新增 owner_id 列
    # SQLite 不支持裸 ALTER 加约束，统一走 batch 模式（copy-and-move 重建表）
    with op.batch_alter_table('tables_datatable') as batch_op:
        batch_op.add_column(sa.Column('owner_id', sa.Integer(), nullable=True))
        batch_op.create_index(op.f('ix_tables_datatable_owner_id'), ['owner_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_tables_datatable_owner_id_accounts_user',
            'accounts_user',
            ['owner_id'],
            ['id'],
            ondelete='SET NULL',
        )

    # 3. 新建 TableMember 表
    op.create_table(
        'tables_tablemember',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
            comment='创建时间（UTC）',
        ),
        sa.Column(
            'updated_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
            comment='最后更新时间（UTC）',
        ),
        sa.Column('table_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(length=16), nullable=False, server_default='read'),
        sa.ForeignKeyConstraint(
            ['table_id'],
            ['tables_datatable.id'],
            name='fk_tables_tablemember_table_id_tables_datatable',
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['user_id'],
            ['accounts_user.id'],
            name='fk_tables_tablemember_user_id_accounts_user',
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('table_id', 'user_id', name='uniq_tablemember_user'),
    )
    op.create_index(op.f('ix_tables_tablemember_table_id'), 'tables_tablemember', ['table_id'], unique=False)
    op.create_index(op.f('ix_tables_tablemember_user_id'), 'tables_tablemember', ['user_id'], unique=False)

    # ── 4. 数据迁移：回填现有表的 owner_id ──
    # 将每张尚无 owner 的表的 owner 设为所属工作区的创建者
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "UPDATE tables_datatable "
            "SET owner_id = (SELECT w.created_by_id FROM workspaces_workspace w WHERE w.id = tables_datatable.workspace_id) "
            "WHERE owner_id IS NULL"
        )
    )


def downgrade() -> None:
    """Downgrade schema."""

    # 1. 删除 TableMember
    op.drop_index(op.f('ix_tables_tablemember_user_id'), table_name='tables_tablemember')
    op.drop_index(op.f('ix_tables_tablemember_table_id'), table_name='tables_tablemember')
    op.drop_table('tables_tablemember')

    # 2. 删除 DataTable.owner_id（SQLite 需 batch 模式）
    with op.batch_alter_table('tables_datatable') as batch_op:
        batch_op.drop_constraint('fk_tables_datatable_owner_id_accounts_user', type_='foreignkey')
        batch_op.drop_index(op.f('ix_tables_datatable_owner_id'))
        batch_op.drop_column('owner_id')

    # 3. 重建 workflows 表
    op.create_table(
        'workflows_workflow',
        sa.Column('workspace_id', sa.INTEGER(), nullable=False),
        sa.Column('name', sa.VARCHAR(length=255), nullable=False),
        sa.Column('description', sa.TEXT(), nullable=False),
        sa.Column('order', sa.INTEGER(), nullable=False),
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column(
            'created_at',
            sa.DATETIME(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DATETIME(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['workspace_id'],
            ['workspaces_workspace.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_workflows_workflow_workspace_id'),
        'workflows_workflow',
        ['workspace_id'],
        unique=False,
    )

    op.create_table(
        'workflows_workflownode',
        sa.Column('workflow_id', sa.INTEGER(), nullable=False),
        sa.Column('name', sa.VARCHAR(length=255), nullable=False),
        sa.Column('table_id', sa.INTEGER(), nullable=True),
        sa.Column('pos_x', sa.INTEGER(), nullable=False),
        sa.Column('pos_y', sa.INTEGER(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column(
            'created_at',
            sa.DATETIME(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DATETIME(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['table_id'],
            ['tables_datatable.id'],
            ondelete='SET NULL',
        ),
        sa.ForeignKeyConstraint(
            ['workflow_id'],
            ['workflows_workflow.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_workflows_workflownode_workflow_id'),
        'workflows_workflownode',
        ['workflow_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_workflows_workflownode_table_id'),
        'workflows_workflownode',
        ['table_id'],
        unique=False,
    )

    op.create_table(
        'workflows_workflowedge',
        sa.Column('workflow_id', sa.INTEGER(), nullable=False),
        sa.Column('source_node_id', sa.INTEGER(), nullable=False),
        sa.Column('target_node_id', sa.INTEGER(), nullable=False),
        sa.Column('label', sa.VARCHAR(length=255), nullable=False),
        sa.Column('id', sa.INTEGER(), nullable=False),
        sa.Column(
            'created_at',
            sa.DATETIME(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.Column(
            'updated_at',
            sa.DATETIME(),
            server_default=sa.text('(CURRENT_TIMESTAMP)'),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ['source_node_id'],
            ['workflows_workflownode.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['target_node_id'],
            ['workflows_workflownode.id'],
            ondelete='CASCADE',
        ),
        sa.ForeignKeyConstraint(
            ['workflow_id'],
            ['workflows_workflow.id'],
            ondelete='CASCADE',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'workflow_id', 'source_node_id', 'target_node_id', name='uniq_wf_edge'
        ),
    )
    op.create_index(
        op.f('ix_workflows_workflowedge_workflow_id'),
        'workflows_workflowedge',
        ['workflow_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_workflows_workflowedge_target_node_id'),
        'workflows_workflowedge',
        ['target_node_id'],
        unique=False,
    )
    op.create_index(
        op.f('ix_workflows_workflowedge_source_node_id'),
        'workflows_workflowedge',
        ['source_node_id'],
        unique=False,
    )
