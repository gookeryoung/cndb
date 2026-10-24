"""github issue pr refactor

GitHub 风格「问题 + 修改申请」重构（P1 后端基座）：
1. 工作区角色三级化：workspaces_workspacemember.role='admin' → 'editor'；
2. 在途变更单迁移：workflows_approvalinstance 中 op IS NOT NULL 且 status='pending'
   的记录逐条转换为 change_requests_changerequest + change_requests_changeitem
   （base_values 置空 dict，merge 端按「基准缺失 = 无漂移检测」语义处理）；
3. drop 六张旧表：workflows_workflow / workflownode / workflowedge /
   approvalinstance / approvalaction、forms_formdefinition；
4. drop 列 tables_datatable.edit_approval_workflow_id；
5. 新建 issues_issue / issues_issuecomment / issues_issueevent、
   change_requests_changerequest / changeitem / changeaction。

关键约束（沿用 d5c6a7b8e9f0 既有模式）：
- 防御式：目标表不存在时跳过（由启动 create_all 按完整 ORM 元数据兜底）；
- 幂等：表/列已存在时跳过，兼容 create_all 时代旧库；
- drop 列走 batch 模式（SQLite 无裸 ALTER DROP COLUMN）；
- 新建表带 FK（建表时目标表均存在）。

Revision ID: e8f9a0b1c2d3
Revises: d5c6a7b8e9f0
Create Date: 2026-10-13 08:00:00.000000

"""

import contextlib
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, Sequence[str], None] = 'd5c6a7b8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_MEMBER = 'workspaces_workspacemember'
_INSTANCE = 'workflows_approvalinstance'
_DT = 'tables_datatable'
_SWITCH_COL = 'edit_approval_workflow_id'

# drop 顺序：先运行时表（被依赖方后删）
_DROP_TABLES = (
    'workflows_approvalaction',
    'workflows_approvalinstance',
    'workflows_workflowedge',
    'workflows_workflownode',
    'workflows_workflow',
    'forms_formdefinition',
)

_TS_DEFAULT = sa.text('(CURRENT_TIMESTAMP)')


