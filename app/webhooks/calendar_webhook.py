"""
Google Calendar webhook handler
Receives push notifications when calendar events are created/updated
"""
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict
from datetime import datetime, timedelta
from app.database.database import get_db
from app.services.lead_service import LeadService
from app.services.booking_service import BookingService
from app.integrations.messenger_api import MessengerAPI
from app.integrations.google_calendar import GoogleCalendar
from app.models.lead import LeadStatus
import json

router = APIRouter()
messenger_api = MessengerAPI()
# Initialize calendar only if configured (lazy initialization)
calendar = None


class CalendarNotification(BaseModel):
    """Google Calendar push notification model"""
    channel_id: Optional[str] = None
    resource_id: Optional[str] = None
    resource_state: Optional[str] = None
    resource_uri: Optional[str] = None
    channel_expiration: Optional[str] = None
    headers: Optional[Dict] = None


@router.post("/")
async def handle_calendar_webhook(request: Request):
    """
    Handle Google Calendar push notifications
    Called when events are created, updated, or deleted
    """
    # Google sends notifications as POST with headers
    headers = dict(request.headers)
    
    # Check if this is a sync notification (initial setup)
    if headers.get("x-goog-resource-state") == "sync":
        # This is just the initial sync, acknowledge it
        return {"status": "ok", "message": "sync acknowledged"}
    
    # Check if this is a change notification
    if headers.get("x-goog-resource-state") in ["exists", "not_exists"]:
        # Calendar has changed - scan for new events
        await process_calendar_changes()
        return {"status": "ok", "message": "change processed"}
    
    # For other cases, just acknowledge
    return {"status": "ok"}


