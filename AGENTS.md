# Ferelix - AI Coding Agent Guide

Ferelix is a media server with FastAPI backend and Vue 3 frontend, featuring transcoding and HLS streaming.

## Architecture Overview

**Monorepo Structure**: `./server` (Python backend) + `./web` (Vue 3 frontend)

**Backend Stack** (`./server`):
- FastAPI + Python 3.14+ + SQLAlchemy (async) + Alembic migrations
- Media processing: FFmpeg/ffprobe for metadata extraction and HLS transcoding
- Streaming strategies: DirectPlay → DirectStream/Remux → Full Transcode
- Key services: `StreamBuilder` (playback decisions), `FFmpegTranscoder` (HLS), `Scanner` (library indexing)

**Frontend Stack** (`./web`):
- Vue 3 + TypeScript + Vite + Tailwind CSS 4 + HLS.js
- API client: openapi-fetch with auto-generated types from backend OpenAPI schema
- Dev server proxies `/api` → `http://localhost:8000`

## Critical Workflows

### Command Runner: Just
All dev commands use [Just](https://github.com/casey/just). Run `just --list` to see all commands.
- **Start development**: `just dev` (runs both server and frontend in parallel)
- **Servers may already be running** from previous sessions - check before starting

### API Type Synchronization (CRITICAL)
When backend routes change, **always** regenerate types:
```bash
# In ./server - export OpenAPI schema
uv run python -m scripts.export_openapi

# In ./web - regenerate TypeScript types
pnpm generate-api-types
```

**Pre-commit hooks auto-run these**, ensuring types stay synced. If frontend shows type errors after backend changes, regenerate types first.

### Backend Development
```bash
# Package manager: uv (NOT pip)
uv sync                              # Install dependencies
uv run fastapi dev                   # Start dev server (hot reload)
uv run --no-sync fastapi run         # Production server

# Database migrations
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head

# Code quality (pre-commit runs automatically)
uv run ruff check --fix
uv run ruff format
```

### Frontend Development
```bash
# Package manager: pnpm (version pinned in package.json)
pnpm install                         # Install dependencies
pnpm dev                            # Dev server on port 5173
pnpm build                          # Production build
pnpm check --fix                    # Format + lint (Biome)
```

## Code Patterns & Conventions

### Backend: Database Access
**Always use dependency injection** for database sessions:
```python
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_session

async def my_route(session: Annotated[AsyncSession, Depends(get_session)]):
    # Use session.get(), session.scalar(), session.scalars()
```

**Background tasks** need their own session:
```python
from app.database import async_session_maker

async def background_job():
    async with async_session_maker() as session:
        # Your code
```

### Backend: Route Organization
- Models: `app/models/` (SQLAlchemy declarative)
- Services: `app/services/` (business logic - transcoder, scanner, stream_builder)
- Routes: `app/routers/v1/` (API endpoints grouped by domain)

### Frontend: API Integration
**Centralized API client** (`src/api/client.ts`):
- All API calls go through this module
- Token refresh handled automatically
- Types auto-generated from OpenAPI schema

**Path alias**: Use `@/` → `src/` for imports
```typescript
import { media } from "@/api/client";
import type { MediaFile } from "@/api/types";
```

### Frontend: Internationalization
**All UI text requires translations** in both `src/i18n/locales/en.json` and `fr.json`:
```typescript
const { t } = useI18n();
// Use: {{ t('key.path') }}
```

### Streaming Strategy Pattern
`StreamBuilder` service (`app/services/stream_builder.py`) determines playback method:
1. **DirectPlay**: Native file serving (no processing)
2. **DirectStream/Remux**: Container conversion only (fast, no re-encoding)
3. **Transcode**: Full video+audio re-encoding (fallback)

Decision logic compares `DeviceProfile` capabilities against media file metadata (codecs, resolution, bitrate).

## Docker & CI

**Dockerfile** (`docker/Dockerfile`):
- Multi-stage build: frontend → backend
- Embeds `uv` package manager
- Installs FFmpeg for media processing
- Entrypoint runs migrations automatically: `uv run --no-sync alembic upgrade head`

**Production installs**: `uv sync --locked --no-default-groups` (excludes dev dependencies)

## Code Review Guidelines

When reviewing code, **focus on real bugs only** - not style preferences or minor improvements:
- Logic errors (null checks, off-by-one, race conditions)
- Type safety violations
- Security issues (auth bypass, injection vulnerabilities)
- Performance problems (N+1 queries, memory leaks)
- Breaking changes to APIs

**Do NOT nitpick**: formatting, naming conventions, code organization - linters and pre-commit hooks handle these automatically.

## Common Pitfalls

1. **Frontend type errors after backend changes**: Run API type regeneration workflow
2. **Database queries**: Import models at top of file, not inside functions
3. **Sessions in background tasks**: Must create new session with `async_session_maker()`
4. **Frontend API paths**: Dev proxy handles `/api`, don't hardcode backend URL
5. **Subtitle handling**: Text codecs (SRT, ASS) extract to WebVTT; image codecs (PGS, VOBSUB) burn into video

## Key Files

- `server/app/main.py` - FastAPI app entry, scheduler setup
- `server/app/services/transcoder.py` - FFmpeg HLS transcoding (1000+ lines)
- `server/app/services/stream_builder.py` - Playback decision logic
- `web/src/api/client.ts` - Centralized API client with token refresh
- `web/src/components/CustomVideoPlayer.vue` - HLS player with transcode management
- `justfile` - All development commands
