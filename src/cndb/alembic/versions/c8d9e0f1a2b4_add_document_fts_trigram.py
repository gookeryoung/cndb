"""add_document_fts_trigram — 文档检索 trigram 影子表（需求 0171）.

新增 FTS5 ``trigram`` 虚拟表 ``documents_fts_tri``，与现有 ``documents_fts``
（unicode61）并行维护：unicode61 把连续中文当单 token，2 字查询无法索引；
trigram 按 3 字符切分，可覆盖 ≥3 字符的中文子串。两表同 rowid、同正文。

**存量回填**：不在迁移内读外存正文，交由 ``ensure_fts_schema`` 在首次打开库时
从主表复制非空行回填（幂等、只补缺行/空行），避免迁移期依赖 data/docs 路径。

**downgrade**：仅 drop 影子表；主表与业务数据不变。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c8d9e0f1a2b4"
down_revision: Union[str, Sequence[str], None] = "b8c7d6e5f4a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts_tri USING fts5("
        "title, content, summary, author, tokenize='trigram')"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents_fts_tri")
