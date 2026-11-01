"""workspace_modules —— 工作区类型枚举改为功能模块集合（ADR 0080 P0）.

Revision ID: b6c7d8e9f0a1
Revises: z4a5b6c7d8e9
Create Date: 2026-11-01 16:00:00.000000

``workspaces_workspace`` 列变更：

- 新增 ``modules`` JSON 列（先 nullable，回填后置 NOT NULL）；
- 回填映射（ADR 0080 D5，与 ``workspaces/modules.py::legacy_type_to_modules``
  同一份口径）：``DATA_DOC → ["tables","documents","design"]``、
  ``DATA → ["tables"]``、``DOC → ["documents","design"]``；
- drop 旧列 ``workspace_type``（SQLite 经 batch 重建）。

downgrade 有损映射（D6）：含 tables 且含 documents → ``DATA_DOC``；含
tables → ``DATA``；其余 → ``DOC``。每步前查列存在性，幂等。
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6c7d8e9f0a1"
down_revision: str | Sequence[str] | None = "z4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "workspaces_workspace"
_NEW = "modules"
_OLD = "workspace_type"


def _existing_columns() -> set[str]:
    """表当前列名集合（表不存在返回空集，整表由启动 create_all 兜底）."""
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        return set()
    return {c["name"] for c in insp.get_columns(_TABLE)}


def upgrade() -> None:
    """Upgrade: 加 modules 列 → CASE 回填 → 置 NOT NULL → drop workspace_type（幂等）."""
    columns = _existing_columns()
    if not columns:
        return

    if _NEW not in columns:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_NEW, sa.JSON(), nullable=True))

    if _OLD in columns:
        # 旧枚举落库为成员名（DATA_DOC/DATA/DOC），按 D5 映射回填
        op.execute(
            f"UPDATE {_TABLE} SET {_NEW} = CASE {_OLD} "  # nosec B608 - 常量表名/列名
            "WHEN 'DATA' THEN '[\"tables\"]' "
            "WHEN 'DOC' THEN '[\"documents\",\"design\"]' "
            "ELSE '[\"tables\",\"documents\",\"design\"]' END "
            f"WHERE {_NEW} IS NULL"
        )
    else:
        # modules 已存在但为空（异常中间态）：回退默认全三模块
        op.execute(f"UPDATE {_TABLE} SET {_NEW} = '[\"tables\",\"documents\",\"design\"]' WHERE {_NEW} IS NULL")  # nosec B608

    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column(_NEW, existing_type=sa.JSON(), nullable=False)

    if _OLD in _existing_columns():
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_OLD)


def downgrade() -> None:
    """Downgrade: 重建 workspace_type 列 → 有损映射回填 → drop modules（幂等）.

    映射（D6）：含 tables 且含 documents → DATA_DOC；含 tables → DATA；其余 → DOC。
    """
    columns = _existing_columns()
    if not columns:
        return

    if _OLD not in columns:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_OLD, sa.Enum("DATA_DOC", "DATA", "DOC", name="workspacetype"), nullable=True))

    if _NEW in columns:
        # JSON 落库为文本，按子串判定包含关系（顺序：先判 DATA_DOC 再判 DATA）
        op.execute(
            f"UPDATE {_TABLE} SET {_OLD} = CASE "  # nosec B608 - 常量表名/列名
            f"WHEN {_NEW} LIKE '%\"tables\"%' AND {_NEW} LIKE '%\"documents\"%' THEN 'DATA_DOC' "
            f"WHEN {_NEW} LIKE '%\"tables\"%' THEN 'DATA' "
            "ELSE 'DOC' END "
            f"WHERE {_OLD} IS NULL"
        )

    if _NEW in _existing_columns():
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_NEW)
