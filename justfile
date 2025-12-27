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

# Run e2e tests
test-e2e:
    cd web && pnpm test:e2e

# Run e2e tests in UI mode
test-e2e-ui:
    cd web && pnpm test:e2e:ui

# Run e2e tests in headed mode (visible browser)
test-e2e-headed:
    cd web && pnpm test:e2e:headed

# Debug e2e tests
test-e2e-debug:
    cd web && pnpm test:e2e:debug

# Show e2e test report
test-e2e-report:
    cd web && pnpm test:e2e:report

# Install Playwright browsers for e2e tests
test-e2e-install:
    cd web && npx playwright install --with-deps chromium
