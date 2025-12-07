"""Main FastAPI application with scheduled media scanning."""

import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.v1 import auth, media, streaming, users
from app.services.scanner import scan_all_libraries
from app.services.setup import SetupMiddleware
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
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("Starting Ferelix Server...")

    # Run initial scan
    logger.info("Running initial library scan...")
    await scan_all_libraries()

    # Schedule periodic scans (every 30 minutes)
    scheduler.add_job(
        scan_all_libraries,
        "interval",
        minutes=30,
        id="library_scanner",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Scheduled scanner started (running every 30 minutes)")

    yield

    # Shutdown
    logger.info("Shutting down Ferelix Server...")
    scheduler.shutdown()
    logger.info("Scheduler stopped")


app = FastAPI(title="Ferelix Server", version="0.1.0", lifespan=lifespan)

# Add CORS middleware
allowed_origins = os.getenv("ALLOWED_ORIGINS", "*")
origins = (
    [origin.strip() for origin in allowed_origins.split(",")]
    if allowed_origins != "*"
    else ["*"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add setup middleware (must be added after CORS)
app.add_middleware(SetupMiddleware)

# Include routers (v1 API)
app.include_router(setup_router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(media.router)
app.include_router(streaming.router)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}
