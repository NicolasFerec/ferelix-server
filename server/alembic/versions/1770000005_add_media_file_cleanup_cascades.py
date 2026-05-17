"""Add media file cleanup cascades

Revision ID: add_media_file_cleanup_cascades
Revises: add_user_delete_cascades
Create Date: 2026-05-17 00:00:05.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "add_media_file_cleanup_cascades"
down_revision = "add_user_delete_cascades"
branch_labels = None
depends_on = None


CASCADE_MEDIA_TABLES = ("audio_track", "video_track", "subtitle_track", "playback_session", "transcoding_job")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _rebuild_sqlite_tables(cascade=True)
        return

    for table_name in CASCADE_MEDIA_TABLES:
        if _has_table(table_name):
            _replace_media_fk(table_name, ondelete="CASCADE")

    if _has_table("media_view"):
        op.alter_column("media_view", "media_file_id", existing_type=sa.Integer(), nullable=True)
        _replace_media_fk("media_view", ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        _rebuild_sqlite_tables(cascade=False)
        return

    for table_name in CASCADE_MEDIA_TABLES:
        if _has_table(table_name):
            _replace_media_fk(table_name, ondelete=None)

    if _has_table("media_view"):
        op.execute(sa.text("DELETE FROM media_view WHERE media_file_id IS NULL"))
        _replace_media_fk("media_view", ondelete=None)
        op.alter_column("media_view", "media_file_id", existing_type=sa.Integer(), nullable=False)


def _replace_media_fk(table_name: str, *, ondelete: str | None) -> None:
    constraint_name = _find_media_fk_name(table_name)
    if constraint_name:
        op.drop_constraint(constraint_name, table_name, type_="foreignkey")

    op.create_foreign_key(
        f"fk_{table_name}_media_file_id_mediafile",
        table_name,
        "mediafile",
        ["media_file_id"],
        ["id"],
        ondelete=ondelete,
    )


def _find_media_fk_name(table_name: str) -> str | None:
    inspector = sa.inspect(op.get_bind())
    for foreign_key in inspector.get_foreign_keys(table_name):
        if foreign_key["constrained_columns"] == ["media_file_id"] and foreign_key["referred_table"] == "mediafile":
            return foreign_key["name"]
    return None


def _rebuild_sqlite_tables(*, cascade: bool) -> None:
    if _has_table("audio_track"):
        op.execute(sa.text("DELETE FROM audio_track WHERE media_file_id NOT IN (SELECT id FROM mediafile)"))
        _rebuild_sqlite_audio_track(cascade=cascade)
    if _has_table("video_track"):
        op.execute(sa.text("DELETE FROM video_track WHERE media_file_id NOT IN (SELECT id FROM mediafile)"))
        _rebuild_sqlite_video_track(cascade=cascade)
    if _has_table("subtitle_track"):
        op.execute(sa.text("DELETE FROM subtitle_track WHERE media_file_id NOT IN (SELECT id FROM mediafile)"))
        _rebuild_sqlite_subtitle_track(cascade=cascade)
    if _has_table("playback_session"):
        op.execute(sa.text("DELETE FROM playback_session WHERE media_file_id NOT IN (SELECT id FROM mediafile)"))
        _rebuild_sqlite_playback_session(cascade=cascade)
    if _has_table("transcoding_job"):
        op.execute(sa.text("DELETE FROM transcoding_job WHERE media_file_id NOT IN (SELECT id FROM mediafile)"))
        _rebuild_sqlite_transcoding_job(cascade=cascade)
    if _has_table("media_view"):
        if not cascade:
            op.execute(sa.text("DELETE FROM media_view WHERE media_file_id IS NULL"))
            op.execute(sa.text("DELETE FROM media_view WHERE media_file_id NOT IN (SELECT id FROM mediafile)"))
        _rebuild_sqlite_media_view(cascade=cascade)


def _media_fk_sql(ondelete: str | None) -> str:
    suffix = f" ON DELETE {ondelete}" if ondelete else ""
    return f"FOREIGN KEY(media_file_id) REFERENCES mediafile (id){suffix}"


def _rebuild_sqlite_audio_track(*, cascade: bool) -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS audio_track_new"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE audio_track_new (
                id INTEGER NOT NULL,
                media_file_id INTEGER NOT NULL,
                stream_index INTEGER NOT NULL,
                codec VARCHAR NOT NULL,
                language VARCHAR,
                title VARCHAR,
                channels INTEGER,
                bitrate INTEGER,
                is_default BOOLEAN NOT NULL,
                sample_rate INTEGER,
                PRIMARY KEY (id),
                {_media_fk_sql("CASCADE" if cascade else None)}
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO audio_track_new (
                id, media_file_id, stream_index, codec, language, title,
                channels, bitrate, is_default, sample_rate
            )
            SELECT
                id, media_file_id, stream_index, codec, language, title,
                channels, bitrate, is_default, sample_rate
            FROM audio_track
            """
        )
    )
    op.execute(sa.text("DROP TABLE audio_track"))
    op.execute(sa.text("ALTER TABLE audio_track_new RENAME TO audio_track"))


