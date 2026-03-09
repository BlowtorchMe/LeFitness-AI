"""
Conversation flow orchestration - guides users through booking process
"""
import logging
import urllib.parse
from datetime import datetime, timedelta
from typing import Dict, Optional

from app.ai.conversation_state import ConversationState, ConversationFlowManager
from app.config import settings
from app.integrations.google_calendar import GoogleCalendar
from app.integrations.messenger_api import MessengerAPI
from app.models.booking import AppointmentType
from app.models.lead import LeadStatus
from app.services.booking_service import BookingService
from app.services.lead_service import LeadService

logger = logging.getLogger(__name__)


class ConversationFlow:
    """Orchestrates the conversation flow from welcome to booking confirmation"""

    def __init__(self):
        self.flow_manager = ConversationFlowManager()
        self.messenger_api = MessengerAPI()

        # ✅ Best practice: Calendar integration is OPTIONAL locally.
        # If service account/json is not available, we keep going without crashing.
        self.calendar: Optional[GoogleCalendar] = None
        try:
            self.calendar = GoogleCalendar()
        except Exception as e:
            self.calendar = None
            logger.warning(
                "GoogleCalendar not configured. Running without calendar integration. Error: %s",
                str(e),
            )

    async def handle_state_transition(
        self,
        lead,
        current_state: str,
        user_message: str,
        intent: str,
        lead_service: LeadService,
        booking_service: BookingService,
    ) -> Dict:
        """
        Handle conversation state transitions and guide user through flow

        Returns:
            Dict with response message, next state, and actions
        """
        state = ConversationState(current_state)
        sender_id = lead.messenger_id or lead.phone

        # State-specific handling
        if state == ConversationState.PROFILE_COMPLETE:
            return await self._recommend_booking(lead, sender_id, lead_service)

        elif state == ConversationState.RECOMMENDING_BOOKING:
            if intent == "book":
                return await self._collect_booking_details(lead, sender_id, booking_service)
            else:
                return await self._continue_recommending(lead, sender_id)

        elif state == ConversationState.COLLECTING_BOOKING_DETAILS:
            return await self._confirm_booking_details(lead, user_message, sender_id, booking_service)

        elif state == ConversationState.CONFIRMING_BOOKING:
            if intent in ["book", "greeting"]:
                return await self._create_booking(lead, sender_id, booking_service, lead_service)

        elif state == ConversationState.BOOKING_CONFIRMED:
            return await self._send_booking_confirmation(lead, sender_id)

        return {"message": None, "next_state": current_state}

    async def _recommend_booking(self, lead, sender_id: str, lead_service: LeadService) -> Dict:
        """Proactively recommend booking after profile complete - provide appointment schedule link"""
        calendar_link = self._get_calendar_link(datetime.now())

        message = (
            f"Perfect, {lead.name}! Now let's get you booked for your free {settings.free_trial_days}-day trial at {settings.gym_name}!\n\n"
            f"You'll get:\n✅ Full gym access\n✅ All equipment\n✅ Group training classes\n✅ Personal gym tour\n\n"
            f"Please book your appointment at a time that works best for you using this link:\n{calendar_link}\n\n"
            f"Once you've booked, I'll confirm everything for you!"
        )

        self.messenger_api.send_message(recipient_id=sender_id, message=message)

        # Update state
        lead.conversation_state = ConversationState.RECOMMENDING_BOOKING.value
        lead.notes = "waiting_for_calendar_booking"
        lead_service.db.commit()

        return {
            "message": message,
            "next_state": ConversationState.RECOMMENDING_BOOKING.value,
            "action": "recommend_booking",
        }

    async def _continue_recommending(self, lead, sender_id: str) -> Dict:
        """Continue recommending booking - provide appointment schedule link again"""
        calendar_link = self._get_calendar_link(datetime.now())

        message = (
            "Our free trial is a great way to experience everything we offer! "
            "Please use this link to book your appointment at a time that works best for you:\n"
            f"{calendar_link}"
        )

        self.messenger_api.send_message(recipient_id=sender_id, message=message)

        return {"message": message, "next_state": ConversationState.RECOMMENDING_BOOKING.value}

    async def _collect_booking_details(self, lead, sender_id: str, booking_service: BookingService) -> Dict:
        """
        Provide appointment schedule link for booking
        User books directly via Google Calendar Appointment Schedule
        """
        calendar_link = self._get_calendar_link(datetime.now())

        message = (
            "Great! Please use this link to book your appointment at a time that works best for you:\n"
            f"{calendar_link}\n\nOnce you've booked, I'll confirm everything for you!"
        )

        self.messenger_api.send_message(recipient_id=sender_id, message=message)

        # Set flag to wait for calendar booking
        lead.notes = "waiting_for_calendar_booking"
        booking_service.db.commit()

        return {"message": message, "next_state": ConversationState.RECOMMENDING_BOOKING.value}

    def _get_calendar_link(self, date: datetime) -> str:
        """
        Get booking link.

        ✅ Best option: Google Appointment Schedule link (no service-account auth needed)
        ✅ Fallback: show calendar by calendar-id
        ✅ Last resort: "create event" template link
        """
        # 1) Best option - stable, no auth required
        if getattr(settings, "google_appointment_schedule_link", None):
            return settings.google_appointment_schedule_link

        # 2) Next best - calendar view link (also no auth)
        if getattr(settings, "google_calendar_id", None):
            calendar_id_encoded = urllib.parse.quote(settings.google_calendar_id, safe="")
            return f"https://calendar.google.com/calendar/u/0/r?cid={calendar_id_encoded}"

        # 3) Last resort - create-event template link
        start_time = date.replace(hour=9, minute=0, second=0, microsecond=0)
        end_time = start_time + timedelta(hours=1)
        start_str = start_time.strftime("%Y%m%dT%H%M%S")
        end_str = end_time.strftime("%Y%m%dT%H%M%S")

        return (
            "https://calendar.google.com/calendar/render?"
            "action=TEMPLATE"
            f"&text=Free Trial - {urllib.parse.quote(settings.gym_name)}"
            f"&dates={start_str}/{end_str}"
            "&details=Book your free trial appointment"
            f"&location={urllib.parse.quote(settings.gym_name)}"
        )

    async def _confirm_booking_details(
        self, lead, user_message: str, sender_id: str, booking_service: BookingService
    ) -> Dict:
        """Confirm booking details before creating"""
        appointment_time = datetime.now() + timedelta(days=1)
        appointment_time = appointment_time.replace(hour=14, minute=0, second=0, microsecond=0)

        message = (
            f"Perfect! So you'd like to book:\n📅 Date: {appointment_time.strftime('%B %d, %Y')}\n"
            f"⏰ Time: {appointment_time.strftime('%I:%M %p')}\n\nIs this correct?"
        )

        self.messenger_api.send_quick_replies(
            recipient_id=sender_id,
            message=message,
            quick_replies=[
                {"title": "Yes, Confirm", "payload": "CONFIRM_BOOKING"},
                {"title": "Change Time", "payload": "CHANGE_TIME"},
                {"title": "Change Date", "payload": "CHANGE_DATE"},
            ],
        )

        lead.notes = f"proposed_booking:{appointment_time.isoformat()}"
        booking_service.db.commit()

        return {
            "message": message,
            "next_state": ConversationState.CONFIRMING_BOOKING.value,
            "proposed_time": appointment_time,
        }

    async def _create_booking(
        self, lead, sender_id: str, booking_service: BookingService, lead_service: LeadService
    ) -> Dict:
        """Create the actual booking"""
        proposed_time_str = (
            lead.notes.split("proposed_booking:", 1)[1]
            if lead.notes and "proposed_booking:" in lead.notes
            else None
        )

        if proposed_time_str:
            appointment_time = datetime.fromisoformat(proposed_time_str)
        else:
            appointment_time = datetime.now() + timedelta(days=1)
            appointment_time = appointment_time.replace(hour=14, minute=0, second=0, microsecond=0)

        result = booking_service.create_booking(
            customer_name=lead.name,
            phone=lead.phone or lead.messenger_id,
            email=lead.email,
            appointment_time=appointment_time,
            appointment_type=AppointmentType.TRIAL_ACTIVATION,
            lead_id=lead.id,
        )

        if result.get("success"):
            lead_service.update_lead_status(lead.id, LeadStatus.BOOKED)
            lead.conversation_state = ConversationState.BOOKING_CONFIRMED.value
            lead.notes = None
            booking_service.db.commit()

            return {
                "message": "Booking created successfully",
                "next_state": ConversationState.BOOKING_CONFIRMED.value,
                "booking": result.get("booking"),
            }

        return {
            "message": "Sorry, there was an error creating your booking. Please try again or call us.",
            "next_state": ConversationState.RECOMMENDING_BOOKING.value,
            "error": result.get("error"),
        }

    async def _send_booking_confirmation(self, lead, sender_id: str) -> Dict:
        """Send booking confirmation message"""
        message = f"""🎉 Perfect! Your booking is confirmed!

You're all set for your free trial at {settings.gym_name}. You'll receive a confirmation email shortly with all the details.

We're excited to welcome you! If you have any questions before your visit, just let me know."""
        self.messenger_api.send_message(recipient_id=sender_id, message=message)

        return {"message": message, "next_state": ConversationState.BOOKING_CONFIRMED.value}