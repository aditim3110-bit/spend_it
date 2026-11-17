"""expense deleted_by

Revision ID: 682207f1b779
Revises: 14258473358b
Create Date: 2026-11-17 21:38:55.973099

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '682207f1b779'
down_revision: Union[str, Sequence[str], None] = '14258473358b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Record who soft-deleted an expense (PRD section 7)."""
    op.add_column('expenses', sa.Column('deleted_by', sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f('fk_expenses_deleted_by_users'), 'expenses', 'users', ['deleted_by'], ['id'])
    # No expense has been deleted yet in any environment, so this check can't fail.
    # Autogenerate never detects CHECK constraints, so it's added by hand.
    op.create_check_constraint(
        op.f('ck_expenses_deleted_fields_together'),
        'expenses',
        '(deleted_at IS NULL) = (deleted_by IS NULL)',
    )


def downgrade() -> None:
    op.drop_constraint(op.f('ck_expenses_deleted_fields_together'), 'expenses', type_='check')
    op.drop_constraint(op.f('fk_expenses_deleted_by_users'), 'expenses', type_='foreignkey')
    op.drop_column('expenses', 'deleted_by')
