#!/bin/bash
set -e

echo "Starting Ferelix Server..."

# Handle PUID and PGID for Unraid compatibility
PUID=${PUID:-1000}
PGID=${PGID:-1000}

echo "Setting up user with PUID=$PUID and PGID=$PGID"

# Update group ID if different
CURRENT_PGID=$(id -g ferelix)
if [ "$PGID" != "$CURRENT_PGID" ]; then
    echo "Updating group ID from $CURRENT_PGID to $PGID"
    groupmod -o -g "$PGID" ferelix
fi

# Update user ID if different
CURRENT_PUID=$(id -u ferelix)
if [ "$PUID" != "$CURRENT_PUID" ]; then
    echo "Updating user ID from $CURRENT_PUID to $PUID"
    usermod -o -u "$PUID" ferelix
fi

# Fix ownership of directories
echo "Fixing ownership of /app, /config, and /media..."
chown -R ferelix:ferelix /app /config /media 2>/dev/null || true

# Create config directory if it doesn't exist
mkdir -p /config

# Generate SECRET_KEY on first run if not set
if [ -z "$SECRET_KEY" ]; then
    SECRET_FILE="/config/.secret_key"
    if [ ! -f "$SECRET_FILE" ]; then
        echo "Generating SECRET_KEY..."
        openssl rand -hex 32 > "$SECRET_FILE"
        chmod 600 "$SECRET_FILE"
    fi
    export SECRET_KEY=$(cat "$SECRET_FILE")
    echo "Using generated SECRET_KEY from $SECRET_FILE"
fi

# Run database migrations
echo "Running database migrations..."
cd /app
uv run alembic upgrade head

# Check if setup is complete
SETUP_COMPLETE=$(uv run python -c "
from app.services.setup import is_setup_complete
import asyncio
result = asyncio.run(is_setup_complete())
print('true' if result else 'false')
" || echo "false")

if [ "$SETUP_COMPLETE" = "false" ]; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                   FIRST-TIME SETUP REQUIRED                    ║"
    echo "╠════════════════════════════════════════════════════════════════╣"
    echo "║ Create your admin account by sending a POST request to:        ║"
    echo "║                                                                ║"
    echo "║   http://your-server:8000/api/v1/setup/admin                   ║"
    echo "║                                                                ║"
    echo "║ Example:                                                       ║"
    echo "║   curl -X POST http://localhost:8000/api/v1/setup/admin \\     ║"
    echo "║     -H 'Content-Type: application/json' \\                     ║"
    echo "║     -d '{                                                      ║"
    echo "║       \"username\": \"admin\",                                 ║"
    echo "║       \"email\": \"admin@example.com\",                        ║"
    echo "║       \"password\": \"your-secure-password\"                   ║"
    echo "║     }'                                                         ║"
    echo "║                                                                ║"
    echo "║ All other endpoints will be blocked until setup is complete.   ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
fi

# Execute the main command as the ferelix user
exec su-exec ferelix "$@"
