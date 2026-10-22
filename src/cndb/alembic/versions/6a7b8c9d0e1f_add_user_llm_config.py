"""add_user_llm_config — 大模型连接改为个人配置（ADR 0019）.

Revision ID: 6a7b8c9d0e1f
Revises: 5e6f7a8b9c01
Create Date: 2026-10-22 13:00:00.000000

- 新建 ``datasource_user_llm_config``：每个用户至多一条记录，保存 OpenAI 兼容服务地址 /
  模型 / 加密 API Key / 可选系统提示词覆盖；
- ``user_id`` 建唯一索引，删除用户时级联删除；
- 把旧工作区表 ``datasource_llm_config`` 的数据搬迁到新表（``created_by`` 作为用户）；
  同一用户多行只取一条（按 id 升序取第一条），``created_by`` 为空的记录无处归属，丢弃；
- 搬迁完成后删除旧表；downgrade 重建旧表并删除新表。

幂等：表 / 索引已存在就跳过；旧表不存在时跳过搬迁与删除。downgrade **不恢复数据**
（旧表数据的归属关系已不可逆，重建后为空表，可由用户重新配置），这是可接受的损失。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6a7b8c9d0e1f"
down_revision: str | Sequence[str] | None = "5e6f7a8b9c01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TABLE = "datasource_llm_config"
_NEW_TABLE = "datasource_user_llm_config"
_NEW_USER_INDEX = f"ix_{_NEW_TABLE}_user_id"
_OLD_WORKSPACE_INDEX = f"ix_{_OLD_TABLE}_workspace_id"
_OLD_CREATED_BY_INDEX = f"ix_{_OLD_TABLE}_created_by"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _indexes(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {str(index["name"]) for index in insp.get_indexes(table) if index.get("name")}


def _create_new_table() -> None:
    op.create_table(
        _NEW_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("api_key", sa.String(length=1024), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
    )
    op.create_index(_NEW_USER_INDEX, _NEW_TABLE, ["user_id"], unique=True)


def _create_old_table() -> None:
    op.create_table(
        _OLD_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "workspace_id",
            sa.Integer(),
            sa.ForeignKey("workspaces_workspace.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("base_url", sa.String(length=512), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("api_key", sa.String(length=1024), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
    )
    op.create_index(_OLD_WORKSPACE_INDEX, _OLD_TABLE, ["workspace_id"], unique=True)
    op.create_index(_OLD_CREATED_BY_INDEX, _OLD_TABLE, ["created_by"])


def _migrate_rows_to_user_config() -> None:
    """把旧工作区连接按 ``created_by`` 搬到新表（同一用户取 id 最小的一条）."""
    bind = op.get_bind()
    metadata = sa.MetaData()
    old_table = sa.Table(
        _OLD_TABLE,
        metadata,
        sa.Column("id", sa.Integer()),
        sa.Column("workspace_id", sa.Integer()),
        sa.Column("created_by", sa.Integer()),
        sa.Column("base_url", sa.String()),
        sa.Column("model", sa.String()),
        sa.Column("api_key", sa.String()),
        sa.Column("system_prompt", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    new_table = sa.Table(
        _NEW_TABLE,
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer()),
        sa.Column("base_url", sa.String()),
        sa.Column("model", sa.String()),
        sa.Column("api_key", sa.String()),
        sa.Column("system_prompt", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    existing = {int(row[0]) for row in bind.execute(sa.select(new_table.c.user_id)).all()}
    rows = bind.execute(
        sa.select(
            old_table.c.created_by,
            old_table.c.base_url,
            old_table.c.model,
            old_table.c.api_key,
            old_table.c.system_prompt,
            old_table.c.created_at,
            old_table.c.updated_at,
        )
        .where(old_table.c.created_by.is_not(None))
        .order_by(old_table.c.id)
    ).all()
    payload: list[dict[str, object]] = []
    for row in rows:
        user_id = int(row.created_by)
        if user_id in existing:
            continue
        existing.add(user_id)
        payload.append(
            {
                "user_id": user_id,
                "base_url": row.base_url,
                "model": row.model,
                "api_key": row.api_key,
                "system_prompt": row.system_prompt,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    if payload:
        bind.execute(sa.insert(new_table), payload)


def upgrade() -> None:
    """Upgrade schema: 建个人连接表 → 搬迁旧工作区连接 → 删旧表（缺表 / 已建跳过）."""
    if not _table_exists(_NEW_TABLE):
        _create_new_table()
    if not _table_exists(_OLD_TABLE):
        return
    _migrate_rows_to_user_config()
    op.drop_table(_OLD_TABLE)


def downgrade() -> None:
    """Downgrade schema: 重建旧工作区表（数据不恢复）并删除个人连接表."""
    if not _table_exists(_OLD_TABLE):
        _create_old_table()
    if not _table_exists(_NEW_TABLE):
        return
    indexes = _indexes(_NEW_TABLE)
    if _NEW_USER_INDEX in indexes:
        op.drop_index(_NEW_USER_INDEX, table_name=_NEW_TABLE)
    op.drop_table(_NEW_TABLE)
