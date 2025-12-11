"""Main FastAPI application with scheduled media scanning."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.dependencies import set_scheduler
from app.routers.v1 import auth, dashboard, media, streaming, users
from app.services.jobs import init_job_tracking
from app.services.scanner import cleanup_deleted_media, scan_all_libraries
from app.services.setup import router as setup_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Initialize scheduler
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: RUF029
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("Starting Ferelix Server...")

    # Schedule periodic scans (every 30 minutes)
    scheduler.add_job(
        scan_all_libraries,
        "interval",
        minutes=30,
        id="library_scanner",
        replace_existing=True,
        next_run_time=datetime.now(),
    )

    # Schedule cleanup job (daily at 3 AM)
    grace_period_days = int(os.getenv("CLEANUP_GRACE_PERIOD_DAYS", "30"))
    scheduler.add_job(
        cleanup_deleted_media,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_deleted_media",
        replace_existing=True,
        kwargs={"grace_period_days": grace_period_days},
    )

    scheduler.start()
    logger.info("Scheduled scanner started (running every 30 minutes)")
    logger.info(
        f"Cleanup job scheduled (daily at 3 AM, grace period: {grace_period_days} days)"
    )

    # Store scheduler in app state and global variable for API access
    app.state.scheduler = scheduler
    set_scheduler(scheduler)

    # Initialize job tracking (must be after scheduler.start())
    init_job_tracking(scheduler)

    yield

    # Shutdown
    logger.info("Shutting down Ferelix Server...")
    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(title="Ferelix Server", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers (v1 API)
app.include_router(setup_router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(media.router)
app.include_router(streaming.router)
app.include_router(dashboard.router)

# Mount static files for frontend
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    # Mount static assets (JS, CSS, images, etc.)
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve the SPA index.html for all non-API routes."""
        # If path starts with api/, setup/, health - let it fall through to API
        if full_path.startswith(("api/", "setup/", "health")):
            return None

        # Serve index.html for SPA client-side routing
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        return {"error": "Frontend not found"}


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
