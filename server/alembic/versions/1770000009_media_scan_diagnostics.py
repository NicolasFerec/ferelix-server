"""Preserve successful metadata while recording failed probe attempts."""

import sqlalchemy as sa

from alembic import op

revision = "media_scan_diagnostics"
down_revision = "playback_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mediafile", sa.Column("last_scan_attempt_at", sa.DateTime(), nullable=True))
    op.add_column("mediafile", sa.Column("scan_error", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("mediafile", "scan_error")
    op.drop_column("mediafile", "last_scan_attempt_at")
