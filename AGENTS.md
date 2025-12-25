# Agent Technical Documentation

**Ferelix** is a media server with FastAPI backend and Vue 3 frontend, featuring transcoding and HLS streaming.

## Quick Start

**Command Runner**: [Just](https://github.com/casey/just) - Run `just --list` for all commands.
- **Start development**: `just dev` (starts both backend and frontend)
- **Port conflicts**: Servers may already be running from previous sessions, do nothing.

---

## Backend (`./server`)

**Stack**: FastAPI + Python 3.14+ + SQLAlchemy + Alembic + FFmpeg

### Essential Commands
```bash
# Dependencies & Development
uv sync                              # Install dependencies
uv run fastapi dev                   # Start dev server
uv run --no-sync fastapi run         # Production server

# Database
uv run alembic revision --autogenerate -m "description"  # Create migration
uv run alembic upgrade head          # Apply migrations

# Exports
uv run python -m scripts.export_openapi  # Regenerate OpenAPI specs
```

### Tech Stack
- **Package Manager**: uv (see `pyproject.toml`, `uv.lock`)
- **Web Framework**: FastAPI (`fastapi[standard]`)
- **Database**: SQLAlchemy ORM + Alembic migrations
- **Media Processing**: FFmpeg/ffprobe for metadata and transcoding

### Development Guidelines

**Code Structure**:
- Models: `app/models/` (SQLAlchemy declarative)
- Services: `app/services/` (business logic)
- Routes: `app/routers/v1/` (API endpoints)

**Database Patterns**:
- Use `Annotated[AsyncSession, Depends(get_session)]` for dependency injection
- Background tasks: `async_session_maker()` helper
- Queries: prefer `session.get()`, `session.scalar()`, `session.scalars()`
- Always import at top of file

**Docker/CI**:
- Dockerfile installs `ffmpeg` + embeds `uv`
- Entrypoint auto-runs migrations: `uv run --no-sync alembic upgrade head`
- Images: use `uv sync --locked --no-default-groups`

---

## Frontend (`./web`)

**Stack**: Vue 3 + TypeScript + Vite + Tailwind CSS 4 + HLS.js

### Essential Commands
```bash
# Development
pnpm install                         # Install dependencies
pnpm dev                            # Start dev server (port 5173)
pnpm build                          # Production build
pnpm check --fix                    # Format & lint (Biome)

# API Integration
pnpm generate-api-types             # Regenerate TypeScript types from OpenAPI
```

### Tech Stack
- **Package Manager**: pnpm (version pinned in `package.json`)
- **Build Tool**: Vite with dev proxy: `/api` → `http://localhost:8000`
- **Styling**: Tailwind CSS 4 + custom styles in `src/style.css`
- **Video**: HLS.js for streaming, native HLS on Safari

### Development Guidelines

**Code Organization**:
- Components: `src/components/` (PascalCase `.vue` files)
- Views: `src/views/` + routing in `src/router/`
- API: centralized in `src/api/client.ts`
- i18n: `src/i18n/locales/en.json` + `fr.json`

**Key Conventions**:
- Path alias: `@` → `src/`
- API changes → regenerate types with `pnpm generate-api-types`
- All UI text needs translations in both locales

---

## API Synchronization Workflow

**When modifying backend endpoints or encountering frontend typing issues:**

1. In `./server` folder, regenerate OpenAPI specs:
   ```bash
   uv run python -m scripts.export_openapi
   ```

2. In `./web` folder, update TypeScript types from the new spec:
   ```bash
   pnpm generate-api-types
   ```

This ensures the frontend's TypeScript types stay in sync with your backend API changes, preventing type mismatches and improving IDE autocomplete accuracy.

---

## Workflow Integration

**Pre-commit hooks** auto-trigger:
- Backend: OpenAPI spec export
- Frontend: API type regeneration

**Media Processing**:
- Scanner: `app/services/scanner.py` uses ffprobe for metadata
- Transcoder: `app/services/transcoder.py` handles HLS streaming
- Requires FFmpeg installed in environment
