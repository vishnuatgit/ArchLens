"""add repository_aliases for renamed repositories

Revision ID: 7d2f9c4e8a1b
Revises: 4c9e2a7d1b3f
Create Date: 2026-10-31 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d2f9c4e8a1b"
down_revision: str | Sequence[str] | None = "4c9e2a7d1b3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "repository_aliases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repository_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_repository_aliases_id"), "repository_aliases", ["id"], unique=False)
    op.create_index(op.f("ix_repository_aliases_url"), "repository_aliases", ["url"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_repository_aliases_url"), table_name="repository_aliases")
    op.drop_index(op.f("ix_repository_aliases_id"), table_name="repository_aliases")
    op.drop_table("repository_aliases")
