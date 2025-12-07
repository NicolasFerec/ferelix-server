#!/bin/bash
set -e

echo "Starting Ferelix Server..."

# Create config directory if it doesn't exist
mkdir -p /config

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
    echo "║ Create your admin account by sending a POST request to:       ║"
    echo "║                                                                ║"
    echo "║   http://your-server:8000/api/v1/setup/admin                  ║"
    echo "║                                                                ║"
    echo "║ Example:                                                       ║"
    echo "║   curl -X POST http://localhost:8000/api/v1/setup/admin \\     ║"
    echo "║     -H 'Content-Type: application/json' \\                     ║"
    echo "║     -d '{                                                      ║"
    echo "║       \"username\": \"admin\",                                    ║"
    echo "║       \"email\": \"admin@example.com\",                          ║"
    echo "║       \"password\": \"your-secure-password\"                      ║"
    echo "║     }'                                                         ║"
    echo "║                                                                ║"
    echo "║ All other endpoints will be blocked until setup is complete.  ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
fi

# Execute the main command
exec "$@"
