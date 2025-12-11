"""
Add name field to library
Create Date: 2025-12-11 00:32:45.448840
"""

import sqlalchemy as sa

from alembic import op

revision = "1fa8c503c08f"
down_revision = "8737db3fef8e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("library", sa.Column("name", sa.String(), nullable=True))
    op.execute("UPDATE library SET name = path WHERE name IS NULL")

    with op.batch_alter_table("library", schema=None) as batch_op:
        batch_op.alter_column("name", nullable=False)


def downgrade() -> None:
    op.drop_column("library", "name")
