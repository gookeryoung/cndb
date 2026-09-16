"""add_wechat_accounts_table — 微信账号与 User 的绑定关系表.

Revision ID: c7e8f9a0b1c2
Revises: 6955718a847b
Create Date: 2026-09-15 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7e8f9a0b1c2'
down_revision: Union[str, Sequence[str], None] = '6955718a847b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建 wechat_accounts 表.

    - openid 唯一索引：一个微信身份只对应一个 cndb 用户
    - unionid 普通索引：用于多端统一身份查询
    - user_id 外键关联 accounts_user，级联删除
    """
    op.create_table(
        'wechat_accounts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('openid', sa.String(length=64), nullable=False),
        sa.Column('unionid', sa.String(length=64), nullable=True),
        sa.Column('session_key', sa.String(length=128), nullable=True),
        sa.Column(
            'user_id',
            sa.Integer(),
            sa.ForeignKey('accounts_user.id', ondelete='CASCADE'),
            nullable=False,
        ),
        sa.Column('nickname', sa.String(length=128), nullable=True),
        sa.Column('avatar_url', sa.String(length=512), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('openid', name='ix_wechat_openid'),
    )
    op.create_index('ix_wechat_unionid', 'wechat_accounts', ['unionid'])
    op.create_index('ix_wechat_user_id', 'wechat_accounts', ['user_id'])


def downgrade() -> None:
    """降级：删除 wechat_accounts 表."""
    op.drop_index('ix_wechat_user_id', table_name='wechat_accounts')
    op.drop_index('ix_wechat_unionid', table_name='wechat_accounts')
    op.drop_table('wechat_accounts')
