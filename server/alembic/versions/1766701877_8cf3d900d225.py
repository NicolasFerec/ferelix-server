"""
Add start_time column to transcoding_job table
Create Date: 2025-12-25 23:31:17.254630
"""

import sqlalchemy as sa

from alembic import op

revision = "8cf3d900d225"
down_revision = "6e8907acad12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("transcoding_job", sa.Column("start_time", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("transcoding_job", "start_time")
