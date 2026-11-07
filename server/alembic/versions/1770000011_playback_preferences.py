"""Persist initial playback preferences without changing existing defaults."""

import sqlalchemy as sa

from alembic import op

revision = "playback_preferences"
down_revision = "watchlist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("user", sa.Column("preferred_audio_language", sa.String(), nullable=True))
    op.add_column("user", sa.Column("preferred_subtitle_language", sa.String(), nullable=True))
    op.add_column("user", sa.Column("subtitle_mode", sa.String(), nullable=False, server_default="off"))


def downgrade() -> None:
    op.drop_column("user", "subtitle_mode")
    op.drop_column("user", "preferred_subtitle_language")
    op.drop_column("user", "preferred_audio_language")
