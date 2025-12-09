"""
Add language field to user table
Create Date: 2025-01-10
"""

import sqlalchemy as sa

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "de7e724ff7d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add language column with default value 'en'
    op.add_column(
        "user",
        sa.Column("language", sa.String(), nullable=False, server_default="en"),
    )


def downgrade() -> None:
    # Remove language column
    op.drop_column("user", "language")
