"""drop_dataview_public_share — 移除视图匿名公开分享（ADR 0003 决策 D5）.

Revision ID: a4b5c6d7e8f9
Revises: e6a7b8c9d0e1
Create Date: 2026-10-16 20:10:00.000000

背景：视图可见性的口径是「最大放宽至数据表范围内」，而匿名公开分享
（``is_public`` + ``public_slug`` + ``/api/v1/public/share/{slug}``）本质是
**表范围之外**的独立通道：拿到链接的人无需登录、不受表权限约束，也不走
字段隐藏（``hidden_fields``）与行级过滤。它与「分档可见性 + 表权限硬上限」
的模型互斥（飞书开启高级权限后原链接分享会整体失效，即同一取舍）。

因此整体移除该能力，删除两列与公开分享所需的路由/前端页面。移除后对外
分发改由「登录态深链」承接（链接带 view_id，访问校验表 READ + 视图
VIEW_READ，仍在表范围内）。

本迁移只负责数据层；路由与前端在同期代码中删除。

- tables_dataview.public_slug  String(12) + 唯一索引 ix_tables_dataview_public_slug
- tables_dataview.is_public    Boolean NOT NULL DEFAULT 0

幂等约束（与 f7a8b9c0d1e2 同源）：
- 目标表不存在 → 整表由启动 create_all 兜底，本迁移跳过
- 列/索引不存在 → 跳过（部分旧库经 create_all 时代建表从未有过这两列）

SQLite 限制：带索引的列不能直接 DROP COLUMN，因此先删索引再删列。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a4b5c6d7e8f9"
down_revision: Union[str, Sequence[str], None] = "e6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tables_dataview"
_SLUG_INDEX = "ix_tables_dataview_public_slug"


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists() -> bool:
    """目标表是否存在（不存在则整表由启动 create_all 兜底，本迁移跳过）."""
    return _TABLE in set(_inspector().get_table_names())


def _existing_columns() -> set[str]:
    """读取表当前已有的列名集合（表不存在时返回空集）."""
    insp = _inspector()
    if _TABLE not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns(_TABLE)}


def _existing_indexes() -> set[str]:
    """读取表当前已有的索引名集合（表不存在时返回空集）."""
    insp = _inspector()
    if _TABLE not in set(insp.get_table_names()):
        return set()
    # 匿名索引的 name 可能是 None（SQLite 自动索引），调用方只关心具名索引
    names: set[str] = set()
    for index in insp.get_indexes(_TABLE):
        name = index["name"]
        if name:
            names.add(name)
    return names


def _drop_column_if_exists(column: str) -> None:
    """列存在才 drop_column（幂等，兼容 create_all 时代从未有过该列的旧库）."""
    if not _table_exists() or column not in _existing_columns():
        return
    op.drop_column(_TABLE, column)


def upgrade() -> None:
    """Upgrade schema: 删除视图匿名公开分享所需的两列与唯一索引."""
    if not _table_exists():
        return
    # 先删索引：SQLite 不允许对带索引的列执行 DROP COLUMN
    if _SLUG_INDEX in _existing_indexes():
        op.drop_index(op.f(_SLUG_INDEX), table_name=_TABLE)
    _drop_column_if_exists("public_slug")
    _drop_column_if_exists("is_public")


def downgrade() -> None:
    """Downgrade schema: 恢复两列与唯一索引（幂等，缺表时跳过）.

    仅恢复结构；已失效的分享链接（列被清空后 slug 丢失）无法还原。
    """
    if not _table_exists():
        return
    cols = _existing_columns()
    if "is_public" not in cols:
        op.add_column(
            _TABLE,
            sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "public_slug" not in cols:
        op.add_column(_TABLE, sa.Column("public_slug", sa.String(12), nullable=True))
    if _SLUG_INDEX not in _existing_indexes():
        op.create_index(op.f(_SLUG_INDEX), _TABLE, ["public_slug"], unique=True)
