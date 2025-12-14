"""
Conversation flow orchestration - guides users through booking process
"""
from typing import Dict, Optional
from app.ai.conversation_state import ConversationState, ConversationFlowManager
from app.integrations.messenger_api import MessengerAPI
from app.services.booking_service import BookingService
from app.services.lead_service import LeadService
from datetime import datetime, timedelta
from app.config import settings
from app.integrations.google_calendar import GoogleCalendar


class ConversationFlow:
    """Orchestrates the conversation flow from welcome to booking confirmation"""
    
    def __init__(self):
        self.flow_manager = ConversationFlowManager()
        self.messenger_api = MessengerAPI()
        self.calendar = GoogleCalendar()
    
    async def handle_state_transition(
        self,
        lead,
        current_state: str,
        user_message: str,
        intent: str,
        lead_service: LeadService,
        booking_service: BookingService
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
            # Profile complete - proactively recommend booking
            return await self._recommend_booking(lead, sender_id, lead_service)
        
        elif state == ConversationState.RECOMMENDING_BOOKING:
            if intent == "book":
                # User wants to book - collect details
                return await self._collect_booking_details(lead, sender_id, booking_service)
            else:
                # Still recommending - be more persuasive
                return await self._continue_recommending(lead, sender_id)
        
        elif state == ConversationState.COLLECTING_BOOKING_DETAILS:
            # User provided date/time - confirm details
            return await self._confirm_booking_details(lead, user_message, sender_id, booking_service)
        
        elif state == ConversationState.CONFIRMING_BOOKING:
            if intent in ["book", "greeting"]:
                # User confirmed - create booking
                return await self._create_booking(lead, sender_id, booking_service, lead_service)
        
        elif state == ConversationState.BOOKING_CONFIRMED:
            # Booking confirmed - send confirmation message
            return await self._send_booking_confirmation(lead, sender_id)
        
        return {"message": None, "next_state": current_state}
    
    async def _recommend_booking(self, lead, sender_id: str, lead_service: LeadService) -> Dict:
        """Proactively recommend booking after profile complete"""
        from app.config import settings
        
        message = f"Perfect, {lead.name}! 🎉 Now let's get you booked for your free {settings.free_trial_days}-day trial at {settings.gym_name}!\n\nYou'll get:\n✅ Full gym access\n✅ All equipment\n✅ Group training classes\n✅ Personal gym tour\n\nWhen would you like to visit us?"
        
        self.messenger_api.send_quick_replies(
            recipient_id=sender_id,
            message=message,
            quick_replies=[
                {"title": "Tomorrow", "payload": "BOOK_TOMORROW"},
                {"title": "This Week", "payload": "BOOK_THIS_WEEK"},
                {"title": "Next Week", "payload": "BOOK_NEXT_WEEK"},
                {"title": "Choose Date", "payload": "BOOK_CHOOSE_DATE"}
            ]
        )
        
        # Update state
        lead.conversation_state = ConversationState.RECOMMENDING_BOOKING.value
        lead_service.db.commit()
        
        return {
            "message": message,
            "next_state": ConversationState.RECOMMENDING_BOOKING.value,
            "action": "recommend_booking"
        }
    
    async def _continue_recommending(self, lead, sender_id: str) -> Dict:
        """Continue recommending booking"""
        message = "Our free trial is a great way to experience everything we offer! Would you like to book your appointment now?"
        
        self.messenger_api.send_quick_replies(
            recipient_id=sender_id,
            message=message,
            quick_replies=[
                {"title": "Yes, Book Now", "payload": "BOOK_NOW"},
                {"title": "Tell Me More", "payload": "LEARN_MORE"},
                {"title": "Maybe Later", "payload": "LATER"}
            ]
        )
        
        return {
            "message": message,
            "next_state": ConversationState.RECOMMENDING_BOOKING.value
        }
    
    async def _collect_booking_details(self, lead, sender_id: str, booking_service: BookingService) -> Dict:
        """
        Collect booking date and time
        Primary: Show available time slots as buttons
        Fallback: Offer calendar link for more flexibility
        """
        # Get available slots for tomorrow
        tomorrow = datetime.now() + timedelta(days=1)
        slots = booking_service.get_available_slots(tomorrow)
        
        if slots:
            # Show available time slots as buttons (PRIMARY METHOD)
            time_buttons = []
            for slot in slots[:3]:  # Show first 3 slots
                time_str = datetime.fromisoformat(slot["start"]).strftime("%H:%M")
                time_buttons.append({
                    "type": "postback",
                    "title": time_str,
                    "payload": f"BOOK_TIME_{slot['start']}"
                })
            
            # Add "See More" and "View Calendar" options
            if len(slots) > 3:
                time_buttons.append({
                    "type": "postback",
                    "title": "See More Times",
                    "payload": "BOOK_MORE_TIMES"
                })
            
            # Add calendar link as fallback option
            time_buttons.append({
                "type": "web_url",
                "title": "View Full Calendar",
                "url": self._get_calendar_link(tomorrow)
            })
            
            self.messenger_api.send_button_template(
                recipient_id=sender_id,
                text="Great! Here are some available times for tomorrow. You can select one, or view the full calendar:",
                buttons=time_buttons
            )
            
            # If user chooses calendar link, set flag to follow up
            # (This will be handled in postback handler)
        else:
            # No slots available, ask for preferred time or offer calendar
            self.messenger_api.send_button_template(
                recipient_id=sender_id,
                text="What time works best for you?",
                buttons=[
                    {"type": "postback", "title": "Morning (9-12)", "payload": "BOOK_MORNING"},
                    {"type": "postback", "title": "Afternoon (12-17)", "payload": "BOOK_AFTERNOON"},
                    {"type": "postback", "title": "Evening (17-20)", "payload": "BOOK_EVENING"},
                    {"type": "web_url", "title": "View Calendar", "url": self._get_calendar_link(tomorrow)}
                ]
            )
        
        return {
            "message": "Collecting booking details",
            "next_state": ConversationState.COLLECTING_BOOKING_DETAILS.value
        }
    
    def _get_calendar_link(self, date: datetime) -> str:
        """
        Generate Google Calendar link for viewing/booking
        This opens Google Calendar in a new window
        """
        from app.config import settings
        
        # Create Google Calendar URL with date pre-selected
        # Format: https://calendar.google.com/calendar/render?action=TEMPLATE&dates=...
        start_time = date.replace(hour=9, minute=0)  # Default to 9 AM
        end_time = start_time + timedelta(hours=1)
        
        # Format dates for Google Calendar (YYYYMMDDTHHMMSSZ)
        start_str = start_time.strftime("%Y%m%dT%H%M%S")
        end_str = end_time.strftime("%Y%m%dT%H%M%S")
        
        calendar_url = (
            f"https://calendar.google.com/calendar/render?"
            f"action=TEMPLATE"
            f"&text=Free Trial - {settings.gym_name}"
            f"&dates={start_str}/{end_str}"
            f"&details=Book your free trial appointment"
            f"&location={settings.gym_name}"
        )
        
        return calendar_url
    
    async def _confirm_booking_details(self, lead, user_message: str, sender_id: str, booking_service: BookingService) -> Dict:
        """Confirm booking details before creating"""
        # Parse date/time from message (simplified - would use NLP in production)
        # For now, use tomorrow as default
        appointment_time = datetime.now() + timedelta(days=1)
        appointment_time = appointment_time.replace(hour=14, minute=0)  # 2 PM default
        
        message = f"Perfect! So you'd like to book:\n📅 Date: {appointment_time.strftime('%B %d, %Y')}\n⏰ Time: {appointment_time.strftime('%I:%M %p')}\n\nIs this correct?"
        
        self.messenger_api.send_quick_replies(
            recipient_id=sender_id,
            message=message,
            quick_replies=[
                {"title": "Yes, Confirm", "payload": "CONFIRM_BOOKING"},
                {"title": "Change Time", "payload": "CHANGE_TIME"},
                {"title": "Change Date", "payload": "CHANGE_DATE"}
            ]
        )
        
        # Store proposed booking time in lead notes temporarily
        lead.notes = f"proposed_booking:{appointment_time.isoformat()}"
        booking_service.db.commit()
        
        return {
            "message": message,
            "next_state": ConversationState.CONFIRMING_BOOKING.value,
            "proposed_time": appointment_time
        }
    
    async def _create_booking(self, lead, sender_id: str, booking_service: BookingService, lead_service: LeadService) -> Dict:
        """Create the actual booking"""
        from app.models.booking import AppointmentType
        
        # Get proposed time from notes
        proposed_time_str = lead.notes.split(":")[1] if lead.notes and "proposed_booking:" in lead.notes else None
        
        if proposed_time_str:
            appointment_time = datetime.fromisoformat(proposed_time_str)
        else:
            # Default to tomorrow 2 PM
            appointment_time = datetime.now() + timedelta(days=1)
            appointment_time = appointment_time.replace(hour=14, minute=0)
        
        # Create booking
        result = booking_service.create_booking(
            customer_name=lead.name,
            phone=lead.phone or lead.messenger_id,
            email=lead.email,
            appointment_time=appointment_time,
            appointment_type=AppointmentType.TRIAL_ACTIVATION,
            lead_id=lead.id
        )
        
        if result.get("success"):
            # Update lead status
            from app.models.lead import LeadStatus
            lead_service.update_lead_status(lead.id, LeadStatus.BOOKED)
            lead.conversation_state = ConversationState.BOOKING_CONFIRMED.value
            lead.notes = None
            booking_service.db.commit()
            
            return {
                "message": "Booking created successfully",
                "next_state": ConversationState.BOOKING_CONFIRMED.value,
                "booking": result.get("booking")
            }
        else:
            return {
                "message": "Sorry, there was an error creating your booking. Please try again or call us.",
                "next_state": ConversationState.RECOMMENDING_BOOKING.value,
                "error": result.get("error")
            }
    
    async def _send_booking_confirmation(self, lead, sender_id: str) -> Dict:
        """Send booking confirmation message"""
        from app.ai.prompts import BOOKING_CONFIRMATION
        
        # Get booking details (would load from database)
        message = f"""🎉 Perfect! Your booking is confirmed!

You're all set for your free trial at {settings.gym_name}. You'll receive a confirmation email shortly with all the details.

We're excited to welcome you! If you have any questions before your visit, just let me know."""
        
        self.messenger_api.send_message(recipient_id=sender_id, message=message)
        
        return {
            "message": message,
            "next_state": ConversationState.BOOKING_CONFIRMED.value
        }

