"""friend source phone_email

Revision ID: 14258473358b
Revises: f37543949eea
Create Date: 2026-11-17 19:00:27.599637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '14258473358b'
down_revision: Union[str, Sequence[str], None] = 'f37543949eea'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


OLD = "('qr', 'nearby', 'contacts', 'expense')"
NEW = "('qr', 'phone_email', 'nearby', 'contacts', 'expense')"


def _replace_check(values: str) -> None:
    # Enums are stored as text + CHECK (see app/models/base.py:text_enum), so adding a
    # value means swapping the CHECK constraint.
    op.drop_constraint(op.f("ck_friendships_friend_source"), "friendships", type_="check")
    op.create_check_constraint(
        op.f("ck_friendships_friend_source"), "friendships", f"source IN {values}"
    )


def upgrade() -> None:
    """Allow friendships created by typing a phone number or email."""
    _replace_check(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM friendships WHERE source = 'phone_email'")
    _replace_check(OLD)
