"""
Main FastAPI application entry point
"""
import os
import time
import uvicorn
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import leads, bookings, chat, faq
from app.config import settings
from app.database.database import ensure_db
from app.services.calendar_webhook_service import calendar_webhook_service
from app.webhooks import meta_webhook, calendar_webhook

IS_VERCEL = os.getenv("VERCEL") == "1"

ALLOWED = {
    "video/mp4": ("videos", ".mp4"),
    "video/webm": ("videos", ".webm"),
    "image/jpeg": ("images", ".jpg"),
    "image/png": ("images", ".png"),
    "image/webp": ("images", ".webp"),
    "image/gif": ("images", ".gif"),
}

MAX_BYTES = 50 * 1024 * 1024  # 50MB

# Global scheduler instance
scheduler = AsyncIOScheduler()


def renew_webhook_job():
    """Job function to renew calendar webhook (called by scheduler)"""
    print("Renewing calendar webhook (scheduled job)...")
    result = calendar_webhook_service.renew_webhook()
    if result.get("success"):
        print("Calendar webhook renewed successfully")
    else:
        print(f"Failed to renew webhook: {result.get('error')}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle events for the app"""
    startup_total_start = time.perf_counter()
    print("Starting up...")

    db_start = time.perf_counter()
    print("Running ensure_db()...")
    ensure_db()
    print("ensure_db() done")
    print("ensure_db() took", (time.perf_counter() - db_start) * 1000, "ms")

    # Warm up FAQ components AND the OpenAI HTTP connection at startup.
    # _get_components() only creates the objects — the first real embedder.run()
    # call still pays SSL/connection cost (~6000ms). We run a dummy embedding
    # here so that cost is paid at startup, not on the first user request.
    try:
        import asyncio as _asyncio
        from app.ai.faq_handler import _get_components

        def _faq_warmup():
            store, embedder, retriever = _get_components()
            # Run a real (tiny) embedding to warm up the OpenAI HTTP connection
            embedder.run(text="warmup")

        warmup_start = time.perf_counter()
        loop = _asyncio.get_event_loop()
        await loop.run_in_executor(None, _faq_warmup)
        print("FAQ warmup (incl. OpenAI connection) took", (time.perf_counter() - warmup_start) * 1000, "ms")
    except Exception as _e:
        print("FAQ warmup failed (non-critical):", _e)

    if settings.google_calendar_id and settings.google_service_account and settings.google_calendar_webhook_url:
        calendar_start = time.perf_counter()
        result = calendar_webhook_service.setup_webhook()
        print(
            "calendar_webhook_service.setup_webhook took",
            (time.perf_counter() - calendar_start) * 1000,
            "ms"
        )

        if result.get("success"):
            scheduler.add_job(
                renew_webhook_job,
                trigger=IntervalTrigger(days=6),
                id="renew_calendar_webhook",
                replace_existing=True
            )
            scheduler.start()
            print("Calendar webhook set up and auto-renewal scheduled (every 6 days)")
        else:
            print(f"Failed to set up calendar webhook: {result.get('error')}")
    else:
        print("Calendar webhook not configured - skipping setup")

    print("Startup total took", (time.perf_counter() - startup_total_start) * 1000, "ms")

    yield

    shutdown_start = time.perf_counter()
    print("Shutting down...")

    if scheduler.running:
        scheduler.shutdown()
    if calendar_webhook_service.channel_id:
        calendar_webhook_service.stop_webhook()

    print("Shutdown total took", (time.perf_counter() - shutdown_start) * 1000, "ms")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
    lifespan=lifespan
)


@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start) * 1000
    print(f"HTTP {request.method} {request.url.path} completed in {duration_ms:.2f} ms status={response.status_code}")
    return response


def get_allowed_origins() -> list[str]:
    raw = os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173"
    )
    return [origin.strip().rstrip("/") for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=False,
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
    """
    Upload is no longer handled via local disk/Apache.
    Keep endpoint for compatibility, but make current behavior explicit.
    """
    if file.content_type not in ALLOWED:
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {file.content_type}")

    raise HTTPException(
        status_code=501,
        detail="Local upload is disabled. Upload media to Blob storage and save the returned URL instead."
    )


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