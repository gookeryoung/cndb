"""add workflows tables

Revision ID: 62817ea574fa
Revises: 6399e5f0f61f
Create Date: 2026-09-12 08:30:03.445291

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '62817ea574fa'
down_revision: Union[str, Sequence[str], None] = '6399e5f0f61f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'workflows_workflow',
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('order', sa.Integer(), nullable=False),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='创建时间（UTC）'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='最后更新时间（UTC）'),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workflows_workflow_workspace_id'), 'workflows_workflow', ['workspace_id'], unique=False)

    op.create_table(
        'workflows_workflownode',
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('table_id', sa.Integer(), nullable=True),
        sa.Column('pos_x', sa.Integer(), nullable=False),
        sa.Column('pos_y', sa.Integer(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='创建时间（UTC）'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='最后更新时间（UTC）'),
        sa.ForeignKeyConstraint(['table_id'], ['tables_datatable.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflows_workflow.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_workflows_workflownode_table_id'), 'workflows_workflownode', ['table_id'], unique=False)
    op.create_index(op.f('ix_workflows_workflownode_workflow_id'), 'workflows_workflownode', ['workflow_id'], unique=False)

    op.create_table(
        'workflows_workflowedge',
        sa.Column('workflow_id', sa.Integer(), nullable=False),
        sa.Column('source_node_id', sa.Integer(), nullable=False),
        sa.Column('target_node_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=255), nullable=False),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='创建时间（UTC）'),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='最后更新时间（UTC）'),
        sa.ForeignKeyConstraint(['source_node_id'], ['workflows_workflownode.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_node_id'], ['workflows_workflownode.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflows_workflow.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_id', 'source_node_id', 'target_node_id', name='uniq_wf_edge'),
    )
    op.create_index(op.f('ix_workflows_workflowedge_source_node_id'), 'workflows_workflowedge', ['source_node_id'], unique=False)
    op.create_index(op.f('ix_workflows_workflowedge_target_node_id'), 'workflows_workflowedge', ['target_node_id'], unique=False)
    op.create_index(op.f('ix_workflows_workflowedge_workflow_id'), 'workflows_workflowedge', ['workflow_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_workflows_workflowedge_workflow_id'), table_name='workflows_workflowedge')
    op.drop_index(op.f('ix_workflows_workflowedge_target_node_id'), table_name='workflows_workflowedge')
    op.drop_index(op.f('ix_workflows_workflowedge_source_node_id'), table_name='workflows_workflowedge')
    op.drop_table('workflows_workflowedge')
    op.drop_index(op.f('ix_workflows_workflownode_workflow_id'), table_name='workflows_workflownode')
    op.drop_index(op.f('ix_workflows_workflownode_table_id'), table_name='workflows_workflownode')
    op.drop_table('workflows_workflownode')
    op.drop_index(op.f('ix_workflows_workflow_workspace_id'), table_name='workflows_workflow')
    op.drop_table('workflows_workflow')
