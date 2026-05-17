"""Add media file modified timestamp

Revision ID: add_media_file_modified_at
Revises: add_media_file_cleanup_cascades
Create Date: 2026-05-18 00:00:06.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "add_media_file_modified_at"
down_revision = "add_media_file_cleanup_cascades"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mediafile", sa.Column("file_modified_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("mediafile", "file_modified_at")
