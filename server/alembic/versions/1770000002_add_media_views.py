"""Add per-user media views

Revision ID: add_media_views
Revises: add_playback_sessions
Create Date: 2026-05-17 00:00:02.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "add_media_views"
down_revision = "add_playback_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _has_media_view_table():
        return

    op.create_table(
        "media_view",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("media_file_id", sa.Integer(), nullable=True),
        sa.Column("position_seconds", sa.Float(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("watched", sa.Boolean(), nullable=False),
        sa.Column("play_count", sa.Integer(), nullable=False),
        sa.Column("first_viewed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_viewed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["media_file_id"], ["mediafile.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "media_file_id", name="uq_media_view_user_media"),
    )
    op.create_index(op.f("ix_media_view_media_file_id"), "media_view", ["media_file_id"])
    op.create_index(op.f("ix_media_view_user_id"), "media_view", ["user_id"])
    op.create_index(op.f("ix_media_view_watched"), "media_view", ["watched"])
    op.create_index(op.f("ix_media_view_last_viewed_at"), "media_view", ["last_viewed_at"])


def downgrade() -> None:
    if _has_media_view_table():
        op.drop_table("media_view")


def _has_media_view_table() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return "media_view" in inspector.get_table_names()
