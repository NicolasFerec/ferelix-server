"""Add playback sessions

Revision ID: add_playback_sessions
Revises: add_hardware_transcoding_setting
Create Date: 2026-05-17 00:00:01.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "add_playback_sessions"
down_revision = "add_hardware_transcoding_setting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _has_playback_session_table():
        return

    op.create_table(
        "playback_session",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.Integer(), nullable=False),
        sa.Column("transcoding_job_id", sa.String(), nullable=True),
        sa.Column("play_method", sa.String(), nullable=False),
        sa.Column("transcoding_type", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("stopped_reason", sa.String(), nullable=True),
        sa.Column("position_seconds", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("is_paused", sa.Boolean(), nullable=False),
        sa.Column("audio_stream_index", sa.Integer(), nullable=True),
        sa.Column("subtitle_stream_index", sa.Integer(), nullable=True),
        sa.Column("client_ip", sa.String(), nullable=True),
        sa.Column("user_agent", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("ended_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["media_file_id"], ["mediafile.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_playback_session_last_heartbeat_at"), "playback_session", ["last_heartbeat_at"])
    op.create_index(op.f("ix_playback_session_media_file_id"), "playback_session", ["media_file_id"])
    op.create_index(op.f("ix_playback_session_status"), "playback_session", ["status"])
    op.create_index(op.f("ix_playback_session_transcoding_job_id"), "playback_session", ["transcoding_job_id"])
    op.create_index(op.f("ix_playback_session_user_id"), "playback_session", ["user_id"])


def downgrade() -> None:
    if _has_playback_session_table():
        op.drop_table("playback_session")


def _has_playback_session_table() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return "playback_session" in inspector.get_table_names()
