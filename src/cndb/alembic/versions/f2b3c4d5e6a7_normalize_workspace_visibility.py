"""normalize_workspace_visibility — 工作区可见性语义归一（ADR 0153 D6 / P2 补充）.

Revision ID: f2b3c4d5e6a7
Revises: e7d8c9b0a1f2
Create Date: 2026-11-25 13:00:00.000000

背景：``workspaces_workspace.visibility`` 自加入以来**从未参与判定**（全仓只有写入与
展示），因此存量取值（public / member / private）在行为上完全等价于 `member`。

本次把 `private` 收紧为「仅工作区所有者可见」之前，先把**存量 `private` 归一为
`member`**：

- 升级前：`private` 与 `member` 行为一致（字段不被读取）；
- 升级后：存量 `private` 行已变成 `member` ⇒ 行为仍与升级前一致（I3 / H13「存量
  行为不变」）；只有**之后显式选择** `private` 的工作区才是「仅所有者可见」。
- 幂等：重复执行是空操作（`WHERE visibility='private'` 第二次无命中）；无表时跳过。
- downgrade 为**空操作**：旧版代码不读取该字段，任何取值行为一致，无需也不应回滚
  数据（否则会把用户显式选择的 `member` 误改成 `private`）。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2b3c4d5e6a7'
down_revision: Union[str, Sequence[str], None] = 'e7d8c9b0a1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = 'workspaces_workspace'


def _table_exists(table: str) -> bool:
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade() -> None:
    """存量 `private` → `member`（语义归一；行为与升级前一致）."""
    if not _table_exists(_TABLE):
        return
    op.execute(
        sa.text(
            f"UPDATE {_TABLE} SET visibility = 'member' "  # noqa: S608 - 表名是模块常量
            "WHERE visibility = 'private'"
        )
    )


def downgrade() -> None:
    """空操作（旧版代码不读取 visibility，回滚数据反而会篡改用户意图）."""
    return
