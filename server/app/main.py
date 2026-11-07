"""Main FastAPI application with scheduled media scanning."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.database import async_session_maker
from app.dependencies import set_scheduler
from app.routers.v1 import auth, dashboard, media, streaming, users
from app.services.jobs import init_job_tracking
from app.services.logging_config import configure_logging, protect_access_logs
from app.services.settings import cleanup_stalled_jobs_job, get_or_create_settings, initialize_scheduler_jobs
from app.services.setup import router as setup_router

# Configure logging
configure_logging()

logger = logging.getLogger(__name__)

# Initialize scheduler
scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    protect_access_logs()
    # Startup
    logger.info("Starting Ferelix Server...")

    # Store scheduler in app state and global variable for API access
    app.state.scheduler = scheduler
    set_scheduler(scheduler)

    # Start scheduler before initializing jobs
    scheduler.start()

    try:
        # Initialize job tracking (must be after scheduler.start())
        init_job_tracking(scheduler)

        # Get or create settings and initialize scheduler jobs
        async with async_session_maker() as session:
            settings = await get_or_create_settings(session)
            initialize_scheduler_jobs(scheduler, settings)

        # Clean up any stalled transcoding jobs from previous server restart
        try:
            cleaned_count = await cleanup_stalled_jobs_job()
            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} stalled transcoding jobs at startup")
        except Exception:
            logger.exception("Failed to cleanup stalled jobs at startup")

        yield
    finally:
        # Shutdown
        logger.info("Shutting down Ferelix Server...")

        # Run final cleanup of transcode files before shutdown
        try:
            final_cleanup_count = await cleanup_stalled_jobs_job()
            if final_cleanup_count > 0:
                logger.info(f"Final cleanup removed {final_cleanup_count} transcoding jobs on shutdown")
        except Exception:
            logger.exception("Failed to run final cleanup on shutdown")

        scheduler.shutdown()
        logger.info("Scheduler stopped")


app = FastAPI(title="Ferelix Server", version="0.1.0", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
def request_validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
    """Report validation failures without echoing non-JSON numbers or credentials."""
    # Pydantic's error input can contain NaN/Infinity, which JSONResponse rejects.
    # Preserve FastAPI's documented error fields and avoid serializing raw input.
    detail = [{key: item[key] for key in ("loc", "msg", "type")} for item in error.errors()]
    return JSONResponse(status_code=422, content={"detail": detail})


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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


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
            raise HTTPException(status_code=404, detail="Not found")

        # Serve index.html for SPA client-side routing
        index_file = STATIC_DIR / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        return {"error": "Frontend not found"}
