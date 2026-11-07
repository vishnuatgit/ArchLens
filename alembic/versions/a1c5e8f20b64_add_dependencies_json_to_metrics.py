"""add dependencies_json to metrics

Revision ID: a1c5e8f20b64
Revises: 7d2f9c4e8a1b
Create Date: 2026-11-07 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c5e8f20b64"
down_revision: str | Sequence[str] | None = "7d2f9c4e8a1b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema. Nullable: reports stored earlier were never scanned."""
    op.add_column("metrics", sa.Column("dependencies_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("metrics", "dependencies_json")
