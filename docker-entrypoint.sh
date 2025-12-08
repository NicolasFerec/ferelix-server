#!/bin/bash
set -e

echo "Starting Ferelix Server..."

# -------------------------------
# Handle PUID and PGID
# -------------------------------
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

# -------------------------------
# Ensure /config directory has correct ownership
# -------------------------------
echo "Setting up /config directory..."
mkdir -p /config
chown -R ferelix:ferelix /config
chmod 755 /config

# -------------------------------
# SECRET_KEY
# -------------------------------
if [ -z "$SECRET_KEY" ]; then
    SECRET_FILE="/config/.secret_key"
    if [ ! -f "$SECRET_FILE" ]; then
        echo "Generating SECRET_KEY..."
        gosu ferelix openssl rand -hex 32 > "$SECRET_FILE"
        chmod 600 "$SECRET_FILE"
    fi
    export SECRET_KEY=$(cat "$SECRET_FILE")
    echo "Using SECRET_KEY from $SECRET_FILE"
fi

# -------------------------------
# Run database migrations AS ferelix
# -------------------------------
echo "Running database migrations..."
cd /app
gosu ferelix uv run --no-sync alembic upgrade head

# Fix permissions on database files if they exist
DB_FILE="${DATABASE_URL#*:///}"
if [ -f "$DB_FILE" ]; then
    chown ferelix:ferelix "$DB_FILE"
    chmod 644 "$DB_FILE"

    # Fix SQLite journal files
    for ext in "-journal" "-wal" "-shm"; do
        if [ -f "${DB_FILE}${ext}" ]; then
            chown ferelix:ferelix "${DB_FILE}${ext}"
            chmod 644 "${DB_FILE}${ext}"
        fi
    done
fi

# -------------------------------
# Check if setup is complete AS ferelix
# -------------------------------
SETUP_COMPLETE=$(gosu ferelix uv run --no-sync python -c "import asyncio; from app.services.setup import is_setup_complete; print(\"true\" if asyncio.run(is_setup_complete()) else \"false\")" || echo "false")

if [ "$SETUP_COMPLETE" = "false" ]; then
    echo ""
    echo "╔════════════════════════════════════════════════════════════════╗"
    echo "║                   FIRST-TIME SETUP REQUIRED                    ║"
    echo "╠════════════════════════════════════════════════════════════════╣"
    echo "║ Create your admin account by sending a POST request to:        ║"
    echo "║                                                                ║"
    echo "║   http://your-server:8659/api/v1/setup/admin                   ║"
    echo "║                                                                ║"
    echo "║ Example:                                                       ║"
    echo "║   curl -X POST http://localhost:8659/api/v1/setup/admin \\      ║"
    echo "║     -H 'Content-Type: application/json' \\                      ║"
    echo "║     -d '{                                                      ║"
    echo "║       \"username\": \"admin\",                                     ║"
    echo "║       \"email\": \"admin@example.com\",                            ║"
    echo "║       \"password\": \"your-secure-password\"                       ║"
    echo "║     }'                                                         ║"
    echo "║                                                                ║"
    echo "║ All other endpoints will be blocked until setup is complete.   ║"
    echo "╚════════════════════════════════════════════════════════════════╝"
    echo ""
fi

# -------------------------------
# Execute the main command AS ferelix
# -------------------------------
echo "Starting application as user ferelix (UID=$PUID, GID=$PGID)..."
exec gosu ferelix "$@"
