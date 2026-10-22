"""add_llm_plugin — 大模型能力平台化（ADR 0020 P0）.

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-10-22 14:10:00.000000

- 新建 ``llm_user_config``（自 ``datasource_user_llm_config`` 全量搬迁，列一一对应）；
- 新建 ``llm_run``：调用留痕（动作 / 模型 / token / 耗时 / 状态 / 错误摘要），不含提示词正文；
- 搬迁完成后删除旧表；downgrade 重建**空**的 ``datasource_user_llm_config``（结构与
  ``6a7b8c9d0e1f`` 建表一致，`user_id` 唯一）并删除新表（数据不恢复，用户可重新配置，与既有迁移口径一致）。

幂等：表 / 索引已存在就跳过；旧表不存在时跳过搬迁与删除。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7b8c9d0e1f2a"
down_revision: str | Sequence[str] | None = "6a7b8c9d0e1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TABLE = "datasource_user_llm_config"
_CONFIG_TABLE = "llm_user_config"
_RUN_TABLE = "llm_run"

_CONFIG_USER_INDEX = f"ix_{_CONFIG_TABLE}_user_id"
_RUN_USER_INDEX = f"ix_{_RUN_TABLE}_user_id"
_RUN_WORKSPACE_INDEX = f"ix_{_RUN_TABLE}_workspace_id"
_RUN_ACTION_INDEX = f"ix_{_RUN_TABLE}_action"
_RUN_STATUS_INDEX = f"ix_{_RUN_TABLE}_status"
_RUN_CREATED_INDEX = f"ix_{_RUN_TABLE}_created_at"
_RUN_USER_CREATED_INDEX = f"ix_{_RUN_TABLE}_user_created"

# 旧个人连接表（downgrade 重建用，结构与 6a7b8c9d0e1f 的 ``_create_new_table`` 一致）
_OLD_USER_INDEX = f"ix_{_OLD_TABLE}_user_id"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _indexes(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {str(index["name"]) for index in insp.get_indexes(table) if index.get("name")}


def _create_config_table() -> None:
    op.create_table(
        _CONFIG_TABLE,
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
    op.create_index(_CONFIG_USER_INDEX, _CONFIG_TABLE, ["user_id"], unique=True)


def _create_run_table() -> None:
    op.create_table(
        _RUN_TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("accounts_user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("workspace_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
    )
    op.create_index(_RUN_USER_INDEX, _RUN_TABLE, ["user_id"])
    op.create_index(_RUN_WORKSPACE_INDEX, _RUN_TABLE, ["workspace_id"])
    op.create_index(_RUN_ACTION_INDEX, _RUN_TABLE, ["action"])
    op.create_index(_RUN_STATUS_INDEX, _RUN_TABLE, ["status"])
    op.create_index(_RUN_CREATED_INDEX, _RUN_TABLE, ["created_at"])
    op.create_index(_RUN_USER_CREATED_INDEX, _RUN_TABLE, ["user_id", "created_at"])


def _create_old_table() -> None:
    op.create_table(
        _OLD_TABLE,
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
    op.create_index(_OLD_USER_INDEX, _OLD_TABLE, ["user_id"], unique=True)


def _migrate_rows() -> None:
    """把旧个人连接表全量搬到新表（保留 id / 时间戳，user_id 已唯一）."""
    bind = op.get_bind()
    metadata = sa.MetaData()
    old_table = sa.Table(
        _OLD_TABLE,
        metadata,
        sa.Column("id", sa.Integer()),
        sa.Column("user_id", sa.Integer()),
        sa.Column("base_url", sa.String()),
        sa.Column("model", sa.String()),
        sa.Column("api_key", sa.String()),
        sa.Column("system_prompt", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
    )
    new_table = sa.Table(
        _CONFIG_TABLE,
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
            old_table.c.id,
            old_table.c.user_id,
            old_table.c.base_url,
            old_table.c.model,
            old_table.c.api_key,
            old_table.c.system_prompt,
            old_table.c.created_at,
            old_table.c.updated_at,
        ).order_by(old_table.c.id)
    ).all()
    payload: list[dict[str, object]] = []
    for row in rows:
        user_id = int(row.user_id)
        if user_id in existing:
            continue
        existing.add(user_id)
        payload.append(
            {
                "id": int(row.id),
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
    """建新表 → 搬数据 → 建运行记录表 → 删旧表（缺表 / 已建跳过）."""
    if not _table_exists(_CONFIG_TABLE):
        _create_config_table()
    if not _table_exists(_RUN_TABLE):
        _create_run_table()
    if not _table_exists(_OLD_TABLE):
        return
    _migrate_rows()
    op.drop_table(_OLD_TABLE)


def downgrade() -> None:
    """重建空旧表（数据不恢复）→ 删除运行记录表 → 删除新连接表."""
    if not _table_exists(_OLD_TABLE):
        _create_old_table()
    if _table_exists(_RUN_TABLE):
        for index_name in (
            _RUN_USER_INDEX,
            _RUN_WORKSPACE_INDEX,
            _RUN_ACTION_INDEX,
            _RUN_STATUS_INDEX,
            _RUN_CREATED_INDEX,
            _RUN_USER_CREATED_INDEX,
        ):
            if index_name in _indexes(_RUN_TABLE):
                op.drop_index(index_name, table_name=_RUN_TABLE)
        op.drop_table(_RUN_TABLE)
    if not _table_exists(_CONFIG_TABLE):
        return
    if _CONFIG_USER_INDEX in _indexes(_CONFIG_TABLE):
        op.drop_index(_CONFIG_USER_INDEX, table_name=_CONFIG_TABLE)
    op.drop_table(_CONFIG_TABLE)
