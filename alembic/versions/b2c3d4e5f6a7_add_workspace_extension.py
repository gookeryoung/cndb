"""add_workspace_extension — Workspace 表新增 visibility/tags/allow_edit.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-09-13 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: workspaces_workspace 加 visibility/tags/allow_edit."""
    # visibility 枚举
    op.add_column(
        'workspaces_workspace',
        sa.Column(
            'visibility',
            sa.Enum('public', 'member', 'private', name='workspacevisibility'),
            nullable=False,
            server_default='member',
        ),
    )
    # tags JSON 数组
    op.add_column(
        'workspaces_workspace',
        sa.Column(
            'tags',
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )
    # allow_edit 布尔
    op.add_column(
        'workspaces_workspace',
        sa.Column(
            'allow_edit',
            sa.Boolean(),
            nullable=False,
            server_default=sa.text('1'),
        ),
    )


def downgrade() -> None:
    """Downgrade schema: 移除 visibility/tags/allow_edit 列."""
    op.drop_column('workspaces_workspace', 'allow_edit')
    op.drop_column('workspaces_workspace', 'tags')
    op.drop_column('workspaces_workspace', 'visibility')