def _table_exists(table: str) -> bool:
    """目标表是否存在（不存在则由启动 create_all 兜底，本迁移跳过对应步骤）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _existing_columns(table: str) -> set[str]:
    """读取表当前已有的列名集合（表不存在时返回空集）."""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c['name'] for c in insp.get_columns(table)}


def _migrate_pending_change_requests() -> int:
    """把在途变更单（op 非 NULL 且 pending）转换为修改申请 + 变更项.

    Returns:
        迁移的变更单条数.
    """
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            f'SELECT id, workspace_id, table_id, op, row_id, "values", submitted_by, created_at, updated_at '
            f"FROM {_INSTANCE} WHERE op IS NOT NULL AND status = 'pending'"
        )
    ).mappings().all()
    for r in rows:
        result = conn.execute(
            sa.text(
                "INSERT INTO change_requests_changerequest "
                "(workspace_id, table_id, title, description, status, stale, submitted_by_id, "
                "review_comment, created_at, updated_at) "
                "VALUES (:ws, :tid, :title, :desc, 'open', 0, :uid, '', :created, :updated)"
            ),
            {
                "ws": r["workspace_id"],
                "tid": r["table_id"],
                "title": f"迁移自变更单 #{r['id']}",
                "desc": f"原审批流变更单自动迁移（op={r['op']}, row_id={r['row_id']}）",
                "uid": r["submitted_by"],
                "created": r["created_at"],
                "updated": r["updated_at"],
            },
        )
        cr_id = result.lastrowid
        conn.execute(
            sa.text(
                "INSERT INTO change_requests_changeitem "
                '(request_id, op, row_id, base_values, "values", created_at, updated_at) '
                "VALUES (:rid, :op, :row_id, '{}', :values, :created, :updated)"
            ),
            {
                "rid": cr_id,
                "op": r["op"],
                "row_id": r["row_id"],
                "values": r["values"] or "{}",
                "created": r["created_at"],
                "updated": r["updated_at"],
            },
        )
    return len(rows)


def _cr_request_table() -> sa.Table:
    """change_requests_changerequest 建表定义（与 ORM 模型逐列对齐）."""
    return sa.Table(
        'change_requests_changerequest',
        sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('table_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('stale', sa.Boolean(), nullable=False),
        sa.Column('submitted_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_by_id', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_comment', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['table_id'], ['tables_datatable.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['submitted_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['reviewed_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def _cr_item_table() -> sa.Table:
    """change_requests_changeitem 建表定义."""
    return sa.Table(
        'change_requests_changeitem',
        sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('op', sa.String(length=16), nullable=False),
        sa.Column('row_id', sa.Integer(), nullable=True),
        sa.Column('base_values', sa.JSON(), nullable=False),
        sa.Column('values', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(
            ['request_id'], ['change_requests_changerequest.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )


def _cr_action_table() -> sa.Table:
    """change_requests_changeaction 建表定义."""
    return sa.Table(
        'change_requests_changeaction',
        sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('request_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('comment', sa.Text(), nullable=False),
        sa.Column('acted_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(
            ['request_id'], ['change_requests_changerequest.id'], ondelete='CASCADE'
        ),
        sa.ForeignKeyConstraint(['acted_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def _issue_table() -> sa.Table:
    """issues_issue 建表定义."""
    return sa.Table(
        'issues_issue',
        sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('workspace_id', sa.Integer(), nullable=False),
        sa.Column('table_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=32), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['table_id'], ['tables_datatable.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def _issue_comment_table() -> sa.Table:
    """issues_issuecomment 建表定义."""
    return sa.Table(
        'issues_issuecomment',
        sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('issue_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_by_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(['issue_id'], ['issues_issue.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['created_by_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


def _issue_event_table() -> sa.Table:
    """issues_issueevent 建表定义."""
    return sa.Table(
        'issues_issueevent',
        sa.MetaData(),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('issue_id', sa.Integer(), nullable=False),
        sa.Column('action', sa.String(length=16), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
        sa.ForeignKeyConstraint(['issue_id'], ['issues_issue.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['actor_id'], ['accounts_user.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )


# 新表定义：(建表函数, 索引列表[(索引名, 列)])
_NEW_TABLES: tuple[tuple[Any, tuple[tuple[str, str], ...]], ...] = (
    (
        _cr_request_table,
        (
            ('ix_change_requests_changerequest_workspace_id', 'workspace_id'),
            ('ix_change_requests_changerequest_table_id', 'table_id'),
            ('ix_change_requests_changerequest_status', 'status'),
            ('ix_change_requests_changerequest_submitted_by_id', 'submitted_by_id'),
        ),
    ),
    (
        _cr_item_table,
        (
            ('ix_change_requests_changeitem_request_id', 'request_id'),
            ('ix_change_requests_changeitem_row_id', 'row_id'),
        ),
    ),
    (
        _cr_action_table,
        (('ix_change_requests_changeaction_request_id', 'request_id'),),
    ),
    (
        _issue_table,
        (
            ('ix_issues_issue_workspace_id', 'workspace_id'),
            ('ix_issues_issue_table_id', 'table_id'),
            ('ix_issues_issue_status', 'status'),
            ('ix_issues_issue_created_by_id', 'created_by_id'),
        ),
    ),
    (
        _issue_comment_table,
        (('ix_issues_issuecomment_issue_id', 'issue_id'),),
    ),
    (
        _issue_event_table,
        (('ix_issues_issueevent_issue_id', 'issue_id'),),
    ),
)


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()

    # 1. 角色三级化：admin → editor
    if _table_exists(_MEMBER) and 'role' in _existing_columns(_MEMBER):
        conn.execute(sa.text(f"UPDATE {_MEMBER} SET role = 'editor' WHERE role = 'admin'"))

    # 2. 新表先建（在途变更单转换的目标）
    for table_fn, indexes in _NEW_TABLES:
        table = table_fn()
        if not _table_exists(table.name):
            op.create_table(table.name, *table.columns, *table.constraints)
            for ix_name, ix_col in indexes:
                op.create_index(ix_name, table.name, [ix_col], unique=False)

    # 3. 在途变更单 → 修改申请
    if _table_exists(_INSTANCE) and _table_exists('change_requests_changerequest'):
        _migrate_pending_change_requests()

    # 4. drop 表级「编辑需审批」开关列（须在 workflows_workflow 删除前执行）
    if _table_exists(_DT) and _SWITCH_COL in _existing_columns(_DT):
        with op.batch_alter_table(_DT) as batch_op:
            batch_op.drop_column(_SWITCH_COL)

    # 5. drop 旧表（无外则依赖：SQLite 默认不校验 FK）
    for t in _DROP_TABLES:
        if _table_exists(t):
            op.drop_table(t)


def downgrade() -> None:
    """Downgrade schema."""
    conn = op.get_bind()

    # 1. drop 新表
    for table_fn, indexes in reversed(_NEW_TABLES):
        table = table_fn()
        if _table_exists(table.name):
            for ix_name, _ in indexes:
                with contextlib.suppress(Exception):
                    op.drop_index(ix_name, table_name=table.name)
            op.drop_table(table.name)

    # 2. 回退角色：无法区分「原 admin」与迁移后的 editor，仅恢复枚举兼容（no-op 数据回退）
    if _table_exists(_MEMBER) and 'role' in _existing_columns(_MEMBER):
        conn.execute(sa.text(f"UPDATE {_MEMBER} SET role = 'admin' WHERE role = 'editor' AND 1 = 0"))

    # 3. 重建旧表 schema（数据不可恢复，仅保证结构可回退）
    if not _table_exists('workflows_workflow'):
        op.create_table(
            'workflows_workflow',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('workspace_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('order', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
            sa.ForeignKeyConstraint(['workspace_id'], ['workspaces_workspace.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_workflows_workflow_workspace_id', 'workflows_workflow', ['workspace_id'])
    if not _table_exists('forms_formdefinition'):
        op.create_table(
            'forms_formdefinition',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
            sa.Column('workspace_id', sa.Integer(), nullable=False),
            sa.Column('table_id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=255), nullable=False),
            sa.Column('slug', sa.String(length=64), nullable=False),
            sa.Column('description', sa.Text(), nullable=False),
            sa.Column('fields', sa.JSON(), nullable=False),
            sa.Column('submit_policy', sa.String(length=16), nullable=False),
            sa.Column('created_by', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=_TS_DEFAULT, nullable=False),
            sa.PrimaryKeyConstraint('id'),
        )

    # 4. 恢复表级开关列
    if _table_exists(_DT) and _SWITCH_COL not in _existing_columns(_DT):
        op.add_column(_DT, sa.Column(_SWITCH_COL, sa.Integer(), nullable=True))
