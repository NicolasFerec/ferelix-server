"""
Add settings model for job configuration
Create Date: 2025-12-13 17:21:32.314715
"""

import sqlalchemy as sa

from alembic import op

revision = "d358779480a3"
down_revision = "59733aa5d4c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "library_scan_interval_minutes",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
        sa.Column(
            "cleanup_schedule_hour", sa.Integer(), nullable=False, server_default="3"
        ),
        sa.Column(
            "cleanup_schedule_minute", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "cleanup_grace_period_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    # Insert default settings record
    op.execute(
        "INSERT INTO settings (id, library_scan_interval_minutes, cleanup_schedule_hour, cleanup_schedule_minute, cleanup_grace_period_days) VALUES (1, 120, 3, 0, 30)"
    )


def downgrade() -> None:
    op.drop_table("settings")
