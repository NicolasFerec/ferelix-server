"""Add user profile images

Revision ID: add_user_profile_images
Revises: add_media_views
Create Date: 2026-05-17 00:00:03.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "add_user_profile_images"
down_revision = "add_media_views"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _has_column("user", "profile_image_path"):
        return

    op.add_column("user", sa.Column("profile_image_path", sa.String(), nullable=True))


def downgrade() -> None:
    if _has_column("user", "profile_image_path"):
        op.drop_column("user", "profile_image_path")


def _has_column(table_name: str, column_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))