def _rebuild_sqlite_video_track(*, cascade: bool) -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS video_track_new"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE video_track_new (
                id INTEGER NOT NULL,
                media_file_id INTEGER NOT NULL,
                stream_index INTEGER NOT NULL,
                codec VARCHAR NOT NULL,
                width INTEGER,
                height INTEGER,
                bitrate INTEGER,
                fps FLOAT,
                language VARCHAR,
                title VARCHAR,
                is_default BOOLEAN NOT NULL,
                profile VARCHAR,
                level VARCHAR,
                pixel_format VARCHAR,
                bit_depth INTEGER,
                color_range VARCHAR,
                color_space VARCHAR,
                color_primaries VARCHAR,
                color_transfer VARCHAR,
                max_luminance INTEGER,
                min_luminance FLOAT,
                max_cll INTEGER,
                max_fall INTEGER,
                PRIMARY KEY (id),
                {_media_fk_sql("CASCADE" if cascade else None)}
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO video_track_new (
                id, media_file_id, stream_index, codec, width, height, bitrate,
                fps, language, title, is_default, profile, level, pixel_format,
                bit_depth, color_range, color_space, color_primaries,
                color_transfer, max_luminance, min_luminance, max_cll, max_fall
            )
            SELECT
                id, media_file_id, stream_index, codec, width, height, bitrate,
                fps, language, title, is_default, profile, level, pixel_format,
                bit_depth, color_range, color_space, color_primaries,
                color_transfer, max_luminance, min_luminance, max_cll, max_fall
            FROM video_track
            """
        )
    )
    op.execute(sa.text("DROP TABLE video_track"))
    op.execute(sa.text("ALTER TABLE video_track_new RENAME TO video_track"))


def _rebuild_sqlite_subtitle_track(*, cascade: bool) -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS subtitle_track_new"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE subtitle_track_new (
                id INTEGER NOT NULL,
                media_file_id INTEGER NOT NULL,
                stream_index INTEGER NOT NULL,
                codec VARCHAR NOT NULL,
                language VARCHAR,
                title VARCHAR,
                is_forced BOOLEAN NOT NULL,
                is_default BOOLEAN NOT NULL,
                PRIMARY KEY (id),
                {_media_fk_sql("CASCADE" if cascade else None)}
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO subtitle_track_new (
                id, media_file_id, stream_index, codec, language, title,
                is_forced, is_default
            )
            SELECT
                id, media_file_id, stream_index, codec, language, title,
                is_forced, is_default
            FROM subtitle_track
            """
        )
    )
    op.execute(sa.text("DROP TABLE subtitle_track"))
    op.execute(sa.text("ALTER TABLE subtitle_track_new RENAME TO subtitle_track"))


def _rebuild_sqlite_playback_session(*, cascade: bool) -> None:
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
                FOREIGN KEY(user_id) REFERENCES "user" (id) ON DELETE CASCADE,
                {_media_fk_sql("CASCADE" if cascade else None)}
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


