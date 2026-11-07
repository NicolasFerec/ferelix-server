"""Bind media access and encoder regulation to owned playback sessions."""

import sqlalchemy as sa

from alembic import op

revision = "playback_access"
down_revision = "account_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "playback_session", sa.Column("playback_generation", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("transcoding_job", sa.Column("playback_generation", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("video_track", sa.Column("codec_tag", sa.String(), nullable=True))
    op.add_column("playback_session", sa.Column("media_token_hash", sa.String(), nullable=True))
    op.add_column(
        "playback_session", sa.Column("credentials_version", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("playback_session", sa.Column("video_stream_index", sa.Integer(), nullable=True))
    op.add_column("transcoding_job", sa.Column("video_stream_index", sa.Integer(), nullable=True))
    op.add_column("transcoding_job", sa.Column("is_throttled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("transcoding_job", sa.Column("encoded_ahead_seconds", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("transcoding_job", "playback_generation")
    op.drop_column("playback_session", "playback_generation")
    op.drop_column("video_track", "codec_tag")
    op.drop_column("transcoding_job", "encoded_ahead_seconds")
    op.drop_column("transcoding_job", "is_throttled")
    op.drop_column("transcoding_job", "video_stream_index")
    op.drop_column("playback_session", "video_stream_index")
    op.drop_column("playback_session", "credentials_version")
    op.drop_column("playback_session", "media_token_hash")
