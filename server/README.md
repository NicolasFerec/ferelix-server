# Ferelix Server

A self-hosted media server with JWT-based authentication, role-based access control, and HTTP streaming support. Built with FastAPI and designed for personal or family use.

## Features

- 🔐 **Authentication & Authorization**: JWT-based auth with admin/user roles
- 🎬 **Video Streaming**: HTTP Range request support for seeking and partial content delivery
- 📁 **Automatic Library Scanning**: Scheduled folder scanner that discovers video files
- 🗄️ **Database Storage**: SQLite with easy PostgreSQL migration path
- 📊 **Metadata Extraction**: Automatic video metadata extraction using ffprobe (bundled with Python dependencies)
- 🔄 **Database Migrations**: Alembic integration for clean schema evolution
- ⚡ **Async Everything**: Built on async/await for high performance
- 🐳 **Docker Support**: Production-ready containerization for easy deployment


## Development

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- Docker (for production deployment)

Install uv:
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Note:** FFmpeg is no longer required to be installed separately. The `static-ffmpeg` Python package provides bundled FFmpeg binaries that are automatically installed with the project dependencies.

This project uses [pre-commit](https://pre-commit.com/) for code quality checks. Install the git hooks:

```bash
uv run pre-commit install
```
