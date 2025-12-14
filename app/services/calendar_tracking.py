"""
Calendar booking tracking service
Handles follow-up when users book via calendar link
"""
from typing import List, Dict, Optional
from sqlalchemy.orm import Session
from app.models.lead import Lead
from app.integrations.google_calendar import GoogleCalendar
from app.services.lead_service import LeadService
from datetime import datetime, timedelta


class CalendarTrackingService:
    """Tracks calendar bookings and matches them to leads"""
    
    def __init__(self, db: Session):
        self.db = db
        self.calendar = GoogleCalendar()
        self.lead_service = LeadService(db)
    
    def check_for_calendar_bookings(self, hours_window: int = 24) -> List[Dict]:
        """
        Check for new calendar events that might be from users who used calendar link
        This is a fallback mechanism - not perfect, but helps track some bookings
        
        Args:
            hours_window: Check events created in last N hours
        
        Returns:
            List of potential matches
        """
        try:
            # Get recent events from calendar
            start_time = datetime.utcnow() - timedelta(hours=hours_window)
            end_time = datetime.utcnow() + timedelta(days=30)  # Future events
            
            # Query calendar for events
            # Note: This is a simplified approach - in production, you'd use
            # Google Calendar API to list events
            events = self._get_recent_events(start_time, end_time)
            
            # Try to match events to leads waiting for calendar booking
            matches = []
            waiting_leads = self.db.query(Lead).filter(
                Lead.notes == "waiting_for_calendar_booking"
            ).all()
            
            for lead in waiting_leads:
                # Try to match by name or time proximity
                for event in events:
                    if self._match_event_to_lead(event, lead):
                        matches.append({
                            "lead": lead,
                            "event": event,
                            "confidence": "high" if lead.name in event.get("summary", "") else "medium"
                        })
            
            return matches
        
        except Exception as e:
            return []
    
    def _get_recent_events(self, start_time: datetime, end_time: datetime) -> List[Dict]:
        """Get recent events from Google Calendar"""
        return self.calendar.get_recent_events(start_time=start_time, end_time=end_time)
    
    def _match_event_to_lead(self, event: Dict, lead: Lead) -> bool:
        """Try to match calendar event to lead"""
        event_summary = event.get("summary", "").lower()
        lead_name = lead.name.lower() if lead.name else ""
        
        # Match by name
        if lead_name and lead_name in event_summary:
            return True
        
        # Match by time proximity (if lead was created recently)
        event_time = event.get("start", {}).get("dateTime")
        if event_time and lead.created_at:
            event_dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
            # If event is within 7 days of lead creation, might be a match
            if abs((event_dt - lead.created_at).days) <= 7:
                return True
        
        return False
    
    def follow_up_calendar_link_users(self) -> List[Dict]:
        """
        Follow up with users who clicked calendar link but haven't booked via chat
        """
        # Get leads waiting for calendar booking
        waiting_leads = self.db.query(Lead).filter(
            Lead.notes == "waiting_for_calendar_booking",
            Lead.created_at >= datetime.utcnow() - timedelta(hours=24)
        ).all()
        
        results = []
        for lead in waiting_leads:
            # Check if they booked via calendar
            matches = self.check_for_calendar_bookings()
            lead_matches = [m for m in matches if m["lead"].id == lead.id]
            
            if not lead_matches:
                # No match found - follow up
                results.append({
                    "lead_id": lead.id,
                    "action": "follow_up",
                    "message": "Did you manage to book your appointment? If so, let me know and I'll confirm!"
                })
            else:
                # Found a match - update lead
                match = lead_matches[0]
                lead.notes = f"calendar_booking_matched:{match['event'].get('id')}"
                lead.status = "booked"  # Would need to import LeadStatus
                self.db.commit()
                results.append({
                    "lead_id": lead.id,
                    "action": "matched",
                    "event_id": match["event"].get("id")
                })
        
        return results

