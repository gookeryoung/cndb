"""add_dataview_visibility — 视图可见性三档模型（ADR 0003 决策 D1/D2/D3/D4）.

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-10-16 21:30:00.000000

背景：视图可见性原先是**二元**的 —— ``owner_id IS NULL`` 编码"公共"、
``owner_id IS NOT NULL`` 编码"个人"，既无法表达"指定成员"这一中间档，
也把"创建者"与"可见性"两个概念混在一列里。本迁移引入显式档位列并收紧默认值：

- ``visibility``  ``table``（继承表权限）/ ``shared``（指定成员）/ ``private``（仅本人）
- ``scope_key``   命名空间：``0`` = 共享（table/shared 档），``user_id`` = 创建者私有

五步（可回滚；P1 已提前完成第 5 步）：

1. 加列（默认 ``private``，先不改行为）
2. 存量映射：``owner_id IS NULL OR is_default = 1`` → ``table``/``scope_key=0``；
   其余有 owner 的 → ``private``/``scope_key=owner_id``
   （即"存量视图继承表权限"，零行为变化；仅修正缺陷 #6：默认视图不再落成 owner 私有）
3. 唯一键由 ``(table_id, name)`` 换成 ``(table_id, scope_key, name)``
   —— 私有视图只在本人命名空间内唯一（修缺陷 #7）
4. ``owner_id`` 外键 ``CASCADE`` → ``SET NULL``（D3：创建者删号后视图作为"孤儿"保留，
   不能被级联删除 —— 否则"保留孤儿"的决策无从实现）
5. 建 ``tables_dataviewpermission``（``shared`` 档授权名单；P1 已移除匿名分享）

SQLite 限制：唯一约束与外键都无法就地修改，因此 Step 3+4 合并成一次
``batch_alter_table``（copy-and-move 重建表）。重建时用命名约定解析出无名外键
（SQLite 不保存 FK 名），才能按名 drop。

幂等约束（与 f7a8b9c0d1e2 / a4b5c6d7e8f9 同源）：
- 目标表不存在 → 由启动 create_all 兜底，本迁移跳过列/约束部分
- 列/索引已存在 → 跳过（不重复 ADD COLUMN）
- 唯一约束 / 外键已是目标形态 → 跳过 batch 步骤
- 表存在但不是完整业务形状（如测试/legacy 存根只含 ``id``/``name``）→
  与"表不存在"同等对待，只补列与索引，跳过依赖真实列的映射与约束重建
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b5c6d7e8f9a0"
down_revision: Union[str, Sequence[str], None] = "a4b5c6d7e8f9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "tables_dataview"
_GRANT_TABLE = "tables_dataviewpermission"
_VIS_INDEX = "ix_tables_dataview_visibility"
_OLD_UNIQUE = "uniq_table_view_name"
_NEW_UNIQUE = "uniq_table_view_scope_name"
_OWNER_FK = "fk_tables_dataview_owner_id_accounts_user"

#: SQLite 反射出的外键/唯一约束可能是无名的 —— 提供命名约定以便按名 drop
_NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def _table_exists(table: str) -> bool:
    return table in set(_inspector().get_table_names())


def _columns(table: str) -> set[str]:
    insp = _inspector()
    if table not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def _has_columns(table: str, *names: str) -> bool:
    """表是否存在且含全部指定列（用于识别"完整业务形状"的表）."""
    cols = _columns(table)
    return all(name in cols for name in names)


def _index_names(table: str) -> set[str]:
    insp = _inspector()
    if table not in set(insp.get_table_names()):
        return set()
    return {i["name"] for i in insp.get_indexes(table)}


def _unique_names(table: str) -> set[str]:
    insp = _inspector()
    if table not in set(insp.get_table_names()):
        return set()
    return {c["name"] for c in insp.get_unique_constraints(table) if c.get("name")}


def _owner_fk_ondelete(table: str) -> str | None:
    insp = _inspector()
    if table not in set(insp.get_table_names()):
        return None
    for fk in insp.get_foreign_keys(table):
        if fk.get("constrained_columns") == ["owner_id"]:
            return str(fk.get("options", {}).get("ondelete") or "").upper() or None
    return None


def _create_grant_table() -> None:
    """建 ``shared`` 档授权名单表（与 documents_permission 同构的白名单模式）."""
    if _table_exists(_GRANT_TABLE):
        return
    op.create_table(
        _GRANT_TABLE,
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("view_id", sa.Integer(), nullable=False),
        sa.Column("subject_type", sa.String(8), nullable=False),
        sa.Column("subject_id", sa.String(64), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("granted_by_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("view_id", "subject_type", "subject_id", name="uniq_view_grant_subject"),
        sa.ForeignKeyConstraint(["view_id"], [f"{_TABLE}.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by_id"], ["accounts_user.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_tables_dataviewpermission_view_id", _GRANT_TABLE, ["view_id"])


def upgrade() -> None:
    """Upgrade schema: 视图可见性三档（列 + 命名空间 + 唯一键 + FK + 授权表）."""
    table_exists = _table_exists(_TABLE)
    if table_exists:
        cols = _columns(_TABLE)
        added_columns = False
        if "visibility" not in cols:
            op.add_column(
                _TABLE,
                sa.Column("visibility", sa.String(16), nullable=False, server_default=sa.text("'private'")),
            )
            added_columns = True
        if "scope_key" not in cols:
            op.add_column(
                _TABLE,
                sa.Column("scope_key", sa.Integer(), nullable=False, server_default=sa.text("0")),
            )
            added_columns = True
        if _VIS_INDEX not in _index_names(_TABLE):
            op.create_index(_VIS_INDEX, _TABLE, ["visibility"])

        # Step 2 存量映射（仅在刚加列时执行，避免覆盖用户此后的主动调整；
        # 依赖 owner_id / is_default 两列，存根表缺列时整体跳过）
        if added_columns and _has_columns(_TABLE, "owner_id", "is_default"):
            op.get_bind().execute(
                sa.text(
                    f"UPDATE {_TABLE} SET visibility = 'table', scope_key = 0 "
                    "WHERE owner_id IS NULL OR is_default = 1"
                )
            )
            op.get_bind().execute(
                sa.text(
                    f"UPDATE {_TABLE} SET visibility = 'private', scope_key = owner_id "
                    "WHERE owner_id IS NOT NULL AND is_default = 0"
                )
            )

        # Step 3+4 唯一键与外键（SQLite 需重建表，故合并成一次 batch）
        # 唯一键引用 (table_id, scope_key, name)、外键引用 owner_id —— 三者缺一则跳过，
        # 否则会在存根表上造出引用不存在列的约束
        if _has_columns(_TABLE, "table_id", "owner_id", "name", "scope_key"):
            uqs = _unique_names(_TABLE)
            need_unique = _NEW_UNIQUE not in uqs
            need_fk = _owner_fk_ondelete(_TABLE) != "SET NULL"
            if need_unique or need_fk:
                with op.batch_alter_table(
                    _TABLE, naming_convention=_NAMING_CONVENTION, recreate="always"
                ) as batch:
                    if _OLD_UNIQUE in uqs:
                        batch.drop_constraint(_OLD_UNIQUE, type_="unique")
                    if need_unique:
                        batch.create_unique_constraint(_NEW_UNIQUE, ["table_id", "scope_key", "name"])
                    if need_fk:
                        if _OWNER_FK in {fk.get("name") for fk in _inspector().get_foreign_keys(_TABLE)}:
                            batch.drop_constraint(_OWNER_FK, type_="foreignkey")
                        batch.create_foreign_key(
                            _OWNER_FK,
                            "accounts_user",
                            ["owner_id"],
                            ["id"],
                            ondelete="SET NULL",
                        )

    # Step 5 授权名单表（共享档）—— 依附于 tables_dataview，父表缺失时整库交给 create_all 兜底
    if table_exists:
        _create_grant_table()


def downgrade() -> None:
    """Downgrade schema: 回到二元可见性（结构与约束，数据侧只回填 owner 语义）."""
    if _table_exists(_GRANT_TABLE):
        op.drop_index("ix_tables_dataviewpermission_view_id", table_name=_GRANT_TABLE)
        op.drop_table(_GRANT_TABLE)

    if _table_exists(_TABLE):
        cols = _columns(_TABLE)
        # 同理：存根表缺真实列时不重建约束，只回退列与索引
        if _has_columns(_TABLE, "table_id", "owner_id", "name"):
            uqs = _unique_names(_TABLE)
            need_old_unique = _NEW_UNIQUE in uqs or _OLD_UNIQUE not in uqs
            need_fk = _owner_fk_ondelete(_TABLE) != "CASCADE"
            if need_old_unique or need_fk:
                with op.batch_alter_table(
                    _TABLE, naming_convention=_NAMING_CONVENTION, recreate="always"
                ) as batch:
                    if _NEW_UNIQUE in uqs:
                        batch.drop_constraint(_NEW_UNIQUE, type_="unique")
                    if _OLD_UNIQUE not in uqs:
                        batch.create_unique_constraint(_OLD_UNIQUE, ["table_id", "name"])
                    if need_fk:
                        fk_names = {fk.get("name") for fk in _inspector().get_foreign_keys(_TABLE)}
                        if _OWNER_FK in fk_names:
                            batch.drop_constraint(_OWNER_FK, type_="foreignkey")
                        batch.create_foreign_key(
                            _OWNER_FK,
                            "accounts_user",
                            ["owner_id"],
                            ["id"],
                            ondelete="CASCADE",
                        )
        # 索引要先于列删除（SQLite 不允许 DROP 带索引的列）
        if _VIS_INDEX in _index_names(_TABLE):
            op.drop_index(op.f(_VIS_INDEX), table_name=_TABLE)
        for column in ("scope_key", "visibility"):
            if column in cols:
                op.drop_column(_TABLE, column)
