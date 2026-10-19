"""add_workspace_type — 工作区类型（数据+文档 / 数据 / 文档）.

Revision ID: e7f8a9b0c1d2
Revises: c8d9e0f1a2b3
Create Date: 2026-10-19 12:00:00.000000

为 ``workspaces_workspace`` 增加 ``workspace_type`` 列，决定工作区提供哪些
功能模块：

- ``data_doc``：数据 + 文档（数据表 / 数据分析 / 文档），默认
- ``data``：仅数据（数据表 / 数据分析）
- ``doc``：仅文档

存量工作区一律回填默认值 ``data_doc``（保持既有全部功能可见）。幂等加列，
兼容 create_all 时代已含该列的旧库。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "c8d9e0f1a2b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "workspaces_workspace"
_COLUMN = "workspace_type"
# ORM 列类型为 Enum(WorkspaceType)（StrEnum），SQLAlchemy 落库的是枚举成员名
# （DATA_DOC / DATA / DOC），而非枚举值。故此处枚举与默认值都必须用名字，
# 否则存量行回填 value 后读回会抛 LookupError（同 6399e5f0f61f 的 workspacerole 约定）。
_ENUM_NAMES = ("DATA_DOC", "DATA", "DOC")
_DEFAULT = "DATA_DOC"


def _table_exists(table: str) -> bool:
    """目标表是否存在（不存在则整表由启动 create_all 兜底，本迁移跳过）."""
    return table in sa.inspect(op.get_bind()).get_table_names()


def _existing_columns(table: str) -> set[str]:
    """读取表当前已有的列名集合（表不存在时返回空集）."""
    insp = sa.inspect(op.get_bind())
    if table not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    """Upgrade schema: 补 workspace_type 列（幂等）."""
    if not _table_exists(_TABLE) or _COLUMN in _existing_columns(_TABLE):
        return
    op.add_column(
        _TABLE,
        sa.Column(
            _COLUMN,
            sa.Enum(*_ENUM_NAMES, name="workspacetype"),
            nullable=False,
            server_default=_DEFAULT,
        ),
    )


def downgrade() -> None:
    """Downgrade schema: 移除 workspace_type 列（缺表或缺列时跳过）."""
    if not _table_exists(_TABLE) or _COLUMN not in _existing_columns(_TABLE):
        return
    op.drop_column(_TABLE, _COLUMN)
