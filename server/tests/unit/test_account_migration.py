"""Account migrations audit collisions before making any destructive changes."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def load_migration(connection):
    path = Path(__file__).parents[2] / "alembic/versions/1770000007_account_credentials.py"
    spec = importlib.util.spec_from_file_location("account_migration", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    migration.__dict__["op"] = Operations(MigrationContext.configure(connection))
    return migration


def test_upgrade_preserves_accounts_and_enforces_normalized_uniqueness(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        connection.execute(
            text('CREATE TABLE "user" (id INTEGER PRIMARY KEY, username VARCHAR NOT NULL, email VARCHAR)')
        )
        connection.execute(text("INSERT INTO \"user\" VALUES (1, 'Straße', ' Reader@Example.com '), (2, 'other', '')"))
        load_migration(connection).upgrade()
        users = connection.execute(text('SELECT * FROM "user" ORDER BY id')).mappings().all()
        assert [user["id"] for user in users] == [1, 2]
        assert users[0]["username_normalized"] == "strasse"
        assert users[0]["email_normalized"] == "reader@example.com"
        assert users[1]["email_normalized"] is None
        assert all(user["credentials_version"] == 0 for user in users)
        with pytest.raises(IntegrityError):
            connection.execute(
                text("INSERT INTO \"user\" (id,username,username_normalized) VALUES (3,'STRASSE','strasse')")
            )
    engine.dispose()


@pytest.mark.parametrize("field", ["username", "email"])
def test_collisions_fail_before_ddl_without_deleting_accounts(tmp_path, field: str) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'collision.db'}")
    with engine.begin() as connection:
        connection.execute(
            text('CREATE TABLE "user" (id INTEGER PRIMARY KEY, username VARCHAR NOT NULL, email VARCHAR)')
        )
        connection.execute(text("INSERT INTO \"user\" VALUES (1,'reader','reader@example.com')"))
        connection.execute(
            text('INSERT INTO "user" VALUES (2,:username,:email)'),
            {
                "username": " READER " if field == "username" else "other",
                "email": " READER@example.com " if field == "email" else None,
            },
        )
        with pytest.raises(RuntimeError, match=f"{field}: user ids 1, 2"):
            load_migration(connection).upgrade()
        assert {column["name"] for column in inspect(connection).get_columns("user")} == {"id", "username", "email"}
        assert connection.scalar(text('SELECT COUNT(*) FROM "user"')) == 2
    engine.dispose()
