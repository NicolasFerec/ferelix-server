"""Add user delete cascades

Revision ID: add_user_delete_cascades
Revises: add_user_profile_images
Create Date: 2026-05-17 00:00:04.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "add_user_delete_cascades"
down_revision = "add_user_profile_images"
branch_labels = None
depends_on = None


USER_DEPENDENT_TABLES = ("refresh_token", "playback_session", "media_view")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _rebuild_sqlite_tables(cascade=True)
        return

    for table_name in USER_DEPENDENT_TABLES:
        if _has_table(table_name):
            _replace_user_fk(table_name, cascade=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _rebuild_sqlite_tables(cascade=False)
        return

    for table_name in USER_DEPENDENT_TABLES:
        if _has_table(table_name):
            _replace_user_fk(table_name, cascade=False)


def _replace_user_fk(table_name: str, *, cascade: bool) -> None:
    constraint_name = _find_user_fk_name(table_name)
    if constraint_name:
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")

    op.create_foreign_key(
        f"fk_{table_name}_user_id_user",
        table_name,
        "user",
        ["user_id"],
        ["id"],
        ondelete="CASCADE" if cascade else None,
    )


def _find_user_fk_name(table_name: str) -> str | None:
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(table_name):
        if foreign_key["constrained_columns"] == ["user_id"] and foreign_key["referred_table"] == "user":
            return foreign_key["name"]
    return None


def _rebuild_sqlite_tables(*, cascade: bool) -> None:
    if _has_table("refresh_token"):
        op.execute(sa.text('DELETE FROM refresh_token WHERE user_id NOT IN (SELECT id FROM "user")'))
        _rebuild_sqlite_refresh_token(cascade=cascade)
    if _has_table("playback_session"):
        op.execute(sa.text('DELETE FROM playback_session WHERE user_id NOT IN (SELECT id FROM "user")'))
        op.execute(sa.text("DELETE FROM playback_session WHERE media_file_id NOT IN (SELECT id FROM mediafile)"))
        _rebuild_sqlite_playback_session(cascade=cascade)
    if _has_table("media_view"):
        op.execute(sa.text('DELETE FROM media_view WHERE user_id NOT IN (SELECT id FROM "user")'))
        op.execute(sa.text("DELETE FROM media_view WHERE media_file_id NOT IN (SELECT id FROM mediafile)"))
        _rebuild_sqlite_media_view(cascade=cascade)


def _rebuild_sqlite_refresh_token(*, cascade: bool) -> None:
    ondelete = " ON DELETE CASCADE" if cascade else ""
    op.execute(sa.text("DROP TABLE IF EXISTS refresh_token_new"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE refresh_token_new (
                id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                token VARCHAR NOT NULL,
                expires_at DATETIME NOT NULL,
                created_at DATETIME NOT NULL,
                last_used_at DATETIME,
                device_info VARCHAR,
                PRIMARY KEY (id),
                FOREIGN KEY(user_id) REFERENCES "user" (id){ondelete}
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO refresh_token_new (
                id, user_id, token, expires_at, created_at, last_used_at, device_info
            )
            SELECT id, user_id, token, expires_at, created_at, last_used_at, device_info
            FROM refresh_token
            """
        )
    )
    op.execute(sa.text("DROP TABLE refresh_token"))
    op.execute(sa.text("ALTER TABLE refresh_token_new RENAME TO refresh_token"))
    op.execute(sa.text("CREATE UNIQUE INDEX ix_refresh_token_token ON refresh_token (token)"))