async def process_calendar_changes():
    """
    Process calendar changes - find new events and save all bookings to database
    """
    from app.database.database import SessionLocal
    from app.models.lead import Lead
    from app.models.booking import Booking, AppointmentType, BookingStatus
    from app.config import settings
    
    global calendar
    
    # Only process if calendar is configured
    if not calendar:
        if settings.google_calendar_id and settings.google_service_account:
            # Try to initialize calendar
            try:
                calendar = GoogleCalendar()
            except Exception:
                return  # Calendar not available
        else:
            return  # Calendar not configured
    
    db = SessionLocal()
    try:
        lead_service = LeadService(db)
        booking_service = BookingService(db)
        
        # Get events from last 2 hours (new bookings)
        start_time = datetime.utcnow() - timedelta(hours=2)
        events = calendar.get_recent_events(start_time=start_time) if calendar.service else []
        
        # Process all new events - save to database
        for event in events:
            event_id = event.get("id")
            if not event_id:
                continue
            
            # Check if booking already exists for this event
            existing_booking = db.query(Booking).filter(
                Booking.external_booking_id == event_id
            ).first()
            
            if existing_booking:
                # Already saved, skip
                continue
            
            # Parse event details
            event_start = event.get("start", {}).get("dateTime")
            if not event_start:
                continue
            
            try:
                event_dt = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
            except:
                continue
            
            # Get attendee information
            attendees = event.get("attendees", [])
            attendee_email = attendees[0].get("email") if attendees else None
            attendee_name = attendees[0].get("displayName") if attendees else None
            
            # Extract customer name from event summary or attendee
            event_summary = event.get("summary", "")
            customer_name = attendee_name or event_summary.split("-")[-1].strip() if "-" in event_summary else event_summary or "Customer"
            
            # Try to find matching lead by email or name
            lead = None
            if attendee_email:
                lead = lead_service.get_lead_by_email(attendee_email)
            
            if not lead and customer_name and customer_name != "Customer":
                # Try to find by name
                leads = db.query(Lead).filter(Lead.name.ilike(f"%{customer_name.split()[0]}%")).all()
                if leads:
                    lead = leads[0]  # Take first match
            
            # Calculate duration from event
            event_end = event.get("end", {}).get("dateTime")
            duration_minutes = 60  # Default
            if event_end:
                try:
                    end_dt = datetime.fromisoformat(event_end.replace("Z", "+00:00"))
                    duration_minutes = int((end_dt - event_dt).total_seconds() / 60)
                except:
                    pass
            
            # Create booking in database
            from app.models.booking import AppointmentType
            booking = Booking(
                lead_id=lead.id if lead else None,
                customer_name=customer_name,
                phone=lead.phone if lead else None,
                email=attendee_email,
                appointment_time=event_dt,
                appointment_type=AppointmentType.TRIAL_ACTIVATION,
                duration_minutes=duration_minutes,
                status=BookingStatus.CONFIRMED,
                external_booking_id=event_id,
                calendar_link=event.get("htmlLink")
            )
            
            db.add(booking)
            
            # Update lead if matched
            if lead:
                lead.status = LeadStatus.BOOKED
                lead.notes = f"calendar_booking_saved:{event_id}"
                # Notify user via Messenger/Instagram with confirmation and thanks
                if lead.messenger_id:
                    confirmation_message = (
                        f"Perfect! I've confirmed your booking for {event_dt.strftime('%B %d at %I:%M %p')}.\n\n"
                        f"You should receive a confirmation email shortly with all the details.\n\n"
                        f"Thank you for choosing {settings.gym_name}! We're excited to welcome you and help you start your fitness journey.\n\n"
                        f"If you have any questions before your visit, just let me know. Looking forward to seeing you!"
                    )
                    messenger_api.send_message(
                        recipient_id=lead.messenger_id,
                        message=confirmation_message
                    )
        
        db.commit()
        
    except Exception as e:
        print(f"Error processing calendar changes: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
    finally:
        db.close()


def _match_event_to_lead(event: Dict, lead) -> bool:
    """
    Try to match a calendar event to a lead
    Uses multiple heuristics for matching
    """
    event_summary = event.get("summary", "").lower()
    event_description = event.get("description", "").lower()
    event_attendees = [a.get("email", "").lower() for a in event.get("attendees", [])]
    
    lead_name = (lead.name or "").lower()
    lead_email = (lead.email or "").lower()
    
    # Match by name in event summary/description
    if lead_name and lead_name != "customer":
        # Check if lead name appears in event
        if lead_name in event_summary or lead_name in event_description:
            return True
        
        # Check first name only
        first_name = lead_name.split()[0] if lead_name else ""
        if first_name and len(first_name) > 2:
            if first_name in event_summary or first_name in event_description:
                return True
    
    # Match by email in attendees
    if lead_email and lead_email in event_attendees:
        return True
    
    # Match by time proximity (if lead was created recently)
    event_start = event.get("start", {}).get("dateTime")
    if event_start and lead.created_at:
        try:
            event_dt = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
            # If event is within 7 days of lead creation and in future, might be a match
            if (event_dt > datetime.utcnow() and 
                abs((event_dt - lead.created_at).days) <= 7):
                # Additional check: event title contains keywords
                keywords = ["trial", "tour", "visit", "appointment", "booking", "free"]
                if any(keyword in event_summary for keyword in keywords):
                    return True
        except:
            pass
    
    return False


async def _process_matched_booking(
    lead,
    event: Dict,
    lead_service: LeadService,
    booking_service: BookingService
):
    """
    Process a matched booking - create booking record and notify user
    """
    try:
        # Parse event time
        event_start = event.get("start", {}).get("dateTime")
        if not event_start:
            return
        
        event_dt = datetime.fromisoformat(event_start.replace("Z", "+00:00"))
        
        # Create booking in our system
        booking_result = booking_service.create_booking(
            customer_name=lead.name or "Customer",
            phone=lead.phone,
            email=lead.email,
            appointment_time=event_dt,
            appointment_type="trial_activation",  # Default
            lead_id=lead.id
        )
        
        if booking_result.get("success"):
            # Update lead status
            lead.status = LeadStatus.BOOKED
            lead.booking_id = booking_result["booking"].id
            lead.booking_date = event_dt
            lead.notes = f"calendar_booking_matched:{event.get('id')}"
            lead_service.db.commit()
            
            # Notify user via Messenger/Instagram
            if lead.messenger_id:
                messenger_api.send_message(
                    recipient_id=lead.messenger_id,
                    message=f"Perfect! I found your booking for {event_dt.strftime('%B %d at %I:%M %p')}. "
                           f"You should receive a confirmation email shortly. Looking forward to seeing you!"
                )
    
    except Exception as e:
        print(f"Error processing matched booking: {e}")

