"""add form approval

Revision ID: c1d2e3f4a5b6
Revises: b8a7c6d5e4f3
Create Date: 2026-10-11 10:00:00.000000

表单绑定审批流 + 审批运行时两张表。

关键约束（沿用 f7a8b9c0d1e2 既有模式）：
- 防御式迁移：目标表不存在时跳过（由启动 create_all 按完整 ORM 元数据兜底）；
- 幂等：列/索引/表已存在时跳过，兼容 create_all 时代旧库；
- 链上加列不建 FK（既有先例，SQLite 不支持裸 ALTER 加约束）；
  FK 语义由 ORM 层维护，新库由 create_all 自带。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b8a7c6d5e4f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMN = 'approval_workflow_id'
_INDEX = 'ix_forms_formdefinition_approval_workflow_id'


def _table_exists(table: str) -> bool:
    """目标表是否存在（不存在则由启动 create_all 兜底，本迁移跳过）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _existing_columns(table: str) -> set[str]:
    """读取表当前已有的列名集合（表不存在时返回空集）."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return set()
    return {c['name'] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema."""
    # 1. 表单绑定审批流列（防御式 + 幂等；不建 FK，既有先例）
    if _table_exists('forms_formdefinition') and _COLUMN not in _existing_columns('forms_formdefinition'):
        op.add_column('forms_formdefinition', sa.Column(_COLUMN, sa.Integer(), nullable=True))
    if _table_exists('forms_formdefinition'):
        insp = sa.inspect(op.get_bind())
        idx_names = {i['name'] for i in insp.get_indexes('forms_formdefinition')}
        if _INDEX not in idx_names and _COLUMN in _existing_columns('forms_formdefinition'):
            op.create_index(op.f(_INDEX), 'forms_formdefinition', [_COLUMN], unique=False)

    # 2. 审批实例（提交值快照 + 当前节点推进状态）
    if not _table_exists('workflows_approvalinstance'):
        op.create_table(
            'workflows_approvalinstance',
            sa.Column('workspace_id', sa.Integer(), nullable=False),
            sa.Column('workflow_id', sa.Integer(), nullable=False),
            sa.Column('form_id', sa.Integer(), nullable=False),
            sa.Column('table_id', sa.Integer(), nullable=False),
            sa.Column('record_id', sa.Integer(), nullable=True),
            sa.Column('values', sa.JSON(), nullable=False),
            sa.Column('current_node_id', sa.Integer(), nullable=True),
            sa.Column('current_approver_role', sa.String(length=16), nullable=False),
            sa.Column('status', sa.String(length=16), nullable=False),
            sa.Column('submitted_by', sa.Integer(), nullable=True),
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='创建时间（UTC）'),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='最后更新时间（UTC）'),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['workflow_id'], ['workflows_workflow.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['form_id'], ['forms_formdefinition.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['table_id'], ['tables_datatable.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['current_node_id'], ['workflows_workflownode.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['submitted_by'], ['accounts_user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_workflows_approvalinstance_workspace_id'), 'workflows_approvalinstance', ['workspace_id'], unique=False)
        op.create_index(op.f('ix_workflows_approvalinstance_workflow_id'), 'workflows_approvalinstance', ['workflow_id'], unique=False)
        op.create_index(op.f('ix_workflows_approvalinstance_form_id'), 'workflows_approvalinstance', ['form_id'], unique=False)
        op.create_index(op.f('ix_workflows_approvalinstance_table_id'), 'workflows_approvalinstance', ['table_id'], unique=False)
        op.create_index(op.f('ix_workflows_approvalinstance_status'), 'workflows_approvalinstance', ['status'], unique=False)
        op.create_index(op.f('ix_workflows_approvalinstance_submitted_by'), 'workflows_approvalinstance', ['submitted_by'], unique=False)

    # 3. 审批动作流水（成功推进/驳回各一条）
    if not _table_exists('workflows_approvalaction'):
        op.create_table(
            'workflows_approvalaction',
            sa.Column('instance_id', sa.Integer(), nullable=False),
            sa.Column('node_id', sa.Integer(), nullable=True),
            sa.Column('action', sa.String(length=16), nullable=False),
            sa.Column('comment', sa.Text(), nullable=False),
            sa.Column('acted_by', sa.Integer(), nullable=True),
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='创建时间（UTC）'),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='最后更新时间（UTC）'),
            sa.ForeignKeyConstraint(['instance_id'], ['workflows_approvalinstance.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['node_id'], ['workflows_workflownode.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['acted_by'], ['accounts_user.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index(op.f('ix_workflows_approvalaction_instance_id'), 'workflows_approvalaction', ['instance_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    if _table_exists('workflows_approvalaction'):
        op.drop_index(op.f('ix_workflows_approvalaction_instance_id'), table_name='workflows_approvalaction')
        op.drop_table('workflows_approvalaction')
    if _table_exists('workflows_approvalinstance'):
        op.drop_index(op.f('ix_workflows_approvalinstance_submitted_by'), table_name='workflows_approvalinstance')
        op.drop_index(op.f('ix_workflows_approvalinstance_status'), table_name='workflows_approvalinstance')
        op.drop_index(op.f('ix_workflows_approvalinstance_table_id'), table_name='workflows_approvalinstance')
        op.drop_index(op.f('ix_workflows_approvalinstance_form_id'), table_name='workflows_approvalinstance')
        op.drop_index(op.f('ix_workflows_approvalinstance_workflow_id'), table_name='workflows_approvalinstance')
        op.drop_index(op.f('ix_workflows_approvalinstance_workspace_id'), table_name='workflows_approvalinstance')
        op.drop_table('workflows_approvalinstance')
    if _table_exists('forms_formdefinition'):
        insp = sa.inspect(op.get_bind())
        idx_names = {i['name'] for i in insp.get_indexes('forms_formdefinition')}
        if _INDEX in idx_names:
            op.drop_index(op.f(_INDEX), table_name='forms_formdefinition')
        if _COLUMN in _existing_columns('forms_formdefinition'):
            op.drop_column('forms_formdefinition', _COLUMN)