def _rebuild_sqlite_playback_session(*, cascade: bool) -> None:
    ondelete = " ON DELETE CASCADE" if cascade else ""
    op.execute(sa.text("DROP TABLE IF EXISTS playback_session_new"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE playback_session_new (
                id VARCHAR NOT NULL,
                user_id INTEGER NOT NULL,
                media_file_id INTEGER NOT NULL,
                transcoding_job_id VARCHAR,
                play_method VARCHAR NOT NULL,
                transcoding_type VARCHAR,
                status VARCHAR NOT NULL,
                stopped_reason VARCHAR,
                position_seconds FLOAT NOT NULL,
                duration_seconds FLOAT,
                is_paused BOOLEAN NOT NULL,
                audio_stream_index INTEGER,
                subtitle_stream_index INTEGER,
                client_ip VARCHAR,
                user_agent VARCHAR,
                started_at DATETIME NOT NULL,
                last_heartbeat_at DATETIME NOT NULL,
                ended_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(media_file_id) REFERENCES mediafile (id),
                FOREIGN KEY(user_id) REFERENCES "user" (id){ondelete}
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO playback_session_new (
                id, user_id, media_file_id, transcoding_job_id, play_method,
                transcoding_type, status, stopped_reason, position_seconds,
                duration_seconds, is_paused, audio_stream_index,
                subtitle_stream_index, client_ip, user_agent, started_at,
                last_heartbeat_at, ended_at
            )
            SELECT
                id, user_id, media_file_id, transcoding_job_id, play_method,
                transcoding_type, status, stopped_reason, position_seconds,
                duration_seconds, is_paused, audio_stream_index,
                subtitle_stream_index, client_ip, user_agent, started_at,
                last_heartbeat_at, ended_at
            FROM playback_session
            """
        )
    )
    op.execute(sa.text("DROP TABLE playback_session"))
    op.execute(sa.text("ALTER TABLE playback_session_new RENAME TO playback_session"))
    op.execute(sa.text("CREATE INDEX ix_playback_session_last_heartbeat_at ON playback_session (last_heartbeat_at)"))
    op.execute(sa.text("CREATE INDEX ix_playback_session_media_file_id ON playback_session (media_file_id)"))
    op.execute(sa.text("CREATE INDEX ix_playback_session_status ON playback_session (status)"))
    op.execute(sa.text("CREATE INDEX ix_playback_session_transcoding_job_id ON playback_session (transcoding_job_id)"))
    op.execute(sa.text("CREATE INDEX ix_playback_session_user_id ON playback_session (user_id)"))


def _rebuild_sqlite_media_view(*, cascade: bool) -> None:
    ondelete = " ON DELETE CASCADE" if cascade else ""
    op.execute(sa.text("DROP TABLE IF EXISTS media_view_new"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE media_view_new (
                id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                media_file_id INTEGER NOT NULL,
                position_seconds FLOAT NOT NULL,
                duration_seconds FLOAT,
                watched BOOLEAN NOT NULL,
                play_count INTEGER NOT NULL,
                first_viewed_at DATETIME NOT NULL,
                last_viewed_at DATETIME NOT NULL,
                completed_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(media_file_id) REFERENCES mediafile (id),
                FOREIGN KEY(user_id) REFERENCES "user" (id){ondelete},
                CONSTRAINT uq_media_view_user_media UNIQUE (user_id, media_file_id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO media_view_new (
                id, user_id, media_file_id, position_seconds, duration_seconds,
                watched, play_count, first_viewed_at, last_viewed_at, completed_at
            )
            SELECT
                id, user_id, media_file_id, position_seconds, duration_seconds,
                watched, play_count, first_viewed_at, last_viewed_at, completed_at
            FROM media_view
            """
        )
    )
    op.execute(sa.text("DROP TABLE media_view"))
    op.execute(sa.text("ALTER TABLE media_view_new RENAME TO media_view"))
    op.execute(sa.text("CREATE INDEX ix_media_view_last_viewed_at ON media_view (last_viewed_at)"))
    op.execute(sa.text("CREATE INDEX ix_media_view_media_file_id ON media_view (media_file_id)"))
    op.execute(sa.text("CREATE INDEX ix_media_view_user_id ON media_view (user_id)"))
    op.execute(sa.text("CREATE INDEX ix_media_view_watched ON media_view (watched)"))


def _has_table(table_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return table_name in inspector.get_table_names()