def _rebuild_sqlite_transcoding_job(*, cascade: bool) -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS transcoding_job_new"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE transcoding_job_new (
                id VARCHAR NOT NULL,
                media_file_id INTEGER NOT NULL,
                type VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                video_codec VARCHAR,
                audio_codec VARCHAR,
                video_bitrate INTEGER,
                audio_bitrate INTEGER,
                max_width INTEGER,
                max_height INTEGER,
                start_time FLOAT,
                output_path VARCHAR,
                playlist_path VARCHAR,
                progress_percent FLOAT,
                transcoded_duration FLOAT,
                current_fps FLOAT,
                current_bitrate INTEGER,
                process_id INTEGER,
                ffmpeg_command TEXT,
                error_message TEXT,
                retry_count INTEGER NOT NULL,
                session_id VARCHAR,
                client_ip VARCHAR,
                user_agent VARCHAR,
                created_at DATETIME NOT NULL,
                started_at DATETIME,
                completed_at DATETIME,
                last_accessed_at DATETIME NOT NULL,
                auto_cleanup BOOLEAN NOT NULL,
                keep_segments BOOLEAN NOT NULL,
                PRIMARY KEY (id),
                {_media_fk_sql("CASCADE" if cascade else None)}
            )
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO transcoding_job_new (
                id, media_file_id, type, status, video_codec, audio_codec,
                video_bitrate, audio_bitrate, max_width, max_height, start_time,
                output_path, playlist_path, progress_percent,
                transcoded_duration, current_fps, current_bitrate, process_id,
                ffmpeg_command, error_message, retry_count, session_id,
                client_ip, user_agent, created_at, started_at, completed_at,
                last_accessed_at, auto_cleanup, keep_segments
            )
            SELECT
                id, media_file_id, type, status, video_codec, audio_codec,
                video_bitrate, audio_bitrate, max_width, max_height, start_time,
                output_path, playlist_path, progress_percent,
                transcoded_duration, current_fps, current_bitrate, process_id,
                ffmpeg_command, error_message, retry_count, session_id,
                client_ip, user_agent, created_at, started_at, completed_at,
                last_accessed_at, auto_cleanup, keep_segments
            FROM transcoding_job
            """
        )
    )
    op.execute(sa.text("DROP TABLE transcoding_job"))
    op.execute(sa.text("ALTER TABLE transcoding_job_new RENAME TO transcoding_job"))
    op.execute(sa.text("CREATE INDEX ix_transcoding_job_media_file_id ON transcoding_job (media_file_id)"))
    op.execute(sa.text("CREATE INDEX ix_transcoding_job_session_id ON transcoding_job (session_id)"))


def _rebuild_sqlite_media_view(*, cascade: bool) -> None:
    media_file_column = "media_file_id INTEGER" if cascade else "media_file_id INTEGER NOT NULL"
    media_fk = _media_fk_sql("SET NULL" if cascade else None)
    media_id_select = (
        "CASE WHEN EXISTS (SELECT 1 FROM mediafile WHERE mediafile.id = media_view.media_file_id) "
        "THEN media_file_id ELSE NULL END"
        if cascade
        else "media_file_id"
    )

    op.execute(sa.text("DROP TABLE IF EXISTS media_view_new"))
    op.execute(
        sa.text(
            f"""
            CREATE TABLE media_view_new (
                id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                {media_file_column},
                position_seconds FLOAT NOT NULL,
                duration_seconds FLOAT,
                watched BOOLEAN NOT NULL,
                play_count INTEGER NOT NULL,
                first_viewed_at DATETIME NOT NULL,
                last_viewed_at DATETIME NOT NULL,
                completed_at DATETIME,
                PRIMARY KEY (id),
                FOREIGN KEY(user_id) REFERENCES "user" (id) ON DELETE CASCADE,
                {media_fk},
                CONSTRAINT uq_media_view_user_media UNIQUE (user_id, media_file_id)
            )
            """
        )
    )
    op.execute(
        sa.text(
            f"""
            INSERT INTO media_view_new (
                id, user_id, media_file_id, position_seconds, duration_seconds,
                watched, play_count, first_viewed_at, last_viewed_at, completed_at
            )
            SELECT
                id, user_id, {media_id_select}, position_seconds, duration_seconds,
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
