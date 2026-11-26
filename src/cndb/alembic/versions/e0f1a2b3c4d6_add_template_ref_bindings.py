"""add_template_ref_bindings — 文档 / 内容模板的排版模板绑定列（ADR 0177 P3）.

新增两列，均可空、**无外键**：

- ``documents_document.export_template_ref``：文档级默认排版模板；
- ``documents_contenttemplate.export_template_ref``：内容模板自带的排版模板
  （「从模板新建」时写入新文档）。

存量行保持 ``NULL``（跟随工作区默认），导出行为不变；downgrade 直接删列还原。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e0f1a2b3c4d6"
down_revision: Union[str, Sequence[str], None] = "d9e0f1a2b3c5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: (表名, 列名) 清单；升级 / 降级都按列是否存在做幂等
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("documents_document", "export_template_ref"),
    ("documents_contenttemplate", "export_template_ref"),
)


def _column_names(table: str) -> set[str] | None:
    """表存在时返回列名集合；表不存在返回 None（残缺库升级时跳过该表）."""
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    """补两列（表 / 列已存在则跳过：全量建库后 stamp 回旧版重放的幂等场景）."""
    for table, column in _COLUMNS:
        columns = _column_names(table)
        if columns is None or column in columns:
            continue
        op.add_column(table, sa.Column(column, sa.String(length=64), nullable=True))


def downgrade() -> None:
    """删两列，回到 ADR 0177 P3 之前的库结构（表或列不存在时跳过）."""
    for table, column in _COLUMNS:
        columns = _column_names(table)
        if columns is None or column not in columns:
            continue
        op.drop_column(table, column)
