"""Application logging setup and dashboard log readers."""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from pydantic import BaseModel

LOG_FORMAT = "%(asctime)s - %(channel)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"
LOG_FILE_NAME = "ferelix.log"
DEFAULT_MAX_LOG_BYTES = 2 * 1024 * 1024
DEFAULT_LOG_BACKUP_COUNT = 4
DEFAULT_CONSOLE_LOG_LEVEL = "INFO"
DEFAULT_FILE_LOG_LEVEL = "INFO"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class LogLineSchema(BaseModel):
    """One server log line exposed to admins."""

    number: int
    text: str
    message: str
    channel: str | None = None
    logger: str | None = None
    level: str | None = None
    timestamp: str | None = None


class LogsResponse(BaseModel):
    """Server logs response."""

    lines: list[LogLineSchema]
    next_offset: int
    truncated: bool = False
    path: str


class LogsConfigResponse(BaseModel):
    """Server logs dashboard configuration."""

    levels: list[str]
    file_level: str
    max_bytes: int
    backup_count: int


class LoggingChannelFilter(logging.Filter):
    """Attach a stable dashboard channel to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.channel = channel_for_logger(record.name)
        return True


def configure_logging() -> None:
    """Configure console and persistent file logging once."""
    root_logger = logging.getLogger()

    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    channel_filter = LoggingChannelFilter()
    console_level = _log_level_from_env("FERELIX_LOG_LEVEL", DEFAULT_CONSOLE_LOG_LEVEL)
    file_level = _log_level_from_env("FERELIX_FILE_LOG_LEVEL", DEFAULT_FILE_LOG_LEVEL)
    max_log_bytes = _int_from_env("FERELIX_LOG_MAX_BYTES", DEFAULT_MAX_LOG_BYTES, minimum=1024)
    backup_count = _int_from_env("FERELIX_LOG_BACKUP_COUNT", DEFAULT_LOG_BACKUP_COUNT, minimum=1)
    root_logger.setLevel(min(console_level, file_level))

    for handler in root_logger.handlers:
        handler.addFilter(channel_filter)
        handler.setFormatter(formatter)
        if isinstance(handler, RotatingFileHandler):
            handler.setLevel(file_level)
            handler.maxBytes = max_log_bytes
            handler.backupCount = backup_count
        elif isinstance(handler, logging.StreamHandler):
            handler.setLevel(console_level)

    if not any(isinstance(handler, logging.StreamHandler) and not isinstance(handler, RotatingFileHandler) for handler in root_logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(console_level)
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(channel_filter)
        root_logger.addHandler(stream_handler)

    log_path = get_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if not any(isinstance(handler, RotatingFileHandler) and Path(handler.baseFilename) == log_path for handler in root_logger.handlers):
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_log_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(file_level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(channel_filter)
        root_logger.addHandler(file_handler)


def get_log_path() -> Path:
    """Return the persistent server log path."""
    env_path = os.getenv("FERELIX_LOG_PATH")
    if env_path:
        return Path(env_path)

    config_dir = Path("/config")
    try:
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "logs" / LOG_FILE_NAME
    except OSError:
        return Path.cwd() / "logs" / LOG_FILE_NAME


def _log_level_from_env(name: str, default: str) -> int:
    level_name = os.getenv(name, default).upper()
    return getattr(logging, level_name, getattr(logging, default))


def _log_level_name_from_env(name: str, default: str) -> str:
    level_name = os.getenv(name, default).upper()
    return level_name if level_name in LOG_LEVELS else default


def _int_from_env(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(value, minimum)


def logs_config() -> LogsConfigResponse:
    """Return dashboard-visible log configuration."""
    file_level_name = _log_level_name_from_env("FERELIX_FILE_LOG_LEVEL", DEFAULT_FILE_LOG_LEVEL)
    file_level = getattr(logging, file_level_name)
    return LogsConfigResponse(
        levels=[level for level in LOG_LEVELS if getattr(logging, level) >= file_level],
        file_level=file_level_name,
        max_bytes=_int_from_env("FERELIX_LOG_MAX_BYTES", DEFAULT_MAX_LOG_BYTES, minimum=1024),
        backup_count=_int_from_env("FERELIX_LOG_BACKUP_COUNT", DEFAULT_LOG_BACKUP_COUNT, minimum=1),
    )


def read_logs(
    max_lines: int | None,
    *,
    levels: set[str] | None = None,
    channels: set[str] | None = None,
) -> LogsResponse:
    """Read the persistent logs, including rotated files, oldest first."""
    log_path = get_log_path()
    parsed_lines: list[LogLineSchema] = []
    line_number = 1
    for path in log_files_oldest_first(log_path):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            parsed = _schema_for_line(line_number, line)
            line_number += 1
            if _matches_filters(parsed, levels=levels, channels=channels):
                parsed_lines.append(parsed)

    truncated = False
    if max_lines is not None and len(parsed_lines) > max_lines:
        parsed_lines = parsed_lines[-max_lines:]
        truncated = True

    return LogsResponse(
        lines=parsed_lines,
        next_offset=_file_size(log_path),
        truncated=truncated,
        path=str(log_path),
    )


def tail_logs(
    offset: int,
    *,
    levels: set[str] | None = None,
    channels: set[str] | None = None,
) -> LogsResponse:
    """Read new bytes from the current log file since an offset."""
    log_path = get_log_path()
    size = _file_size(log_path)
    if offset < 0 or offset > size:
        offset = 0

    if not log_path.exists():
        return LogsResponse(lines=[], next_offset=0, path=str(log_path))

    with log_path.open("r", encoding="utf-8", errors="replace") as file:
        file.seek(offset)
        lines = file.read().splitlines()
        next_offset = file.tell()

    return LogsResponse(
        lines=[
            parsed
            for parsed in (_schema_for_line(number, line) for number, line in enumerate(lines, start=1))
            if _matches_filters(parsed, levels=levels, channels=channels)
        ],
        next_offset=next_offset,
        path=str(log_path),
    )


def channel_for_logger(logger_name: str) -> str:
    """Map Python logger names to dashboard channels."""
    if logger_name.startswith("uvicorn"):
        return "web"
    if logger_name.startswith("apscheduler") or logger_name in {"app.services.jobs", "app.services.settings"}:
        return "scheduler"
    if logger_name.startswith(("app.services.transcoder", "app.services.transcoding", "app.services.playback_session")):
        return "transcode"
    if logger_name.startswith("app.routers.v1.streaming"):
        return "transcode"
    if logger_name.startswith("app.services.scanner"):
        return "scanner"
    if logger_name.startswith(("app.services.auth", "app.routers.v1.auth", "app.routers.v1.users")):
        return "auth"
    if logger_name.startswith("app.routers"):
        return "api"
    if logger_name.startswith("sqlalchemy"):
        return "database"
    if logger_name in {"app.main", "__main__"}:
        return "web"
    return "server"


def log_files_oldest_first(log_path: Path) -> list[Path]:
    """Return rotated log files followed by the active file."""
    parent = log_path.parent
    if not parent.exists():
        return []

    rotated: list[tuple[int, Path]] = []
    for path in parent.glob(f"{LOG_FILE_NAME}.*"):
        suffix = path.name.removeprefix(f"{LOG_FILE_NAME}.")
        if suffix.isdigit():
            rotated.append((int(suffix), path))

    files = [path for _index, path in sorted(rotated, reverse=True)]
    if log_path.exists():
        files.append(log_path)
    return files


def _schema_for_line(number: int, line: str) -> LogLineSchema:
    match = re.match(
        r"^(?P<timestamp>(?:\d{4}-\d{2}-\d{2}T\S+)|(?:\d{4}-\d{2}-\d{2} \S+)) - (?:(?P<channel>[a-z_]+) - )?(?P<logger>.*?) - (?P<level>[A-Z]+) - ",
        line,
    )
    logger_name = match.group("logger") if match else None
    timestamp = match.group("timestamp") if match else None
    return LogLineSchema(
        number=number,
        text=line,
        message=line[match.end() :] if match else line,
        channel=match.group("channel") if match and match.group("channel") else (channel_for_logger(logger_name) if logger_name else None),
        logger=logger_name,
        level=match.group("level") if match else None,
        timestamp=_normalize_timestamp(timestamp),
    )


def _normalize_timestamp(timestamp: str | None) -> str | None:
    if not timestamp:
        return None

    try:
        return datetime.strptime(timestamp, LOG_DATE_FORMAT).isoformat()
    except ValueError:
        return timestamp


def _matches_filters(line: LogLineSchema, *, levels: set[str] | None, channels: set[str] | None) -> bool:
    if levels and (line.level or "").upper() not in levels:
        return False
    return not (channels and (line.channel or "") not in channels)


def _file_size(path: Path) -> int:
    return path.stat().st_size if path.exists() else 0


def _total_line_count(log_path: Path) -> int:
    total = 0
    for path in log_files_oldest_first(log_path):
        with path.open("r", encoding="utf-8", errors="replace") as file:
            total += sum(1 for _line in file)
    return total
