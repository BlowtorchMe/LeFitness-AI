"""
Main FastAPI application entry point
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.webhooks import meta_webhook, calendar_webhook
from app.api import leads, bookings, chat, faq
from app.services.calendar_webhook_service import calendar_webhook_service
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
import uvicorn

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = AsyncIOScheduler()

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
    
    if settings.google_calendar_id and settings.google_service_account and settings.google_calendar_webhook_url:
        result = calendar_webhook_service.setup_webhook()
        if result.get("success"):
            # Schedule webhook renewal every 6 days (cron-like)
            scheduler.add_job(
                renew_webhook_job,
                trigger=IntervalTrigger(days=6),
                id="renew_calendar_webhook",
                replace_existing=True
            )
            scheduler.start()
            logger.info("✅ Calendar webhook set up and auto-renewal scheduled (every 6 days)")
        else:
            logger.warning(f"Failed to set up calendar webhook: {result.get('error')}")
    else:
        logger.info("Calendar webhook not configured - skipping setup")
    
    yield
    
    # Shutdown: Stop scheduler and webhook
    logger.info("Shutting down...")
    scheduler.shutdown()
    if calendar_webhook_service.channel_id:
        calendar_webhook_service.stop_webhook()

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
#kopplar in endpoints från en annan fil.
app.include_router(meta_webhook.router, prefix="/webhooks/meta", tags=["webhooks"])
app.include_router(calendar_webhook.router, prefix="/webhooks/calendar", tags=["webhooks"])
app.include_router(leads.router, prefix="/api/leads", tags=["leads"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["bookings"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(faq.router, prefix="/api/faq", tags=["faq"])


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

