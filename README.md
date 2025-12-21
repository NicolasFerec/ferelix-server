# Ferelix

Ferelix is a self-hosted media server, similar to Plex or Jellyfin. It allows you to organize, manage, and stream your personal media collection from your own server.

## Architecture

Ferelix is organized into two main subprojects:

- **[Server](./server)** - The backend API and media management engine built with Python
- **[Web](./web)** - The web dashboard and media player built with modern web technologies

## Quick Start

### Prerequisites

- **Python 3.14+** and **[uv](https://docs.astral.sh/uv/)** - For the backend server
- **pnpm** - For the web frontend
- **ffmpeg** - For video metadata extraction
- **[just](https://github.com/casey/just)** - Command runner (optional but recommended)

### Install Just (Command Runner)

Just is a handy command runner that makes working with this monorepo easier:

```bash
# Debian/Ubuntu
sudo apt install just
```

Verify installation:
```bash
just --version
```

### Install Dependencies

```bash
# Using just (recommended)
just install

# Or manually
cd server && uv sync
cd web && pnpm install
```

### Run Development Servers

```bash
# Start both backend and frontend together
just dev

# Or start them separately in different terminals
just dev-server   # Backend only
just dev-web      # Frontend only
```

The server will be available at `http://localhost:8000` and the web client at `http://localhost:5173`.

### Discover Available Commands

```bash
just --list
```

or simply:

```bash
just
```

This will show all available commands you can run.

## Detailed Setup

For detailed setup instructions, configuration, and development guidelines, refer to the individual README files:

- Server setup: [server/README.md](./server/README.md)
- Web setup: [web/README.md](./web/README.md)

## License

See [LICENSE](./LICENSE) for details.
