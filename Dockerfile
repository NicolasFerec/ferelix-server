FROM python:3.14-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

# Install system dependencies including ffmpeg, openssl, and gosu
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    ca-certificates \
    openssl \
    unzip \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Create app user and directories with default IDs
RUN useradd -m ferelix && \
    mkdir -p /app /config && \
    chown -R ferelix:ferelix /app /config

# Set working directory
WORKDIR /app

# Switch to ferelix user for installing dependencies
USER ferelix

# Copy dependency files
COPY --chown=ferelix:ferelix pyproject.toml uv.lock ./

# Install dependencies and project
RUN uv sync --locked --no-default-groups

# Copy application code
COPY --chown=ferelix:ferelix . .

# Switch back to root for the rest of the build
USER root


# Download and set up front-end static files (only in CI with github_token secret)
# For local builds, frontend files should already be in app/static/
ARG FRONT_RELEASE=rolling
ENV FRONT_RELEASE=${FRONT_RELEASE}
RUN --mount=type=secret,id=github_token,required=false \
    if [ -f /run/secrets/github_token ]; then \
      GITHUB_TOKEN=$(cat /run/secrets/github_token) \
      && mkdir -p /app/static \
      && curl -fSL -H "Authorization: token ${GITHUB_TOKEN}" -H "Accept: application/octet-stream" \
        -o /tmp/dist.zip \
        https://github.com/NicolasFerec/ferelix-client-web/releases/download/${FRONT_RELEASE}/dist.zip \
      && unzip /tmp/dist.zip -d /app/static \
      && rm /tmp/dist.zip \
      && echo "Frontend downloaded from GitHub release"; \
    else \
      echo "INFO: Building without GitHub token - using local static files from app/static/"; \
    fi


# Copy and set up entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Expose port
EXPOSE 8659

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8659/health || exit 1

# Set volumes
VOLUME /config

# Set default environment variables
ENV DATABASE_URL=sqlite+aiosqlite:///config/ferelix.db \
    HOST=0.0.0.0 \
    PORT=8659 \
    PUID=1000 \
    PGID=1000

# Run entrypoint
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uv", "run", "--no-sync", "fastapi", "run", "--host", "0.0.0.0", "--port", "8659"]
