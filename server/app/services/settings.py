"""Settings service for managing scheduler job configuration."""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Settings
from app.services.scanner import cleanup_deleted_media, scan_all_libraries

logger = logging.getLogger(__name__)


async def scan_all_libraries_job():
    """Wrapper to call scan_all_libraries with scheduler from global context."""
    from app.dependencies import get_scheduler

    scheduler_instance = get_scheduler()
    return await scan_all_libraries(scheduler_instance)


async def get_or_create_settings(session: AsyncSession) -> Settings:
    """Get settings or create default if they don't exist.

    Args:
        session: Database session

    Returns:
        Settings instance
    """
    settings = await session.get(Settings, 1)
    if not settings:
        settings = Settings()
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


def initialize_scheduler_jobs(scheduler: AsyncIOScheduler, settings: Settings) -> None:
    """Initialize scheduler jobs based on settings.

    Args:
        scheduler: APScheduler instance
        settings: Settings instance
    """
    # Schedule periodic library scans
    scheduler.add_job(
        scan_all_libraries_job,
        "interval",
        minutes=settings.library_scan_interval_minutes,
        id="library_scanner",
        replace_existing=True,
    )

    # Schedule cleanup job
    scheduler.add_job(
        cleanup_deleted_media,
        "cron",
        hour=settings.cleanup_schedule_hour,
        minute=settings.cleanup_schedule_minute,
        id="database_maintenance",
        replace_existing=True,
        kwargs={"grace_period_days": settings.cleanup_grace_period_days},
    )

    logger.info(f"Scheduled library scanner (every {settings.library_scan_interval_minutes} minutes)")
    logger.info(
        f"Scheduled cleanup job (daily at {settings.cleanup_schedule_hour:02d}:{settings.cleanup_schedule_minute:02d}, "
        f"grace period: {settings.cleanup_grace_period_days} days)"
    )


def update_scheduler_jobs(scheduler: AsyncIOScheduler, settings: Settings) -> None:
    """Update scheduler jobs when settings change.

    Args:
        scheduler: APScheduler instance
        settings: Updated settings instance
    """
    # Update library scanner job - reschedule with new interval
    job = scheduler.get_job("library_scanner")
    if job:
        scheduler.reschedule_job(
            "library_scanner",
            trigger="interval",
            minutes=settings.library_scan_interval_minutes,
        )
        logger.info(f"Updated library scanner interval to {settings.library_scan_interval_minutes} minutes")

    # Update cleanup job - reschedule with new cron schedule and update kwargs
    job = scheduler.get_job("database_maintenance")
    if job:
        scheduler.reschedule_job(
            "database_maintenance",
            trigger="cron",
            hour=settings.cleanup_schedule_hour,
            minute=settings.cleanup_schedule_minute,
        )
        # Update kwargs separately
        scheduler.modify_job(
            "database_maintenance",
            kwargs={"grace_period_days": settings.cleanup_grace_period_days},
        )
        logger.info(
            f"Updated cleanup job schedule to daily at {settings.cleanup_schedule_hour:02d}:{settings.cleanup_schedule_minute:02d}, "
            f"grace period: {settings.cleanup_grace_period_days} days"
        )
