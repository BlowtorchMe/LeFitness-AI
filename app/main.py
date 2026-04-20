"""
Main FastAPI application entry point
"""
import logging
import threading
import time
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.ai.chat_handler import ChatHandler
from app.ai.faq_handler import FAQHandler
from app.api import admin, leads, bookings, chat, faq, gyms
from app.config import settings
from app.database.database import ensure_schema
from app.services.calendar_webhook_service import calendar_webhook_service
from app.webhooks import meta_webhook, calendar_webhook

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()
faq_handler = FAQHandler()
chat_handler = ChatHandler()


def _warmup_faq_background():
    """Warm AI components without delaying startup."""
    try:
        time.sleep(3)
        faq_handler.warmup()
        chat_handler.warmup()
    except Exception:
        logger.exception("FAQ warmup failed")


def renew_webhook_job():
    """Job function to renew calendar webhook (called by scheduler)"""
    logger.info("Renewing calendar webhook (scheduled job)...")
    result = calendar_webhook_service.renew_webhook()
    if result.get("success"):
        logger.info("✅ Calendar webhook renewed successfully")
    else:
        logger.error(f"Failed to renew webhook: {result.get('error')}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for the app"""
    # Startup: Set up calendar webhook and scheduler
    logger.info("Starting up...")
    ensure_schema()
    threading.Thread(target=_warmup_faq_background, daemon=True).start()

    # Check if at least one active gym has a calendar_id configured in the DB
    from app.database.database import SessionLocal as _SL
    from app.models.gym import Gym as _Gym
    _db = _SL()
    try:
        _has_gym_calendar = (
            _db.query(_Gym)
            .filter(_Gym.is_active.is_(True), _Gym.calendar_id.isnot(None))
            .first()
        ) is not None
    finally:
        _db.close()

    logger.info(
        "Calendar check: service_account=%s webhook_url=%s gym_with_calendar=%s",
        bool(settings.google_service_account),
        bool(settings.google_calendar_webhook_url),
        _has_gym_calendar,
    )

    has_any_calendar = (
        settings.google_service_account
        and settings.google_calendar_webhook_url
        and _has_gym_calendar
    )

    if has_any_calendar:
        result = calendar_webhook_service.setup_webhook()
        if result.get("success"):
            scheduler.add_job(
                renew_webhook_job,
                trigger=IntervalTrigger(days=6),
                id="renew_calendar_webhook",
                replace_existing=True
            )
            scheduler.start()
            logger.info("Calendar webhook set up and auto-renewal scheduled (every 6 days)")
        else:
            logger.warning("Failed to set up calendar webhook: %s", result.get("error"))
    else:
        logger.info("Calendar webhook not configured - skipping setup")

    yield

    # Shutdown: Stop scheduler and webhook
    logger.info("Shutting down...")
    if scheduler.running:
        scheduler.shutdown()
    # Stoppa alla aktiva webhooks (den fixade versionen hanterar alla gym internt)
    if calendar_webhook_service.active_watches:
        calendar_webhook_service.stop_webhook()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan,
    redirect_slashes=False,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=
    [
        "https://lefitness-ai-frontend.vercel.app",
        "http://localhost:5173",
    ], # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(meta_webhook.router, prefix="/webhooks/meta", tags=["webhooks"])
app.include_router(calendar_webhook.router, prefix="/webhooks/calendar", tags=["webhooks"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(leads.router, prefix="/api/leads", tags=["leads"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["bookings"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(faq.router, prefix="/api/faq", tags=["faq"])
app.include_router(gyms.router, prefix="/api/gyms", tags=["gyms"])


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)