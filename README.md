# Ferelix Server

A self-hosted media server with JWT-based authentication, role-based access control, and HTTP streaming support. Built with FastAPI and designed for personal or family use.

## Features

- 🔐 **Authentication & Authorization**: JWT-based auth with admin/user roles
- 🎬 **Video Streaming**: HTTP Range request support for seeking and partial content delivery
- 📁 **Automatic Library Scanning**: Scheduled folder scanner that discovers video files
- 🗄️ **Database Storage**: SQLite with easy PostgreSQL migration path
- 📊 **Metadata Extraction**: Automatic video metadata extraction using ffprobe (duration, resolution, codec)
- 🔄 **Database Migrations**: Alembic integration for clean schema evolution
- ⚡ **Async Everything**: Built on async/await for high performance
- 🌐 **CORS Support**: Configurable cross-origin support for web/mobile clients
- 🐳 **Docker Support**: Production-ready containerization for easy deployment

## Quick Start (Docker - Recommended)

The fastest way to get started is using Docker:

```bash
# 1. Create docker-compose.yml from the example below
# 2. Update media paths in docker-compose.yml
# 3. Start the server
docker-compose up -d

# 4. Create your admin account
curl -X POST "http://localhost:8000/api/v1/setup/admin" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@example.com",
    "password": "secure-password"
  }'
```

See [Docker Deployment](#docker-deployment) section below for the docker-compose.yml example.

## Prerequisites (For Development)

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) - Fast Python package manager
- ffmpeg (for ffprobe metadata extraction)

**OR**

- Docker and Docker Compose (for production deployment)

Install uv:
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Install ffmpeg:
```bash
# Ubuntu/Debian
sudo apt-get install ffmpeg

# macOS
brew install ffmpeg

# Windows
# Download from https://ffmpeg.org/download.html
```

## Docker Deployment

### Using Docker Compose (Recommended)

1. **Create a directory for Ferelix:**
```bash
mkdir ferelix-server
cd ferelix-server
```

2. **Create a `docker-compose.yml` file with this content:**
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
      - /path/to/your/movies:/media/movies:ro
      - /path/to/your/tv:/media/tv:ro
    environment:
      # Optional: All variables have sane defaults
      # SECRET_KEY is auto-generated if not provided
      # DATABASE_URL defaults to SQLite in /config/ferelix.db
      
      # If using your own PostgreSQL server:
      # DATABASE_URL: postgresql+asyncpg://user:password@your-postgres-host:5432/ferelix
      
      # CORS configuration (defaults to allowing all origins)
      ALLOWED_ORIGINS: "*"
```

3. **Update media paths** in `docker-compose.yml`

4. **Start the server:**
```bash
docker-compose up -d
```

5. **Create your admin account:**
```bash
curl -X POST "http://localhost:8000/api/v1/setup/admin" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@example.com",
    "password": "your-secure-password"
  }'
```

6. **View logs:**
```bash
docker-compose logs -f ferelix
```

### Using Docker Run

```bash
# Create config directory
mkdir -p ./config

# Run container
docker run -d \
  --name ferelix-server \
  -p 8000:8000 \
  -v $(pwd)/config:/config \
  -v /path/to/movies:/media/movies:ro \
  --restart unless-stopped \
  your-dockerhub-username/ferelix-server:latest
```

**Note:** SECRET_KEY is auto-generated on first run and stored in `/config/.secret_key`

### Building Your Own Image

```bash
# Clone the repository
git clone https://github.com/your-username/ferelix-server.git
cd ferelix-server

# Build the image
docker build -t ferelix-server:latest .

# Or build for multiple platforms (for Docker Hub)
docker buildx build --platform linux/amd64,linux/arm64 -t your-dockerhub-username/ferelix-server:latest --push .
```

### Pushing to Docker Hub

```bash
# Login to Docker Hub
docker login

# Tag your image
docker tag ferelix-server:latest your-dockerhub-username/ferelix-server:latest
docker tag ferelix-server:latest your-dockerhub-username/ferelix-server:1.0.0

# Push to Docker Hub
docker push your-dockerhub-username/ferelix-server:latest
docker push your-dockerhub-username/ferelix-server:1.0.0
```

### Automated Docker Builds with GitHub Actions

The repository includes a GitHub Actions workflow that automatically builds and pushes Docker images to Docker Hub:

**Setup:**

1. Go to your GitHub repository → Settings → Secrets and variables → Actions
2. Add the following secrets:
   - `DOCKERHUB_USERNAME` - Your Docker Hub username
   - `DOCKERHUB_TOKEN` - Your Docker Hub access token (create at https://hub.docker.com/settings/security)

**Automatic builds are triggered on:**
- Push to `main` branch → builds `latest` tag
- Push tags like `v1.0.0` → builds versioned tags (`1.0.0`, `1.0`, `1`, `latest`)
- Pull requests → builds for testing (not pushed)

**Manual build:**
- Go to Actions → Build and Push Docker Image → Run workflow

The workflow builds multi-platform images (amd64, arm64) for maximum compatibility.

### Docker Volumes

- `/config` - Database and configuration files (persistent)
- `/media` - Your media files (mount read-only with `:ro`)

### Docker Environment Variables

All environment variables from the [Configuration](#configuration) section can be used with Docker.

## Development Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd ferelix-server
```

