"""
Add recommendation_row
Create Date: 2025-12-12 23:41:49.355267
"""

import sqlalchemy as sa

from alembic import op

revision = "59733aa5d4c2"
down_revision = "1fa8c503c08f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "recommendation_row",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("library_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("filter_criteria", sa.JSON(), nullable=False),
        sa.Column("visible_on_homepage", sa.Boolean(), nullable=False),
        sa.Column("visible_on_recommend", sa.Boolean(), nullable=False),
        sa.Column("is_special", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["library_id"],
            ["library.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("recommendation_row")
