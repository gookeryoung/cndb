"""add_datafield_hidden — DataField 表新增 hidden 字段.

Revision ID: 949b0d8ddf3f
Revises: 62817ea574fa
Create Date: 2026-09-12 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '949b0d8ddf3f'
down_revision: Union[str, Sequence[str], None] = '62817ea574fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: tables_datafield 加 hidden 列."""
    op.add_column(
        'tables_datafield',
        sa.Column('hidden', sa.Boolean(), nullable=False, server_default=sa.text('0'), default=False),
    )
    # SQLite 的 ALTER TABLE ADD COLUMN 不支持 server_default 回写存量，手动补 0
    op.execute(sa.text("UPDATE tables_datafield SET hidden = 0 WHERE hidden IS NULL"))


def downgrade() -> None:
    """Downgrade schema: 移除 hidden 列."""
    op.drop_column('tables_datafield', 'hidden')
