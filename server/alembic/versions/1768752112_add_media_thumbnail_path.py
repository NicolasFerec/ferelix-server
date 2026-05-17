"""
Add media thumbnail path
Create Date: 2026-05-17 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "add_media_thumbnail_path"
down_revision = "8cf3d900d225"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mediafile", sa.Column("thumbnail_path", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("mediafile", "thumbnail_path")
