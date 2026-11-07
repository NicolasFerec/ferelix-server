"""Add a personal watchlist with concurrent-safe unique membership."""

import sqlalchemy as sa

from alembic import op

revision = "watchlist"
down_revision = "media_scan_diagnostics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("media_file_id", sa.Integer(), sa.ForeignKey("mediafile.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "media_file_id", name="uq_watchlist_user_media"),
    )
    op.create_index("ix_watchlist_media_file_id", "watchlist", ["media_file_id"])


def downgrade() -> None:
    op.drop_table("watchlist")
