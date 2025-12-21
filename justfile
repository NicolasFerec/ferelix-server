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
    cd server && uv run fastapi dev

# Start development web client (frontend Vite)
dev-web:
    sleep 1
    cd web && pnpm dev

# Start both server and web client in parallel
[parallel]
dev: dev-server dev-web
