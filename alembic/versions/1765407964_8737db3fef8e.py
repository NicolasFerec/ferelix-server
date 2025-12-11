"""
Add soft delete to media files
Create Date: 2025-12-11 00:06:04.745419
"""

import sqlalchemy as sa

from alembic import op

revision = "8737db3fef8e"
down_revision = "885b2d7dd4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mediafile", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("mediafile", "deleted_at")
