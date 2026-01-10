# List all available commands
default:
    @just --list

# Install all dependencies
install:
    @echo "📦 Installing server dependencies..."
    cd server && uv sync
    @echo "📦 Installing web dependencies..."
    cd web && pnpm install
    @echo "✅ All dependencies installed!"

# Start development server (backend FastAPI)
dev-server:
    cd server && uv run alembic upgrade head && uv run fastapi dev

# Start development web client (frontend Vite)
dev-web:
    sleep 1
    cd web && pnpm dev

# Start both server and web client in parallel
[parallel]
dev: dev-server dev-web

# Run backend tests
test-server:
    cd server && uv run pytest

# Run frontend tests
test-web:
    cd web && pnpm test

# Run all tests (backend + frontend)
test: test-server test-web

# Run server type checks
type-check-server:
    cd server && uv run basedpyright

# Run web type checks
type-check-web:
    cd web && pnpm vue-tsc --noEmit

# Run all type checks (backend + frontend)
type-check: type-check-server type-check-web
tc: type-check
