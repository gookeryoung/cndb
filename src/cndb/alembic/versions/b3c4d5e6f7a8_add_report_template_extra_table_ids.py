"""add_report_template_extra_table_ids — ReportTemplate 持久化额外引用表.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-20 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """ReportTemplate 新增 extra_table_ids JSON 列（额外引用表持久化，默认空列表）."""
    op.add_column(
        'reports_template',
        sa.Column('extra_table_ids', sa.JSON(), nullable=False, server_default='[]'),
    )


def downgrade() -> None:
    """降级：移除 extra_table_ids 列."""
    op.drop_column('reports_template', 'extra_table_ids')
