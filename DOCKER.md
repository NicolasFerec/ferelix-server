# Ferelix Server - Docker Deployment Guide

Complete guide for deploying Ferelix Server using Docker.

## Quick Start

```bash
# 1. Create directory
mkdir ferelix && cd ferelix

# 2. Create docker-compose.yml (see below)

# 3. Generate secret key
openssl rand -hex 32

# 4. Update docker-compose.yml with the secret key

# 5. Start server
docker-compose up -d

# 6. Create admin account
curl -X POST "http://localhost:8000/api/v1/setup/admin" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@example.com","password":"your-password"}'
```

## Docker Compose Configuration

### Basic Setup (SQLite)

```yaml
version: '3.8'

services:
  ferelix:
    image: your-dockerhub-username/ferelix-server:latest
    container_name: ferelix-server
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./config:/config
      - /path/to/movies:/media/movies:ro
      - /path/to/tv:/media/tv:ro
    environment:
      - SECRET_KEY=your-secret-key-here
      - DATABASE_URL=sqlite+aiosqlite:///config/ferelix.db
      - ALLOWED_ORIGINS=*
```

### Production Setup (PostgreSQL)

```yaml
version: '3.8'

services:
  ferelix:
    image: your-dockerhub-username/ferelix-server:latest
    container_name: ferelix-server
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./config:/config
      - /path/to/movies:/media/movies:ro
      - /path/to/tv:/media/tv:ro
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - DATABASE_URL=postgresql+asyncpg://ferelix:${DB_PASSWORD}@postgres/ferelix
      - ACCESS_TOKEN_EXPIRE_MINUTES=30
      - REFRESH_TOKEN_EXPIRE_DAYS=7
      - ALLOWED_ORIGINS=https://your-domain.com,https://app.your-domain.com
    depends_on:
      postgres:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 3s
      retries: 3
      start_period: 5s

  postgres:
    image: postgres:16-alpine
    container_name: ferelix-postgres
    restart: unless-stopped
    environment:
      - POSTGRES_USER=ferelix
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=ferelix
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ferelix"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
    driver: local

networks:
  default:
    name: ferelix-network
```

Create a `.env` file:
```bash
SECRET_KEY=your-secret-key-here
DB_PASSWORD=secure-database-password
```

## Volume Mappings

### Configuration Volume (`/config`)

Stores persistent data:
- `ferelix.db` - SQLite database (if using SQLite)
- Future: thumbnails, cache, etc.

**Example:**
```yaml
volumes:
  - ./config:/config
```

### Media Volumes (`/media`)

Mount your media libraries as read-only:

```yaml
volumes:
  # Single library
  - /mnt/storage/movies:/media/movies:ro
  
  # Multiple libraries
  - /mnt/storage/movies:/media/movies:ro
  - /mnt/storage/tv:/media/tv:ro
  - /mnt/nas/anime:/media/anime:ro
  
  # Network share (NFS)
  - type: volume
    source: nfs-movies
    target: /media/movies
    volume:
      nocopy: true
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | *(required)* | JWT signing key - generate with `openssl rand -hex 32` |
| `DATABASE_URL` | `sqlite+aiosqlite:///config/ferelix.db` | Database connection string |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Access token lifetime in minutes |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Refresh token lifetime in days |
| `ALGORITHM` | `HS256` | JWT signing algorithm |
| `ALLOWED_ORIGINS` | `*` | CORS allowed origins (comma-separated) |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |

## Common Deployment Scenarios

### Behind Nginx Reverse Proxy

**docker-compose.yml:**
```yaml
services:
  ferelix:
    # ... other config ...
    environment:
      - ALLOWED_ORIGINS=https://ferelix.yourdomain.com
    networks:
      - web
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.ferelix.rule=Host(`ferelix.yourdomain.com`)"
```

**nginx.conf:**
```nginx
server {
    listen 443 ssl http2;
    server_name ferelix.yourdomain.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Required for streaming
        proxy_buffering off;
        proxy_request_buffering off;
    }
}
```

### With Traefik

```yaml
version: '3.8'

services:
  ferelix:
    image: your-dockerhub-username/ferelix-server:latest
    container_name: ferelix-server
    restart: unless-stopped
    volumes:
      - ./config:/config
      - /path/to/media:/media:ro
    environment:
      - SECRET_KEY=${SECRET_KEY}
      - DATABASE_URL=sqlite+aiosqlite:///config/ferelix.db
    networks:
      - traefik
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.ferelix.rule=Host(`ferelix.yourdomain.com`)"
      - "traefik.http.routers.ferelix.entrypoints=websecure"
      - "traefik.http.routers.ferelix.tls.certresolver=letsencrypt"
      - "traefik.http.services.ferelix.loadbalancer.server.port=8000"

networks:
  traefik:
    external: true
```

