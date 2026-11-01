# =============================================================================
# Stage 1: Build frontend
# =============================================================================
FROM node:26.13.0-slim AS frontend-builder

# Install pnpm
RUN npm install --global --allow-scripts=pnpm pnpm@12.16.1

WORKDIR /build

# Copy frontend package files first for better caching
COPY web/package.json web/pnpm-lock.yaml web/pnpm-workspace.yaml ./
COPY web/patches/ ./patches/
RUN pnpm install --frozen-lockfile

# Copy frontend source and build
COPY web/ ./
RUN pnpm build

# =============================================================================
# Stage 2: Build backend
# =============================================================================
FROM python:3.15.2-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    vainfo \
    mesa-va-drivers \
    pciutils \
    curl \
    ca-certificates \
    openssl \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

# Create app user and directories
RUN useradd -m ferelix && \
    mkdir -p /app /config && \
    chown -R ferelix:ferelix /app /config

# Set working directory
WORKDIR /app

# Switch to ferelix user for installing dependencies
USER ferelix

# Copy and install dependencies
COPY --chown=ferelix:ferelix server/pyproject.toml server/uv.lock ./
RUN uv sync --locked --no-default-groups

# Copy application code
COPY --chown=ferelix:ferelix server/ ./

# Copy frontend build from stage 1
COPY --from=frontend-builder --chown=ferelix:ferelix /build/dist ./app/static

# Switch back to root for entrypoint setup
USER root

# Copy and set up entrypoint
COPY docker/docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Set volumes
VOLUME /config

# Set default environment variables
ENV DATABASE_URL=sqlite+aiosqlite:////config/ferelix.db \
    PUID=1000 \
    PGID=1000

# Run entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uv", "run", "--no-sync", "fastapi", "run"]
