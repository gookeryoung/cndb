"""add_user_phone_and_auditlog — 用户管理模块升级：phone 列 + 用户操作日志表.

Revision ID: a9c0d1e2f3b4
Revises: f7a8b9c0d1e2
Create Date: 2026-10-10 12:00:00.000000

新增内容：
- accounts_user.phone         String(32) NULL（联系方式扩展，管理端编辑用）
- accounts_userauditlog       平台级用户管理操作日志表（action/actor_id/target_user_id/detail JSON）

幂等策略与 f7a8b9c0d1e2 一致：表不存在则由启动 create_all 兜底建表；
phone 列存在性检查后补加（SQLite 不支持裸 ALTER 加约束，不建 FK）。
"""
from typing import Any, Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9c0d1e2f3b4'
down_revision: Union[str, Sequence[str], None] = 'f7a8b9c0d1e2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUDIT_TABLE = "accounts_userauditlog"
_USER_TABLE = "accounts_user"


def _table_exists(table: str) -> bool:
    """目标表是否存在."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _existing_columns(table: str) -> set[str]:
    """读取表当前已有的列名集合（表不存在时返回空集）."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema: 补 phone 列 + 建用户操作日志表与索引."""
    if _table_exists(_USER_TABLE) and "phone" not in _existing_columns(_USER_TABLE):
        op.add_column(_USER_TABLE, sa.Column("phone", sa.String(32), nullable=True))

    if not _table_exists(_AUDIT_TABLE):
        op.create_table(
            _AUDIT_TABLE,
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("action", sa.String(32), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("target_user_id", sa.Integer(), nullable=True),
            sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
    insp = sa.inspect(op.get_bind())
    idx_names = {i["name"] for i in insp.get_indexes(_AUDIT_TABLE)}
    for idx_name, col in (
        (op.f("ix_accounts_userauditlog_action"), "action"),
        (op.f("ix_accounts_userauditlog_actor_id"), "actor_id"),
        (op.f("ix_accounts_userauditlog_target_user_id"), "target_user_id"),
    ):
        if idx_name not in idx_names:
            op.create_index(idx_name, _AUDIT_TABLE, [col])


def downgrade() -> None:
    """Downgrade schema: 删除日志表与 phone 列（缺表/缺列时跳过）."""
    conn = op.get_bind()
    insp = sa.inspect(conn)
    table_names = set(insp.get_table_names())
    if _AUDIT_TABLE in table_names:
        op.drop_table(_AUDIT_TABLE)
    if _USER_TABLE in table_names and "phone" in _existing_columns(_USER_TABLE):
        op.drop_column(_USER_TABLE, "phone")
