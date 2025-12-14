"""
Celery configuration for background tasks
"""
from celery import Celery
from app.config import settings

celery_app = Celery(
    "lefitness",
    broker=settings.redis_url,
    backend=settings.redis_url
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Import tasks
from app.tasks import reminder_tasks, followup_tasks