2. Sync dependencies with uv:
```bash
uv sync
```

This will automatically create a virtual environment and install all dependencies.

## Configuration

### Environment Variables

All environment variables are **optional** with sane defaults. Create a `.env` file only if you need to customize:

```bash
# Optional: JWT secret key
# Auto-generated in Docker, uses dev default for local development
# For production outside Docker: generate with `openssl rand -hex 32`
# SECRET_KEY=your-secret-key-here

# Optional: Database connection (defaults to SQLite)
# DATABASE_URL=sqlite+aiosqlite:///./ferelix.db

# If using your own PostgreSQL server:
# DATABASE_URL=postgresql+asyncpg://user:password@localhost/ferelix

# Optional: JWT configuration (defaults shown)
# ACCESS_TOKEN_EXPIRE_MINUTES=30
# REFRESH_TOKEN_EXPIRE_DAYS=7

# Optional: CORS configuration
# ALLOWED_ORIGINS=*  # For development; restrict in production
```

**For development**, you don't need a `.env` file at all - just run the server with defaults.

## Database Setup

Run migrations to create the database schema:

```bash
uv run alembic upgrade head
```

The database will be created automatically with the User and RefreshToken tables for authentication.

## Running the Server

Start the development server:

```bash
fastapi dev
```

Or for production:

```bash
fastapi run
```

The server will be available at `http://localhost:8000`

API documentation is available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## First-Time Setup

On first run, you **must create an admin account** before using any other endpoints:

```bash
curl -X POST "http://localhost:8000/api/v1/setup/admin" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@example.com",
    "password": "secure-password"
  }'
```

After creating the admin account, all other endpoints will become available. The setup endpoint will be disabled once the first user exists.

## Authentication

### Login

Get access and refresh tokens:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "secure-password"
  }'
```

Response:
```json
{
  "access_token": "eyJ0eXAi...",
  "refresh_token": "eyJ0eXAi...",
  "token_type": "bearer",
  "user": {
    "id": 1,
    "username": "admin",
    "email": "admin@example.com",
    "is_admin": true,
    "is_active": true,
    "created_at": "2025-12-07T10:00:00",
    "updated_at": "2025-12-07T10:00:00"
  }
}
```

### Using Access Tokens

Include the access token in the Authorization header:

```bash
curl -X GET "http://localhost:8000/api/v1/media-files" \
  -H "Authorization: Bearer eyJ0eXAi..."
```

### Refreshing Tokens

When your access token expires (default: 30 minutes), use the refresh token:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJ0eXAi..."
  }'
```

### Logout

Revoke your refresh token:

```bash
curl -X POST "http://localhost:8000/api/v1/auth/logout" \
  -H "Authorization: Bearer eyJ0eXAi..." \
  -H "Content-Type: application/json" \
  -d '{
    "refresh_token": "eyJ0eXAi..."
  }'
```

## Adding Library Paths

Add media library paths via the API (admin only):

```bash
curl -X POST "http://localhost:8000/api/v1/library-paths?path=/path/to/your/movies&enabled=true" \
  -H "Authorization: Bearer eyJ0eXAi..."
```

The scanner will automatically:
- Run immediately on startup
- Run every 30 minutes to discover new files
- Extract metadata from video files using ffprobe

## API Endpoints

### Setup (First-Run Only)
- `GET /api/v1/setup/status` - Check if setup is complete
- `POST /api/v1/setup/admin` - Create first admin account (only works once)

### Authentication
- `POST /api/v1/auth/login` - Login and get tokens
- `POST /api/v1/auth/register` - Register new user
- `POST /api/v1/auth/refresh` - Refresh access token
- `POST /api/v1/auth/logout` - Logout and revoke refresh token

### User Management
- `GET /api/v1/users/me` - Get current user profile
- `PATCH /api/v1/users/me` - Update current user profile
- `GET /api/v1/users` - List all users (admin only)
- `GET /api/v1/users/{user_id}` - Get user by ID (admin only)
- `PATCH /api/v1/users/{user_id}` - Update user (admin only)
- `DELETE /api/v1/users/{user_id}` - Delete user (admin only)

