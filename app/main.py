"""
Main FastAPI application entry point
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.webhooks import meta_webhook, sms_webhook, calendar_webhook
from app.api import leads, bookings

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug
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
app.include_router(meta_webhook.router, prefix="/webhooks/meta", tags=["webhooks"])
app.include_router(sms_webhook.router, prefix="/webhooks/sms", tags=["webhooks"])
app.include_router(calendar_webhook.router, prefix="/webhooks/calendar", tags=["webhooks"])
app.include_router(leads.router, prefix="/api/leads", tags=["leads"])
app.include_router(bookings.router, prefix="/api/bookings", tags=["bookings"])


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
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

