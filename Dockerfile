FROM python:3.14-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Install system dependencies including ffmpeg, openssl, and su-exec
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    openssl \
    su-exec \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create app user and directories with default IDs
RUN useradd -m -u 1000 ferelix && \
    mkdir -p /app /config /media && \
    chown -R ferelix:ferelix /app /config /media

# Set working directory
WORKDIR /app

# Copy dependency files
COPY --chown=ferelix:ferelix pyproject.toml ./

# Install dependencies
RUN uv sync --frozen --no-dev --no-install-project

# Copy application code
COPY --chown=ferelix:ferelix . .

# Install the project
RUN uv sync --frozen --no-dev

# Copy and set up entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Don't switch to non-root user yet - entrypoint will handle it

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set volumes
VOLUME ["/config", "/media"]

# Set default environment variables
ENV DATABASE_URL=sqlite+aiosqlite:///config/ferelix.db \
    HOST=0.0.0.0 \
    PORT=8000 \
    PUID=1000 \
    PGID=1000

# Run entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uv", "run", "fastapi", "run", "--host", "0.0.0.0", "--port", "8000"]
