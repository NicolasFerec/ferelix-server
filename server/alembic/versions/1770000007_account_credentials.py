"""Version credentials and enforce normalized account identities.

Revision ID: account_credentials
Revises: add_media_file_modified_at
"""

from collections import defaultdict

import sqlalchemy as sa

from alembic import op

revision = "account_credentials"
down_revision = "add_media_file_modified_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text('SELECT id, username, email FROM "user"')).mappings().all()
    identities = {field: defaultdict(list) for field in ("username", "email")}
    for row in rows:
        for field in identities:
            normalized = (row[field] or "").strip().casefold()
            if normalized:
                identities[field][normalized].append(row["id"])
            elif field == "username":
                raise RuntimeError(f"Account migration requires a non-empty username for user id {row['id']}")
    collisions = [
        f"{field}: user ids {', '.join(map(str, ids))}"
        for field, values in identities.items()
        for ids in values.values()
        if len(ids) > 1
    ]
    if collisions:
        # Audit before DDL: preserve all accounts and ask for deliberate repairs.
        raise RuntimeError(
            "Normalized account identity collisions; rename accounts before migrating: " + "; ".join(collisions)
        )

    op.add_column("user", sa.Column("credentials_version", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("user", sa.Column("username_normalized", sa.String(), nullable=True))
    op.add_column("user", sa.Column("email_normalized", sa.String(), nullable=True))
    for row in rows:
        connection.execute(
            sa.text('UPDATE "user" SET username_normalized = :username, email_normalized = :email WHERE id = :id'),
            {
                "id": row["id"],
                "username": row["username"].strip().casefold(),
                "email": row["email"].strip().casefold() if row["email"] and row["email"].strip() else None,
            },
        )
    with op.batch_alter_table("user") as batch:
        batch.alter_column("username_normalized", existing_type=sa.String(), nullable=False)
        batch.create_unique_constraint("uq_user_username_normalized", ["username_normalized"])
        batch.create_unique_constraint("uq_user_email_normalized", ["email_normalized"])


def downgrade() -> None:
    with op.batch_alter_table("user") as batch:
        batch.drop_constraint("uq_user_username_normalized", type_="unique")
        batch.drop_constraint("uq_user_email_normalized", type_="unique")
        batch.drop_column("username_normalized")
        batch.drop_column("email_normalized")
        batch.drop_column("credentials_version")
