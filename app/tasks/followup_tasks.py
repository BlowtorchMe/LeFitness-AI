"""
Follow-up background tasks
"""
import asyncio
from datetime import datetime, timedelta

from app.celery_app import celery_app
from app.database.database import SessionLocal
from app.integrations.google_calendar import GoogleCalendar
from app.integrations.messenger_api import MessengerAPI
from app.models.lead import Lead
from app.services.booking_service import BookingService
from app.services.calendar_tracking import CalendarTrackingService
from app.services.followup_service import FollowupService
from app.services.lead_service import LeadService
from app.webhooks.calendar_webhook import _process_matched_booking


@celery_app.task
def followup_missed_appointments():
    """Follow up with customers who missed appointments"""
    db = SessionLocal()
    try:
        lead_service = LeadService(db)
        followup_service = FollowupService(lead_service)
        results = followup_service.followup_missed_appointments()
        return {"sent": len(results), "results": results}
    finally:
        db.close()


@celery_app.task
def followup_trial_expired():
    """Follow up with customers whose trial period expired"""
    db = SessionLocal()
    try:
        lead_service = LeadService(db)
        followup_service = FollowupService(lead_service)
        results = followup_service.followup_trial_expired()
        return {"sent": len(results), "results": results}
    finally:
        db.close()


@celery_app.task
def followup_calendar_link_users():
    """
    Follow up with users who clicked calendar link
    Ask naturally if they booked (after 2-3 minutes)
    """
    db = SessionLocal()
    try:
        # Find leads who clicked calendar link 2-5 minutes ago
        time_window_start = datetime.utcnow() - timedelta(minutes=5)
        time_window_end = datetime.utcnow() - timedelta(minutes=2)
        
        waiting_leads = db.query(Lead).filter(
            Lead.notes == "waiting_for_calendar_booking",
            Lead.updated_at >= time_window_start,
            Lead.updated_at <= time_window_end
        ).all()
        
        messenger_api = MessengerAPI()
        results = []
        
        for lead in waiting_leads:
            if lead.messenger_id:
                # Natural follow-up message
                message = (
                    f"Hi {lead.name or 'there'}! 👋\n\n"
                    "Just checking in - were you able to book your appointment on the calendar? "
                    "If you did, I'll confirm it right away! If you need help, just let me know."
                )
                
                messenger_api.send_message(
                    recipient_id=lead.messenger_id,
                    message=message
                )
                
                results.append({
                    "lead_id": lead.id,
                    "messenger_id": lead.messenger_id,
                    "status": "follow_up_sent"
                })
        
        return {"sent": len(results), "results": results}
    
    finally:
        db.close()


@celery_app.task
def scan_calendar_for_bookings():
    """
    Periodically scan calendar for new bookings
    This is a backup method if push notifications fail
    """
    db = SessionLocal()
    try:
        calendar = GoogleCalendar()
        tracking_service = CalendarTrackingService(db)
        
        # Check for calendar bookings in last 2 hours
        matches = tracking_service.check_for_calendar_bookings(hours_window=2)
        
        # Process matches (this will create bookings and notify users)
        lead_service = LeadService(db)
        booking_service = BookingService(db)
        
        processed = 0
        if matches:
            for match in matches:
                asyncio.run(_process_matched_booking(
                    match["lead"],
                    match["event"],
                    lead_service,
                    booking_service
                ))
                processed += 1
        
        return {"scanned": True, "matches_found": len(matches), "processed": processed}
    
    finally:
        db.close()




# Schedule tasks
celery_app.conf.beat_schedule.update({
    "followup-missed": {
        "task": "app.tasks.followup_tasks.followup_missed_appointments",
        "schedule": 86400.0,  # Daily
    },
    "followup-trial-expired": {
        "task": "app.tasks.followup_tasks.followup_trial_expired",
        "schedule": 86400.0,  # Daily
    },
    "followup-calendar-link": {
        "task": "app.tasks.followup_tasks.followup_calendar_link_users",
        "schedule": 60.0,  # Every minute (checks for leads in 2-5 min window)
    },
    "scan-calendar-bookings": {
        "task": "app.tasks.followup_tasks.scan_calendar_for_bookings",
        "schedule": 300.0,  # Every 5 minutes
    },
})

