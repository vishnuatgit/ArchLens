"""add is_example to analyses

Revision ID: 4c9e2a7d1b3f
Revises: ff3b1ee28354
Create Date: 2026-10-31 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c9e2a7d1b3f"
down_revision: str | Sequence[str] | None = "ff3b1ee28354"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "analyses",
        sa.Column("is_example", sa.Boolean(), server_default=sa.false(), nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.drop_column("is_example")
