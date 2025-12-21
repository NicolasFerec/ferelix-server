# Agent Technical Documentation

Ferelix is a personal media server designed to organize, stream, and manage your media collection. It consists of a backend server built with FastAPI and a frontend web application using Vue 3 and TypeScript.

We're using [Just](https://github.com/casey/just) as a command runner to simplify common tasks across the monorepo. Run `just --list` to see all available commands. Mainly, you'll use `just dev` to start both the backend and frontend development servers.

## [Backend](./server)

The backend is a FastAPI server that handles API requests, database interactions, and media scanning. It handles transcoding when needed and serves media files to clients.

### Quick facts
- Package manager: **uv** (uses `uv.lock`) — see `pyproject.toml`.
- Python: **>= 3.14** (project requires Python 3.14+).
- Web framework: **FastAPI** (`fastapi[standard]`).
- Database migrations: **Alembic** (autogenerate workflow).
- Media metadata: uses **ffprobe** (from ffmpeg).

### Common tasks (short)
- Sync dependencies: `uv sync` (or `uv sync --locked` in CI/Docker).
- Run dev server: `uv run fastapi dev` (or `uv run --no-sync fastapi run` for production).
- Create migration: `uv run alembic revision --autogenerate -m "desc"` then edit `alembic/versions/`.
- Apply migrations: `uv run alembic upgrade head` (Docker entrypoint runs this automatically).

Notes:
- Use `uv run` to execute project-local commands (lints, alembic, pytest).

### Docker / CI notes
- The image installs `ffmpeg` and embeds `uv` (see `docker/Dockerfile`).
- Docker entrypoint runs migrations: `docker/docker-entrypoint.sh` contains `uv run --no-sync alembic upgrade head`.
- Use `uv sync --locked --no-default-groups` when building images to reproduce environments.

### Development conventions (for agents)
- Models live under `app/models/` and follow SQLAlchemy declarative patterns.
- Use dependency injection for DB sessions: prefer `Annotated[AsyncSession, Depends(get_session)]` and helper `async_session_maker()` for background tasks.
- Prefer `session.get()`, `session.scalar()` and `session.scalars()` for queries — see examples in this repo.
- Use `fastapi` CLI for local development (`uv run fastapi dev`) for convenient defaults and autoreload.

### Migrations and code hygiene
- Always use `uv run alembic` for revisions and `uv run alembic upgrade head` for applying migrations.
- After generating a migration, review `alembic/versions/*` and run `uv run alembic upgrade head` to validate.
- Alembic post-write hooks are configured (e.g., `ruff` formatting) in `pyproject.toml`.

### ffprobe / scanner
- The media scanner at `app/services/scanner.py` calls `ffprobe` to extract duration, resolution, codec, bitrate and frame rate.
- Ensure `ffmpeg` is installed in the environment or container when running scans.

### Testing & housekeeping
- There are no tests currently committed. When adding tests, use `uv run pytest` and `uv run pytest --cov`.
- `.pytest_cache/` and `pytest.ini` are ignored in Docker and `.gitignore`/`.dockerignore`.

___
## [Frontend](./web)

The frontend consists of an admin interface (dashboard) and a web app to browse and play media.

### Quick facts

- Package manager: **pnpm** (project has a pinned `packageManager` version in `package.json`).
- Node: **>= 18** (see `engines`).
- Language: **TypeScript** (Vue 3 + TypeScript).
- Dev server: **Vite** (default port 5173) — dev commands run `pnpm generate-version && vite`.

### Common tasks (short)
- Install: `pnpm install` (CI caches pnpm & uses `pnpm-lock.yaml`).
- Dev: `pnpm dev` (runs `generate-version` first).
- Build: `pnpm build` (runs `generate-version` then `vite build`).
- Preview: `pnpm preview` / Clean: `pnpm clean`.
- Format / Lint: `pnpm check --fix` (biome).
- Type-check: `pnpm type-check` (vue-tsc).

Note: `scripts/generate-version.js` must run before dev/build; it's included in `dev` and `build` scripts.

### CI / Release

- GitHub Actions workflow `.github/workflows/build-and-release.yml` caches pnpm and runs `pnpm install` then `pnpm build`.

### Development conventions (for agents)

- Components: `src/components/` (PascalCase, single-file `.vue`).
- Views: `src/views/` and routing in `src/router/`.
- API: centralized in `src/api/client.js` (token refresh + concurrency handling). Update here for new endpoints.
- i18n: add keys to `src/i18n/locales/en.json` and `fr.json` when adding text.
- Styling: Tailwind CSS (`tailwind.config.js`) and `src/style.css`.

### Proxy & runtime

- Dev proxy: Vite proxies `/api` → `http://localhost:8000` (configured in `vite.config.js`) to avoid CORS during development.
- Path alias: `@` resolves to `src/` (used throughout the codebase).

### Helpful tips

- When adding UI, wire up translations in both locales and add simple unit/e2e tests where appropriate (no tests are present yet).
- For streaming, `hls.js` is used in `VideoPlayer.vue` to handle HLS gracefully (native HLS supported on Safari).
