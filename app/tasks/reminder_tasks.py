"""
Reminder background tasks
"""
from app.celery_app import celery_app
from app.services.reminder_service import ReminderService
from app.services.booking_service import BookingService
from app.database.database import SessionLocal


@celery_app.task
def send_appointment_reminders():
    """Send reminders for appointments 2 hours before"""
    db = SessionLocal()
    try:
        booking_service = BookingService(db)
        reminder_service = ReminderService(booking_service)
        results = reminder_service.send_reminders(hours_before=2)
        return {"sent": len(results), "results": results}
    finally:
        db.close()


# Schedule task to run every hour
celery_app.conf.beat_schedule = {
    "send-reminders": {
        "task": "app.tasks.reminder_tasks.send_appointment_reminders",
        "schedule": 3600.0,  # Every hour
    },
}

