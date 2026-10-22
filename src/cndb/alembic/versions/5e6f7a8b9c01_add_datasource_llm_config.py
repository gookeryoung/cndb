"""add_datasource_llm_config — 工作区级大模型连接（ADR 0019）.

Revision ID: 5e6f7a8b9c01
Revises: 2c3d4e5f6a70
Create Date: 2026-10-22 09:00:00.000000

- 新建 ``datasource_llm_config``：每个工作区至多一条记录，保存 OpenAI 兼容服务地址 /
  模型 / 加密 API Key / 可选系统提示词覆盖；
- ``workspace_id`` 建唯一索引，删除工作区时级联删除；``created_by`` 在用户删除时置空。

幂等：表 / 索引已存在就跳过；downgrade 反向移除，存量数据零迁移。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e6f7a8b9c01"
down_revision: str | Sequence[str] | None = "2c3d4e5f6a70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LLM_CONFIG = "datasource_llm_config"
_WORKSPACE_INDEX = f"ix_{_LLM_CONFIG}_workspace_id"
_CREATED_BY_INDEX = f"ix_{_LLM_CONFIG}_created_by"


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def _indexes(table: str) -> set[str]:
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {str(index["name"]) for index in insp.get_indexes(table) if index.get("name")}


def upgrade() -> None:
    """Upgrade schema: 建大模型连接表 + 唯一索引（幂等）."""
    if _table_exists(_LLM_CONFIG):
        return
    op.create_table(
        _LLM_CONFIG,
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
    op.create_index(_WORKSPACE_INDEX, _LLM_CONFIG, ["workspace_id"], unique=True)
    op.create_index(_CREATED_BY_INDEX, _LLM_CONFIG, ["created_by"])


def downgrade() -> None:
    """Downgrade schema: 删除大模型连接表（缺表 / 缺索引跳过）."""
    if not _table_exists(_LLM_CONFIG):
        return
    indexes = _indexes(_LLM_CONFIG)
    if _CREATED_BY_INDEX in indexes:
        op.drop_index(_CREATED_BY_INDEX, table_name=_LLM_CONFIG)
    if _WORKSPACE_INDEX in indexes:
        op.drop_index(_WORKSPACE_INDEX, table_name=_LLM_CONFIG)
    op.drop_table(_LLM_CONFIG)
