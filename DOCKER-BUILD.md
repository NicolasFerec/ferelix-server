# Quick Reference - Docker Build & Deployment

## For Project Maintainers

### Building and Pushing Images to Docker Hub

#### Method 1: Using the Build Script (Recommended)

```bash
# Set your Docker Hub username
export DOCKERHUB_USERNAME=your-username

# Build and push a version
./docker-build.sh 1.0.0

# The script will:
# - Login to Docker Hub
# - Build for linux/amd64 and linux/arm64
# - Tag as both :1.0.0 and :latest
# - Push to Docker Hub
```

#### Method 2: Manual Build

```bash
# Login
docker login

# Create buildx builder
docker buildx create --use --name ferelix-builder

# Build and push
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  --tag your-username/ferelix-server:1.0.0 \
  --tag your-username/ferelix-server:latest \
  --push \
  .

# Cleanup
docker buildx rm ferelix-builder
```

#### Method 3: GitHub Actions (Automated)

1. Set up secrets in GitHub:
   - `DOCKERHUB_USERNAME`
   - `DOCKERHUB_TOKEN`

2. Push to main or create a tag:
```bash
# Automatic on push to main
git push origin main

# Or create a version tag
git tag v1.0.0
git push origin v1.0.0
```

### Version Tagging Strategy

- `latest` - Always points to the most recent stable release
- `1.0.0` - Specific version (semantic versioning)
- `1.0` - Major.minor (auto-updated for patches)
- `1` - Major version only
- `main` - Latest development build from main branch
- `dev` - Local development builds

### Release Checklist

- [ ] Update version in relevant files
- [ ] Update CHANGELOG (if exists)
- [ ] Test locally: `docker build -t ferelix-test .`
- [ ] Run test container: `docker run --rm ferelix-test uv run python -c "from app.main import app; print('OK')"`
- [ ] Create git tag: `git tag v1.0.0`
- [ ] Push tag: `git push origin v1.0.0`
- [ ] GitHub Actions will build and push automatically
- [ ] Verify on Docker Hub
- [ ] Update documentation if needed

## For End Users

### Pulling the Image

```bash
# Latest stable version
docker pull your-username/ferelix-server:latest

# Specific version
docker pull your-username/ferelix-server:1.0.0
```

### First Time Setup

1. Create directory:
```bash
mkdir ~/ferelix && cd ~/ferelix
```

2. Create `docker-compose.yml`:
```yaml
version: '3.8'

services:
  ferelix:
    image: your-username/ferelix-server:latest
    container_name: ferelix-server
    restart: unless-stopped
    ports:
      - "8000:8000"
    volumes:
      - ./config:/config
      - /path/to/movies:/media/movies:ro
    environment:
      - SECRET_KEY=CHANGE_THIS_RUN_openssl_rand_-hex_32
      - DATABASE_URL=sqlite+aiosqlite:///config/ferelix.db
```

3. Generate secret:
```bash
openssl rand -hex 32
```

4. Update `docker-compose.yml` with the generated secret

5. Start:
```bash
docker-compose up -d
```

6. Create admin:
```bash
curl -X POST "http://localhost:8000/api/v1/setup/admin" \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","email":"admin@example.com","password":"secure-password"}'
```

### Updating to Latest Version

```bash
# Pull new image
docker-compose pull

# Recreate container with new image
docker-compose up -d

# Verify
docker-compose logs -f
```

### Rolling Back

```bash
# Update docker-compose.yml to use specific version
# image: your-username/ferelix-server:1.0.0

# Recreate container
docker-compose up -d
```

## Troubleshooting

### Build Fails

```bash
# Check Dockerfile syntax
docker run --rm -i hadolint/hadolint < Dockerfile

# Build with verbose output
docker build --progress=plain --no-cache .
```

### Push Fails

```bash
# Verify login
docker login

# Check image exists
docker images | grep ferelix

# Manually push
docker push your-username/ferelix-server:latest
```

### Multi-platform Build Issues

```bash
# Install QEMU
docker run --privileged --rm tonistiigi/binfmt --install all

# Verify platforms
docker buildx ls

# Create new builder
docker buildx create --name multiarch --use
docker buildx inspect --bootstrap
```

## Useful Commands

```bash
# Check image size
docker images your-username/ferelix-server

# Inspect image
docker inspect your-username/ferelix-server:latest

# Test image locally
docker run --rm -it \
  -e SECRET_KEY=$(openssl rand -hex 32) \
  -e DATABASE_URL=sqlite+aiosqlite:////tmp/test.db \
  -p 8000:8000 \
  your-username/ferelix-server:latest

# Scan for vulnerabilities (requires Docker Scout)
docker scout cves your-username/ferelix-server:latest
```

## Links

- Docker Hub: https://hub.docker.com/r/your-username/ferelix-server
- GitHub: https://github.com/your-username/ferelix-server
- Documentation: See README.md and DOCKER.md