### Synology NAS

1. Open Docker app
2. Download image: `your-dockerhub-username/ferelix-server:latest`
3. Create container with these settings:
   - **Port**: Local `8000` → Container `8000`
   - **Volume**: 
     - `/docker/ferelix/config` → `/config`
     - `/volume1/media/movies` → `/media/movies` (read-only)
   - **Environment**:
     - `SECRET_KEY`: (generate with command)
     - `DATABASE_URL`: `sqlite+aiosqlite:///config/ferelix.db`
   - **Restart policy**: Always

### Unraid

1. Go to **Docker** tab
2. Add Container:
   - **Name**: `ferelix-server`
   - **Repository**: `your-dockerhub-username/ferelix-server:latest`
   - **Network Type**: `Bridge`
   - **Port**: `8000` → `8000`
   - **Path** (`/config`): `/mnt/user/appdata/ferelix`
   - **Path** (`/media`): `/mnt/user/media` (read-only)
   - **Variable** (`SECRET_KEY`): (generate)
   - **Variable** (`DATABASE_URL`): `sqlite+aiosqlite:///config/ferelix.db`

## Management Commands

### View Logs
```bash
# All logs
docker-compose logs -f ferelix

# Last 100 lines
docker-compose logs --tail=100 ferelix

# Since specific time
docker logs --since 1h ferelix-server
```

### Restart Server
```bash
docker-compose restart ferelix
```

### Update to Latest Version
```bash
# Pull new image
docker-compose pull ferelix

# Restart with new image
docker-compose up -d ferelix
```

### Database Backup
```bash
# SQLite
docker exec ferelix-server cp /config/ferelix.db /config/ferelix.db.backup

# Or from host
cp ./config/ferelix.db ./config/ferelix.db.backup

# PostgreSQL
docker exec ferelix-postgres pg_dump -U ferelix ferelix > backup.sql
```

### Exec into Container
```bash
docker exec -it ferelix-server bash
```

## Troubleshooting

### Container won't start

Check logs:
```bash
docker logs ferelix-server
```

Common issues:
- Missing `SECRET_KEY` environment variable
- Port 8000 already in use
- Volume permission issues

### Permission Issues

Fix volume permissions:
```bash
# Check current permissions
ls -la ./config

# Fix ownership (user ID 1000 in container)
sudo chown -R 1000:1000 ./config
```

### Database Migration Failed

Run migrations manually:
```bash
docker exec ferelix-server uv run alembic upgrade head
```

### Can't Access Media Files

Verify volume mounts:
```bash
docker exec ferelix-server ls -la /media
```

Ensure host paths exist and are readable.

## Performance Tuning

### Enable PostgreSQL for Better Performance

SQLite is fine for small deployments, but PostgreSQL scales better:

```yaml
environment:
  - DATABASE_URL=postgresql+asyncpg://ferelix:password@postgres/ferelix
```

### Adjust Resource Limits

```yaml
services:
  ferelix:
    # ... other config ...
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
```

### Use External Cache (Future)

For larger deployments, consider Redis for caching:
```yaml
services:
  redis:
    image: redis:7-alpine
    restart: unless-stopped
```

## Security Best Practices

1. **Always use HTTPS in production** (via reverse proxy)
2. **Set strong SECRET_KEY** (minimum 32 characters)
3. **Restrict CORS origins** in production
4. **Use PostgreSQL with strong password**
5. **Mount media as read-only** (`:ro`)
6. **Keep images updated** regularly
7. **Use Docker secrets** for sensitive data
8. **Enable firewall** rules
9. **Run behind reverse proxy** with rate limiting

## Monitoring

### Health Check Endpoint

```bash
curl http://localhost:8000/health
```

### Container Health
```bash
docker ps
docker inspect ferelix-server | jq '.[0].State.Health'
```

### Resource Usage
```bash
docker stats ferelix-server
```

## Multi-Architecture Support

Images are built for:
- `linux/amd64` (x86_64) - Standard PCs, servers
- `linux/arm64` (aarch64) - Raspberry Pi 4, Apple Silicon, ARM servers

Docker automatically pulls the correct architecture.

## Building Custom Images

See main README for build instructions. Key points:

```bash
# Local build
docker build -t ferelix-server:custom .

# Multi-platform build
docker buildx build --platform linux/amd64,linux/arm64 -t ferelix-server:custom .
```

## License

See main repository LICENSE file.
