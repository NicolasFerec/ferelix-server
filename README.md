# Ferelix

Ferelix is a self-hosted media server, similar to Plex or Jellyfin. It allows you to organize, manage, and stream your personal media collection from your own server.

## Architecture

Ferelix is organized into two main subprojects:

- **[Server](./server)** - The backend API and media management engine built with Python
- **[Web](./clients/web)** - The Vue dashboard and media player, with playback orchestration split from reusable player controls and UI helpers

## Quick Start

### Prerequisites

- **Python 3.15.2** and **[uv](https://docs.astral.sh/uv/)** - For the backend server
- **Node.js 26.13.0 LTS** and **pnpm** (version pinned in the root `package.json`)
- **ffmpeg** - For video metadata extraction and generated HLS playback

### Install Dependencies

```bash
# From the repository root
pnpm bootstrap

# Or manually
(cd server && uv sync --locked)
(cd web && pnpm install --frozen-lockfile)
```

### Run Development Servers

```bash
# Start both backend and frontend together
pnpm dev

# Or start them separately in different terminals
pnpm dev:server   # Backend only
pnpm dev:web      # Frontend only
```

The server will be available at `http://localhost:8005` and the web client at `http://localhost:5187`.

### Transcoding Configuration

Ferelix defaults to the `ffmpeg` binary on `PATH`. To run a packaged build such as `jellyfin-ffmpeg`, point the server at it without changing code:

```bash
export FERELIX_FFMPEG_PATH=/usr/lib/jellyfin-ffmpeg/ffmpeg
export FERELIX_TRANSCODE_DIR=/tmp/ferelix-transcode
export FERELIX_THUMBNAIL_DIR=/tmp/ferelix-thumbnails
```

The player uses DirectPlay when possible, HLS remux for compatible streams in unsupported containers, audio-only transcode when only audio is incompatible, and full HLS transcode as the fallback. Library scans also use ffmpeg to extract a representative thumbnail screenshot for each media card.

Hardware transcoding is detected automatically from the devices visible to the Ferelix process. The Docker image includes `vainfo` and Mesa VAAPI drivers so AMD/Intel devices can report their codec capabilities from inside the container. Expose the host GPU first:

```bash
# AMD/Intel VAAPI
--device /dev/dri:/dev/dri

# NVIDIA NVENC/NVDEC
--runtime=nvidia
-e NVIDIA_VISIBLE_DEVICES=all
-e NVIDIA_DRIVER_CAPABILITIES=all
```

Ferelix tests the visible FFmpeg encoders at runtime and uses `auto` by default. Admins can pin a specific detected device, or force software encoding, from Dashboard > Settings > Hardware Transcoding. The optional `FERELIX_HW_ACCEL_DEVICE` environment variable accepts the same values (`auto`, `software`, or a detected device id such as `vaapi:/dev/dri/renderD128`).

### Available Commands

Run `pnpm run` at the repository root to list all commands.

| Command | Purpose |
| --- | --- |
| `pnpm bootstrap` | Install backend and frontend dependencies |
| `pnpm dev` | Run migrations and start both development servers |
| `pnpm dev:server` / `pnpm dev:web` | Start one development server |
| `pnpm test` | Run all tests |
| `pnpm test:server` / `pnpm test:web` | Run backend or frontend tests |
| `pnpm type-check` (or `pnpm tc`) | Check backend and frontend types |
| `pnpm type-check:server` / `pnpm type-check:web` | Check one component's types |
| `pnpm build` | Build the web client |

## Detailed Setup

For detailed setup instructions, configuration, and development guidelines, refer to the individual README files:

- Server setup: [server/README.md](./server/README.md)
- Web setup: [clients/web/README.md](./clients/web/README.md)

## License

See [LICENSE](./LICENSE) for details.

## Daily development

From the repository root, run `pnpm bootstrap` once to install Python and web dependencies, then `pnpm dev` to start both servers. Node.js 26.13.0 LTS is required. Stop both servers with Ctrl+C; if either server fails, the other is stopped too. Occupied ports are reported before migrations run.

The launcher loads optional `.env` and `.env.local` files from the root and each component directory. Component values override root values; exported shell variables take precedence. Vite also loads its usual mode-specific environment files.

The backend applies Alembic migrations before starting and watches only `server/app/`. SQLite defaults to `server/ferelix.db`. Worktree setup installs dependencies and copies environment files, but does not copy the database.

Root commands: `pnpm test`, `pnpm type-check`, `pnpm build`, `pnpm dev:server`, and `pnpm dev:web`. Frontend dependencies and their lockfile stay in `clients/web/`; root scripts delegate to that package.

### Dependency compatibility

TypeScript stays on `~5.9.3`: the current Vue language tools cannot run with TypeScript 7, and `openapi-typescript` requires TypeScript 5. All other direct dependencies were refreshed to their latest stable releases on 2026-11-01. pnpm is pinned to 12.16.1 in both packages and Docker. The web pnpm settings allow the exact same-day releases selected in this refresh while preserving the release-age check for other versions.

### Authentication and local storage

Accounts are created by administrators in the dashboard; `/api/v1/auth/register` also requires administrator authentication. First-run setup creates the initial administrator atomically.

Set `SECRET_KEY` to manage the signing key yourself. Otherwise Ferelix generates a private persistent `.secret_key` in the backend working directory (or `/config/.secret_key` in Docker). Keep it private and backed up; changing it invalidates existing tokens. `FERELIX_SECRET_KEY_FILE` can override its location. Installations previously using the public development key must sign in again.

Profile images are stored in `/config/images/profile` in Docker and `server/images/profile` for local development. `FERELIX_PROFILE_IMAGE_DIR` overrides this location.

The web lockfile also refreshes transitive dependencies. `pnpm-workspace.yaml` overrides `glob` and `minimatch` to patched releases; `clients/web/patches/@redocly__openapi-core@1.34.22.patch` adapts Redocly's minimatch import so OpenAPI generation remains compatible. A regression test exercises URL-header matching through this patched code. Remove the patch when the generator supports the maintained dependency directly.

### Runtime versions

The project uses Python 3.15.2, Node.js 26.13.0 LTS, uv 0.13.6 and pnpm 12.16.1. Root and backend `.python-version` files select Python for uv; `.nvmrc` selects Node for nvm and CI. Docker uses the same pinned versions.

Before working in a new terminal, run `nvm use` from the repository, then `pnpm bootstrap` and `pnpm dev`. If the selected Node version is missing, run `nvm install` first. Python is installed automatically by uv when needed. The OS Python and nvm default for other repositories are not changed.
