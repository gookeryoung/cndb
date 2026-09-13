"""add_user_preferences — User 表新增 preferences JSON 列.

Revision ID: a1b2c3d4e5f6
Revises: 949b0d8ddf3f
Create Date: 2026-09-13 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '949b0d8ddf3f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: accounts_user 加 preferences JSON 列."""
    op.add_column(
        'accounts_user',
        sa.Column(
            'preferences',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{\"active_views\":{}}'"),
        ),
    )


def downgrade() -> None:
    """Downgrade schema: 移除 preferences 列."""
    op.drop_column('accounts_user', 'preferences')
