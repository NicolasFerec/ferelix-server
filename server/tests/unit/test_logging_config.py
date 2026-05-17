from app.services.logging_config import _schema_for_line, logs_config


def test_schema_for_line_extracts_visible_fields_and_message() -> None:
    line = "2026-05-17T22:58:12+0200 - transcode - app.services.transcoder - ERROR - FFmpeg failed"

    parsed = _schema_for_line(42, line)

    assert parsed.number == 42
    assert parsed.text == line
    assert parsed.message == "FFmpeg failed"
    assert parsed.timestamp == "2026-05-17T22:58:12+02:00"
    assert parsed.channel == "transcode"
    assert parsed.logger == "app.services.transcoder"
    assert parsed.level == "ERROR"


def test_schema_for_line_keeps_unparsed_line_as_message() -> None:
    parsed = _schema_for_line(1, "plain legacy log line")

    assert parsed.message == "plain legacy log line"
    assert parsed.channel is None
    assert parsed.level is None


def test_schema_for_line_keeps_legacy_timestamp_without_timezone() -> None:
    line = "2026-05-17 22:58:12,345 - transcode - app.services.transcoder - ERROR - FFmpeg failed"

    parsed = _schema_for_line(1, line)

    assert parsed.timestamp == "2026-05-17 22:58:12,345"


def test_logs_config_hides_debug_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FERELIX_FILE_LOG_LEVEL", raising=False)

    config = logs_config()

    assert config.file_level == "INFO"
    assert config.levels == ["INFO", "WARNING", "ERROR", "CRITICAL"]


def test_logs_config_includes_debug_when_file_level_is_debug(monkeypatch) -> None:
    monkeypatch.setenv("FERELIX_FILE_LOG_LEVEL", "DEBUG")

    config = logs_config()

    assert config.file_level == "DEBUG"
    assert config.levels == ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


def test_logs_config_exposes_bounded_rotation_settings(monkeypatch) -> None:
    monkeypatch.setenv("FERELIX_LOG_MAX_BYTES", "512")
    monkeypatch.setenv("FERELIX_LOG_BACKUP_COUNT", "0")

    config = logs_config()

    assert config.max_bytes == 1024
    assert config.backup_count == 1
