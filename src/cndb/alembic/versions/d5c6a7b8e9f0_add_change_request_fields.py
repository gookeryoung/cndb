"""add change request fields

表级「编辑需审批」：ApprovalInstance 扩展为双载荷（表单提交 / 网格变更单），
DataTable 新增 edit_approval_workflow_id 开关列。

关键约束（沿用 f7a8b9c0d1e2 / c1d2e3f4a5b6 既有模式）：
- 防御式：目标表不存在时跳过（由启动 create_all 按完整 ORM 元数据兜底）；
- 幂等：列/索引已存在时跳过，兼容 create_all 时代旧库；
- 链上加列不建 FK（既有先例，SQLite 不支持裸 ALTER 加约束），
  FK 语义由 ORM 层维护，新库由 create_all 自带；
- form_id 放开可空必须重建表（SQLite 无 ALTER COLUMN），走 batch 模式；
  迁移链历史上 workflows 三表曾被 6955718a847b 移除，c1d2e3f4a5b6 重建
  approvalinstance 时其 FK 目标 workflows_workflow 在纯迁移链库中不存在
  （幽灵 FK，SQLite 不校验建表），因此 batch 不能用反射模式，改用
  copy_from 显式表定义（列/索引/FK 与 c1d2e3f4a5b6 建表定义逐列对齐）。

Revision ID: d5c6a7b8e9f0
Revises: c1d2e3f4a5b6
Create Date: 2026-10-12 09:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5c6a7b8e9f0'
down_revision: Union[str, Sequence[str], None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INSTANCE = 'workflows_approvalinstance'
_DT = 'tables_datatable'
_OP_COL = 'op'
_ROW_ID_COL = 'row_id'
_ROW_ID_IX = 'ix_workflows_approvalinstance_row_id'
_SWITCH_COL = 'edit_approval_workflow_id'

# c1d2e3f4a5b6 建表时的既有索引（batch 重建后须原样恢复）
_INSTANCE_IX_COLS = (
    'workspace_id', 'workflow_id', 'form_id', 'table_id', 'status', 'submitted_by',
)


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


def _column_nullable(table: str, column: str) -> bool | None:
    """读取列当前 nullable 状态（表/列不存在时返回 None）."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return None
    for c in insp.get_columns(table):
        if c['name'] == column:
            return bool(c['nullable'])
    return None


def _instance_copy_from(include_change_fields: bool) -> sa.Table:
    """approvalinstance 显式表定义（batch copy_from，绕开反射解析幽灵 FK）.

    列/约束与 c1d2e3f4a5b6 建表定义逐列对齐；include_change_fields
    控制是否带 op / row_id（upgrade 起点不含 / downgrade 起点含）。

    Args:
        include_change_fields: True 时包含 op/row_id 列与 row_id 索引。
    """
    m = sa.MetaData()
    cols = [
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
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
        sa.Column(
            'created_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='创建时间（UTC）',
        ),
        sa.Column(
            'updated_at', sa.DateTime(timezone=True),
            server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False, comment='最后更新（UTC）',
        ),
    ]
    if include_change_fields:
        cols[3] = sa.Column('form_id', sa.Integer(), nullable=True)
        cols.insert(5, sa.Column('op', sa.String(length=16), nullable=True))
        cols.insert(6, sa.Column('row_id', sa.Integer(), nullable=True))
    indexes = [sa.Index(f'ix_workflows_approvalinstance_{c}', c) for c in _INSTANCE_IX_COLS]
    if include_change_fields:
        indexes.append(sa.Index(_ROW_ID_IX, _ROW_ID_COL))
    return sa.Table(
        _INSTANCE,
        m,
        *cols,
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['workflow_id'], ['workflows_workflow.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['form_id'], ['forms_formdefinition.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['table_id'], ['tables_datatable.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['current_node_id'], ['workflows_workflownode.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['submitted_by'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        *indexes,
    )


def upgrade() -> None:
    """Upgrade schema."""
    if not _table_exists(_INSTANCE):
        return
    existing = _existing_columns(_INSTANCE)

    # 1. 变更单载荷列 op / row_id（幂等加列）
    if _OP_COL not in existing:
        op.add_column(_INSTANCE, sa.Column(_OP_COL, sa.String(length=16), nullable=True))
    if _ROW_ID_COL not in existing:
        op.add_column(_INSTANCE, sa.Column(_ROW_ID_COL, sa.Integer(), nullable=True))
    insp = sa.inspect(op.get_bind())
    if _table_exists(_INSTANCE) and _ROW_ID_IX not in {i['name'] for i in insp.get_indexes(_INSTANCE)}:
        op.create_index(_ROW_ID_IX, _INSTANCE, [_ROW_ID_COL], unique=False)

    # 2. form_id 放开可空（变更单无表单来源）：SQLite 需重建表，
    #    copy_from 显式定义避免反射解析幽灵 FK（见模块 docstring）
    if _column_nullable(_INSTANCE, 'form_id') is False:
        with op.batch_alter_table(_INSTANCE, copy_from=_instance_copy_from(include_change_fields=True)) as batch_op:
            batch_op.alter_column('form_id', existing_type=sa.Integer(), nullable=True)

    # 3. 表级编辑审批开关（NULL = 关闭；不建 FK，沿用链上加列先例）
    if _table_exists(_DT) and _SWITCH_COL not in _existing_columns(_DT):
        op.add_column(_DT, sa.Column(_SWITCH_COL, sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    if not _table_exists(_INSTANCE):
        return
    existing = _existing_columns(_INSTANCE)

    # 1. 表级开关列回退
    if _table_exists(_DT) and _SWITCH_COL in _existing_columns(_DT):
        op.drop_column(_DT, _SWITCH_COL)

    # 2. 变更单（op IS NOT NULL）在旧语义下不存在，回滚前须清除残留
    op.execute(f"DELETE FROM {_INSTANCE} WHERE {_OP_COL} IS NOT NULL")

    # 3. form_id 回 NOT NULL + 移除 op/row_id：一步 batch 重建（copy_from）
    if _OP_COL in existing and _column_nullable(_INSTANCE, 'form_id') is True:
        with op.batch_alter_table(_INSTANCE, copy_from=_instance_copy_from(include_change_fields=True)) as batch_op:
            batch_op.alter_column('form_id', existing_type=sa.Integer(), nullable=False)
            batch_op.drop_index(_ROW_ID_IX)
            batch_op.drop_column(_ROW_ID_COL)
            batch_op.drop_column(_OP_COL)
    else:
        # form_id 仍为 NOT NULL 的 create_all 时代库：仅移除载荷列
        insp = sa.inspect(op.get_bind())
        if _ROW_ID_IX in {i['name'] for i in insp.get_indexes(_INSTANCE)}:
            op.drop_index(_ROW_ID_IX, table_name=_INSTANCE)
        for col in (_ROW_ID_COL, _OP_COL):
            if col in _existing_columns(_INSTANCE):
                op.drop_column(_INSTANCE, col)
