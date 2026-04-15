"""
Booking management service
"""
from typing import Optional, List, Dict
from sqlalchemy.orm import Session
from app.models.booking import Booking, BookingStatus, AppointmentType
from app.integrations.google_calendar import GoogleCalendar
from datetime import datetime, timedelta
from app.models.gym import Gym


class BookingService:
    """Service for managing bookings with Google Calendar"""

    def __init__(self, db: Session):
        self.db = db

    def create_booking(
            self,
            customer_name: str,
            phone: str,
            email: Optional[str],
            appointment_time: datetime,
            gym_slug: str,
            appointment_type: AppointmentType = AppointmentType.TRIAL_ACTIVATION,
            lead_id: Optional[int] = None,
            duration_minutes: int = 60
    ) -> Dict[str, any]:
        """
        Create a booking in Google Calendar
        Google Calendar automatically sends email confirmation to attendees
        
        Returns:
            Dict with booking info and success status
        """
        # If calendar is not configured, simulate creation
        calendar = self._get_calendar(gym_slug)

        use_calendar = getattr(calendar, "service", None) is not None
        end_time = appointment_time + timedelta(minutes=duration_minutes)

        if use_calendar:
            calendar_result = calendar.create_event(
                summary=f"{appointment_type.value.title()} - {customer_name}",
                start_time=appointment_time,
                end_time=end_time,
                description=f"Customer: {customer_name}\nPhone: {phone}\nType: {appointment_type.value}",
                attendee_email=email,
                location=""
            )
            if not calendar_result.get("success"):
                return {
                    "success": False,
                    "error": calendar_result.get("error", "Failed to create calendar event")
                }
        else:
            # Kalendern är inte konfigurerad – simulera ett lyckat resultat
            calendar_result = {"success": True, "event_id": None, "html_link": None, "simulated": True}

        # Create in local database
        booking = Booking(
            lead_id=lead_id,
            customer_name=customer_name,
            phone=phone,
            email=email,
            appointment_time=appointment_time,
            appointment_type=appointment_type,
            duration_minutes=duration_minutes,
            status=BookingStatus.CONFIRMED,
            external_booking_id=calendar_result.get("event_id"),
        )

        self.db.add(booking)
        self.db.commit()
        self.db.refresh(booking)

        # Note: Google Calendar automatically sends email confirmation to attendees
        # when sendUpdates='all' is set (which we do in create_event)
        # No need for custom email service - Google handles it!

        return {
            "success": True,
            "booking": booking,
            "calendar_event_id": calendar_result.get("event_id"),
            "calendar_link": calendar_result.get("html_link")
        }

    def get_available_slots(self, date: datetime, gym_slug: str, duration_minutes: int = 60) -> List[Dict]:
        """Get available booking slots for a date from Google Calendar"""
        calendar = self._get_calendar(gym_slug)
        if getattr(calendar, "service", None) is None:
            return self._mock_slots(date, duration_minutes)
        return calendar.get_available_slots(date, duration_minutes)

    def get_booking(self, booking_id: int) -> Optional[Booking]:
        """Get booking by ID"""
        return self.db.query(Booking).filter(Booking.id == booking_id).first()

    def cancel_booking(self, booking_id: int, gym_slug: str) -> Optional[Booking]:
        """Cancel a booking in Google Calendar"""
        booking = self.get_booking(booking_id)
        if booking:
            # Delete from Google Calendar
            if booking.external_booking_id:
                calendar = self._get_calendar(gym_slug)
                if getattr(calendar, "service", None) is not None:
                    calendar.delete_event(booking.external_booking_id)

            # Update local database
            booking.status = BookingStatus.CANCELLED
            booking.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(booking)
        return booking

    def mark_no_show(self, booking_id: int) -> Optional[Booking]:
        """Mark booking as no-show"""
        booking = self.get_booking(booking_id)
        if booking:
            booking.status = BookingStatus.NO_SHOW
            booking.updated_at = datetime.utcnow()
            self.db.commit()
            self.db.refresh(booking)
        return booking

    def get_bookings_needing_reminder(self, hours_before: int = 2) -> List[Booking]:
        """Get bookings that need reminders"""
        reminder_time = datetime.utcnow() + timedelta(hours=hours_before)

        return self.db.query(Booking).filter(
            Booking.appointment_time <= reminder_time,
            Booking.appointment_time > datetime.utcnow(),
            Booking.status == BookingStatus.CONFIRMED,
            Booking.reminder_sent.is_(None)
        ).all()

    def _mock_slots(self, date: datetime, duration_minutes: int) -> List[Dict]:
        slots = []
        start_hour, end_hour = 9, 18
        current_time = date.replace(hour=start_hour, minute=0, second=0)
        end_time = date.replace(hour=end_hour, minute=0, second=0)
        while current_time + timedelta(minutes=duration_minutes) <= end_time:
            slot_start = current_time
            slot_end = current_time + timedelta(minutes=duration_minutes)
            slots.append({
                "start": slot_start.isoformat(),
                "end": slot_end.isoformat(),
                "display": slot_start.strftime("%H:%M")
            })
            current_time += timedelta(minutes=30)
        return slots

    def _get_calendar(self, gym_slug: str) -> GoogleCalendar:
        gym = self.db.query(Gym).filter(Gym.slug == gym_slug).first()

        if not gym or not gym.calendar_id:
            raise ValueError(f"No Google Calendar configured for gym: {gym_slug}")

        return GoogleCalendar(calendar_id=gym.calendar_id)