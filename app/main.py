"""
Main FastAPI application entry point
"""
import logging
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

from app.api import leads, bookings, chat, faq
from app.config import settings
from app.services.calendar_webhook_service import calendar_webhook_service
from app.webhooks import meta_webhook, calendar_webhook

logger = logging.getLogger(__name__)

# -------- Media upload config (Docker/Apache) --------
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", "./media"))
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "http://localhost:8080/media")

VIDEO_DIR = MEDIA_ROOT / "videos"
IMAGE_DIR = MEDIA_ROOT / "images"

IS_VERCEL = os.getenv("VERCEL") == "1"

ALLOWED = {
    "video/mp4": ("videos", ".mp4"),
    "video/webm": ("videos", ".webm"),
    "image/jpeg": ("images", ".jpg"),
    "image/png": ("images", ".png"),
    "image/webp": ("images", ".webp"),
    "image/gif": ("images", ".gif"),
}

MAX_BYTES = 50 * 1024 * 1024  # 50MB (justera vid behov)

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
    logger.info("Starting up...")

    if not IS_VERCEL:
        VIDEO_DIR.mkdir(parents=True, exist_ok=True)
        IMAGE_DIR.mkdir(parents=True, exist_ok=True)

    if settings.google_calendar_id and settings.google_service_account and settings.google_calendar_webhook_url:
        result = calendar_webhook_service.setup_webhook()
        if result.get("success"):
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

    logger.info("Shutting down...")
    if scheduler.running:
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
    allow_origins=[
        "http://localhost:5173",
        "https://le-fitness-ai-frontend.vercel.app/",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(meta_webhook.router, prefix="/webhooks/meta", tags=["webhooks"])
app.include_router(calendar_webhook.router, prefix="/webhooks/calendar", tags=["webhooks"])
app.include_router(leads.router, prefix="/api/leads", tags=["leads"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["bookings"])
app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(faq.router, prefix="/api/faq", tags=["faq"])


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if IS_VERCEL:
        raise HTTPException(status_code=501, detail="Local media upload is disabled on Vercel")

    if file.content_type not in ALLOWED:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")

    folder, default_ext = ALLOWED[file.content_type]
    ext = Path(file.filename).suffix.lower() or default_ext
    filename = f"{uuid.uuid4().hex}{ext}"

    target_dir = VIDEO_DIR if folder == "videos" else IMAGE_DIR
    dest = target_dir / filename

    data = await file.read()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large")

    dest.write_bytes(data)

    public_url = f"{MEDIA_BASE_URL}/{folder}/{filename}"
    return {"url": public_url, "content_type": file.content_type}


@app.get("/")
async def root():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": "1.0.0"
    }


@app.get("/health")
async def health():
    return {"status": "healthy"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)