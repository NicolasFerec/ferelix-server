"""Add hardware transcoding setting

Revision ID: add_hardware_transcoding_setting
Revises: add_media_thumbnail_path
Create Date: 2026-05-17 00:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "add_hardware_transcoding_setting"
down_revision = "add_media_thumbnail_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if _settings_has_hardware_column():
        return

    op.add_column(
        "settings",
        sa.Column("hardware_transcoding_device", sa.String(), nullable=False, server_default="auto"),
    )
    op.alter_column("settings", "hardware_transcoding_device", server_default=None)


def downgrade() -> None:
    if _settings_has_hardware_column():
        op.drop_column("settings", "hardware_transcoding_device")


def _settings_has_hardware_column() -> bool:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return any(column["name"] == "hardware_transcoding_device" for column in inspector.get_columns("settings"))
