# Agent Technical Documentation

Concise technical guidance for AI coding agents working on the Ferelix server.

## Quick facts
- Package manager: **uv** (uses `uv.lock`) — see `pyproject.toml`.
- Python: **>= 3.14** (project requires Python 3.14+).
- Web framework: **FastAPI** (`fastapi[standard]`).
- Database migrations: **Alembic** (autogenerate workflow).
- Media metadata: uses **ffprobe** (from ffmpeg).

---

## Common tasks (short)
- Sync dependencies: `uv sync` (or `uv sync --locked` in CI/Docker).
- Run dev server: `uv run fastapi dev` (or `uv run --no-sync fastapi run` for production).
- Create migration: `uv run alembic revision --autogenerate -m "desc"` then edit `alembic/versions/`.
- Apply migrations: `uv run alembic upgrade head` (Docker entrypoint runs this automatically).

Notes:
- Use `uv run` to execute project-local commands (lints, alembic, pytest).

---

## Docker / CI notes
- The image installs `ffmpeg` and embeds `uv` (see `docker/Dockerfile`).
- Docker entrypoint runs migrations: `docker/docker-entrypoint.sh` contains `uv run --no-sync alembic upgrade head`.
- Use `uv sync --locked --no-default-groups` when building images to reproduce environments.

---

## Development conventions (for agents)
- Models live under `app/models/` and follow SQLAlchemy declarative patterns.
- Use dependency injection for DB sessions: prefer `Annotated[AsyncSession, Depends(get_session)]` and helper `async_session_maker()` for background tasks.
- Prefer `session.get()`, `session.scalar()` and `session.scalars()` for queries — see examples in this repo.
- Use `fastapi` CLI for local development (`uv run fastapi dev`) for convenient defaults and autoreload.

---

## Migrations and code hygiene
- Always use `uv run alembic` for revisions and `uv run alembic upgrade head` for applying migrations.
- After generating a migration, review `alembic/versions/*` and run `uv run alembic upgrade head` to validate.
- Alembic post-write hooks are configured (e.g., `ruff` formatting) in `pyproject.toml`.

---

## ffprobe / scanner
- The media scanner at `app/services/scanner.py` calls `ffprobe` to extract duration, resolution, codec, bitrate and frame rate.
- Ensure `ffmpeg` is installed in the environment or container when running scans.

---

## Testing & housekeeping
- There are no tests currently committed. When adding tests, use `uv run pytest` and `uv run pytest --cov`.
- `.pytest_cache/` and `pytest.ini` are ignored in Docker and `.gitignore`/`.dockerignore`.