### Library Management (Admin Only)
- `GET /api/v1/library-paths` - List all configured library paths
- `POST /api/v1/library-paths` - Add a new library path
- `DELETE /api/v1/library-paths/{path_id}` - Remove a library path

### Media Files (Authenticated)
- `GET /api/v1/media-files` - List all discovered media files
- `GET /api/v1/media-files/{media_id}` - Get specific media file details

### Movies (Authenticated)
- `GET /api/v1/movies` - List all movies
- `GET /api/v1/movies/{movie_id}` - Get specific movie details

### Streaming (Optional Auth)
- `GET /api/v1/stream/{media_id}` - Stream video file with Range request support

### Health
- `GET /health` - Health check endpoint

## Streaming Example

The streaming endpoint supports both header and query parameter authentication for browser compatibility.

**Using Authorization header:**
```bash
curl -X GET "http://localhost:8000/api/v1/stream/1" \
  -H "Authorization: Bearer eyJ0eXAi..." \
  --output video.mp4
```

**Using query parameter (for HTML5 video tags):**
```html
<video controls>
  <source src="http://localhost:8000/api/v1/stream/1?api_key=eyJ0eXAi..." type="video/mp4">
</video>
```

The query parameter method enables browser-based video players to work without custom headers.

The streaming endpoint supports HTTP Range requests for seeking and progressive download.

## Database Migrations

Create a new migration after model changes:

```bash
alembic revision --autogenerate -m "Description of changes"
```

Apply migrations:

```bash
alembic upgrade head
```

Rollback migrations:

```bash
alembic downgrade -1
```

## Project Structure

```
ferelix-server/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app with scheduler & CORS
│   ├── models.py            # Database models & Pydantic schemas
│   ├── database.py          # Database configuration
│   ├── dependencies.py      # Auth dependencies
│   ├── routers/
│   │   └── v1/
│   │       ├── auth.py      # Authentication endpoints
│   │       ├── users.py     # User management endpoints
│   │       ├── media.py     # Media management endpoints
│   │       └── streaming.py # Video streaming endpoint
│   └── services/
│       ├── auth.py          # JWT & password hashing
│       ├── scanner.py       # Media library scanner
│       └── setup.py         # First-run setup service
├── alembic/
│   ├── versions/            # Migration scripts
│   └── env.py              # Alembic environment config
├── alembic.ini             # Alembic configuration
├── pyproject.toml          # Project dependencies
├── AGENTS.md               # AI agent technical documentation
└── README.md
```

## Development

The project uses:
- **uv**: Fast Python package manager and environment manager
- **FastAPI**: Modern web framework
- **SQLAlchemy**: SQL databases with async support
- **Pydantic**: Data validation and serialization
- **Alembic**: Database migrations
- **APScheduler**: Scheduled tasks
- **python-jose**: JWT token handling
- **passlib**: Password hashing with bcrypt
- **aiofiles**: Async file operations
- **aiosqlite**: Async SQLite driver

### Common Commands

```bash
# Sync dependencies
uv sync

# Add a new dependency
uv add package-name

# Run development server
fastapi dev

# Run production server
fastapi run

# Run migrations
uv run alembic upgrade head

# Create new migration
uv run alembic revision --autogenerate -m "description"

# Rollback migration
uv run alembic downgrade -1
```

## Security Considerations

### Production Deployment

1. **SECRET_KEY**: Auto-generated in Docker, or set manually with `openssl rand -hex 32` for non-Docker deployments
2. **Use HTTPS**: Never transmit tokens over unencrypted connections
3. **Restrict CORS**: Set specific origins instead of `*` in production
4. **Database**: SQLite is fine for small deployments, PostgreSQL for larger ones (you manage your own PostgreSQL server)
5. **Firewall Configuration**: Only expose necessary ports
6. **Regular Updates**: Keep dependencies updated for security patches

### Token Security

- Access tokens expire after 30 minutes (configurable)
- Refresh tokens expire after 7 days (configurable)
- Refresh tokens are hashed before database storage
- Tokens can be revoked via logout endpoint
- Multiple device support via device_info tracking

### Password Requirements

The system uses bcrypt for password hashing. Consider implementing:
- Minimum password length requirements
- Password complexity rules
- Rate limiting on login attempts
- Password reset functionality (TODO)

## Future Enhancements

- [ ] Movie metadata lookup (TMDb, OMDb)
- [ ] TV show support with season/episode tracking
- [ ] Transcoding support for different formats
- [ ] Subtitle support
- [ ] Watch history and resume playback
- [ ] Password reset functionality
- [ ] Rate limiting on authentication endpoints
- [ ] Mobile and web clients
- [ ] Two-factor authentication (2FA)
- [ ] External authentication providers (OAuth2)


## License

See LICENSE file for details.
