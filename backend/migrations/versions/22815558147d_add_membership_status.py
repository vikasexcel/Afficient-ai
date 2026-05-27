"""add membership status

Revision ID: 22815558147d
Revises: 58012be49379
Create Date: 2026-05-27 14:50:25.416207

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '22815558147d'
down_revision: Union[str, Sequence[str], None] = '58012be49379'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


status_enum = sa.Enum('active', 'pending', name='membership_status')


def upgrade() -> None:
    status_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        'memberships',
        sa.Column(
            'status',
            status_enum,
            server_default='active',
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column('memberships', 'status')
    status_enum.drop(op.get_bind(), checkfirst=True)
