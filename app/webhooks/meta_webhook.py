"""
META (Facebook/Instagram) webhook handler
Supports both Facebook Messenger and Instagram Direct Messages
"""
from datetime import datetime, timedelta
from typing import Optional, Dict

from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from sqlalchemy import desc

from app.ai.chat_handler import ChatHandler
from app.ai.conversation_flow import ConversationFlow
from app.config import settings
from app.database.database import get_db
from app.integrations.meta_api import MetaAPI
from app.integrations.messenger_api import MessengerAPI
from app.integrations.mock_meta_api import MockMetaAPI, MockMessengerAPI
from app.models.conversation import ConversationChannel, MessageDirection, Conversation
from app.services.booking_service import BookingService
from app.services.lead_service import LeadService
from app.services.conversation_service import ConversationService

# Use real Meta APIs - only use mocks if explicitly enabled AND no access token
use_mocks = (settings.use_mock_apis or settings.test_mode) and not settings.meta_access_token

if use_mocks:
    print("[WARNING] Using MOCK APIs - messages will NOT be sent to real users!")
    meta_api = MockMetaAPI()
    messenger_api = MockMessengerAPI()
else:
    if not settings.meta_access_token:
        print("[WARNING] META_ACCESS_TOKEN not set - messages cannot be sent!")
    else:
        print("[INFO] Using REAL Meta APIs")
    meta_api = MetaAPI()
    messenger_api = MessengerAPI()

router = APIRouter()

# Initialize chat_handler - handle errors gracefully for Vercel
# ChatHandler now handles missing API keys gracefully
chat_handler = ChatHandler()


class MetaWebhookData(BaseModel):
    """META webhook payload model"""
    object: Optional[str] = None
    entry: Optional[list] = None


@router.get("/")
async def verify_webhook(
    mode: str = Query(..., alias="hub.mode"),
    token: str = Query(..., alias="hub.verify_token"),
    challenge: str = Query(..., alias="hub.challenge")
):
    """Verify META webhook"""
    # Debug logging (remove in production)
    print(f"[WEBHOOK VERIFY] mode={mode}, token={token}, expected={settings.meta_verify_token}")
    
    challenge_response = meta_api.verify_webhook(mode, token, challenge)
    
    if challenge_response:
        return PlainTextResponse(challenge)
    else:
        raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/")
async def handle_webhook(request: Request):
    """
    Handle META webhook events
    Supports both Facebook Messenger and Instagram Direct Messages
    """
    data = await request.json()
    
    # Handle different webhook events
    if data.get("object") == "page":
        # Facebook Messenger events
        for entry in data.get("entry", []):
            # Handle messaging events (messages, postbacks, etc.)
            messaging_events = entry.get("messaging", [])
            
            for event in messaging_events:
                # CRITICAL: Ignore echo events (bot's own messages) to prevent infinite loops
                message = event.get("message", {})
                if message.get("is_echo"):
                    print("[WEBHOOK] Ignoring echo event (bot's own message)")
                    continue
                
                # Ignore delivery/read events
                if "delivery" in event or "read" in event:
                    print("[WEBHOOK] Ignoring delivery/read event")
                    continue
                
                # Process real user messages
                await handle_messaging_event(event, ConversationChannel.MESSENGER)
            
            # Handle opt-in events (Click-to-Message ad clicks)
            optin_events = entry.get("messaging", [])
            for event in optin_events:
                # Ignore echo events for opt-in too
                message = event.get("message", {})
                if message.get("is_echo"):
                    continue
                
                if event.get("optin"):
                    await handle_optin_event(event, ConversationChannel.MESSENGER)
    
    elif data.get("object") == "instagram":
        # Instagram Direct Message events (same Send API, different channel for storage)
        for entry in data.get("entry", []):
            messaging_events = entry.get("messaging", [])
            
            for event in messaging_events:
                message = event.get("message", {})
                if message.get("is_echo"):
                    print("[WEBHOOK] Ignoring echo event (bot's own message)")
                    continue
                if "delivery" in event or "read" in event:
                    print("[WEBHOOK] Ignoring delivery/read event")
                    continue
                await handle_messaging_event(event, ConversationChannel.INSTAGRAM)
    
    return {"status": "ok"}


async def handle_messaging_event(event: Dict, channel: ConversationChannel):
    """
    Handle individual messaging event
    Works for both Facebook Messenger and Instagram Direct Messages
    """
    # CRITICAL: Double-check for echo events (extra safety layer)
    message = event.get("message", {})
    if message.get("is_echo"):
        print("[MESSAGING EVENT] Ignoring echo event (bot's own message)")
        return
    
    # Ignore delivery/read events
    if "delivery" in event or "read" in event:
        print("[MESSAGING EVENT] Ignoring delivery/read event")
        return
    
    sender_id = event.get("sender", {}).get("id")
    
    if not sender_id:
        print("[MESSAGING EVENT] No sender_id found")
        return
    
    # Handle postback (button clicks)
    if event.get("postback"):
        payload = event.get("postback", {}).get("payload", "")
        await handle_postback(sender_id, payload, channel)
        return
    
    # Handle regular text messages
    message_text = message.get("text", "")
    
    # Ignore empty messages (attachments, quick replies without text, etc.)
    if not message_text:
        print("[MESSAGING EVENT] No message text found, ignoring")
        return
    
    # Get or create lead
    db = next(get_db())
    lead_service = LeadService(db)
    conversation_service = ConversationService(db)
    
    # Find lead by messenger_id
    lead = lead_service.get_lead_by_messenger_id(sender_id)
    
    if not lead:
        user_info = await get_user_profile(sender_id)
        platform_name = "messenger" if channel == ConversationChannel.MESSENGER else "instagram"
        
        referral = event.get("referral")
        ad_campaign = None
        if referral:
            ad_campaign = referral.get("ref", "")
        
        lead = lead_service.create_lead(
            name=user_info.get("first_name", "Customer"),
            messenger_id=sender_id,
            platform=platform_name,
            email=None,
            source="meta_ad" if referral else platform_name,
            ad_campaign=ad_campaign
        )
        
        status = await gather_profile_info(sender_id, channel, lead, lead_service, conversation_service)
        if status != "complete":
            lead.notes = f"profile_status:{status}"
            lead.conversation_state = "gathering_profile"
        else:
            lead.conversation_state = "profile_complete"
        lead_service.db.commit()
        return
    
    if not lead.conversation_state or lead.conversation_state == "welcome":
        lead.notes = None
        status = await gather_profile_info(sender_id, channel, lead, lead_service, conversation_service)
        if status != "complete":
            lead.notes = f"profile_status:{status}"
            lead.conversation_state = "gathering_profile"
        else:
            lead.conversation_state = "profile_complete"
        lead_service.db.commit()
        return
    
    # Check if we just sent welcome - now start profile gathering
    if lead.notes == "waiting_for_first_response":
        # User responded after welcome - ALWAYS start profile gathering
        lead.notes = None
        
        # Save inbound message first
        conversation_service.save_message(
            lead_id=lead.id,
            channel=channel,
            direction=MessageDirection.INBOUND,
            message_text=message_text,
            messenger_id=sender_id
        )
        lead_service.db.commit()
        
        # Start profile gathering using gather_profile_info (pass existing services)
        status = await gather_profile_info(sender_id, channel, lead, lead_service, conversation_service)
        if status != "complete":
            lead.notes = f"profile_status:{status}"
            lead.conversation_state = "gathering_profile"
        else:
            lead.conversation_state = "profile_complete"
        
        lead_service.db.commit()
        return
    
    # Check if we're in profile gathering mode - prioritize this over AI processing
    if lead.notes and lead.notes.startswith("profile_status:"):
        status = lead.notes.split(":")[1]
        await handle_profile_gathering(sender_id, message_text, status, lead, lead_service, channel)
        return
    
    # Check if profile is complete before processing AI messages
    # If profile is not complete, start gathering
    if not lead.conversation_state or lead.conversation_state == "welcome" or lead.conversation_state == "welcome_sent":
        # Check if we have all profile info
        needs_info = []
        if not lead.name or lead.name == "Customer":
            needs_info.append("name")
        if not lead.email:
            needs_info.append("email")
        if not lead.phone:
            needs_info.append("phone")
        
        if needs_info:
            # Start profile gathering
            status = await gather_profile_info(sender_id, channel, lead)
            if status != "complete":
                lead.notes = f"profile_status:{status}"
                lead.conversation_state = "gathering_profile"
                lead_service.db.commit()
                return
    
    # Check if user is waiting for calendar booking
    if lead.notes == "waiting_for_calendar_booking":
        # If user confirms they booked, acknowledge it
        if any(word in message_text.lower() for word in ["booked", "done", "yes", "confirmed", "scheduled"]):
            calendar_msg = "Great! I'll check the calendar and confirm your booking. You should receive a confirmation email shortly!"
            messenger_api.send_message(recipient_id=sender_id, message=calendar_msg)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=channel,
                direction=MessageDirection.OUTBOUND,
                message_text=calendar_msg,
                messenger_id=sender_id
            )
            lead.notes = "calendar_booking_pending_verification"
            lead_service.db.commit()
            return
        
        # If user asks about booking or calendar, provide the link again
        booking_keywords = ["book", "booking", "calendar", "appointment", "schedule", "time", "plz", "please", "link"]
        if any(keyword in message_text.lower() for keyword in booking_keywords):
            flow = ConversationFlow()
            calendar_link = flow._get_calendar_link(datetime.now())
            
            calendar_msg = f"Please use this link to book your appointment:\n{calendar_link}\n\nOnce you've booked, I'll confirm everything for you!"
            
            messenger_api.send_message(recipient_id=sender_id, message=calendar_msg)
            
            conversation_service.save_message(
                lead_id=lead.id,
                channel=channel,
                direction=MessageDirection.OUTBOUND,
                message_text=calendar_msg,
                messenger_id=sender_id
            )
            lead_service.db.commit()
            return
    
    # Only process AI messages if profile is complete
    # If profile is not complete, we should have handled it above
    current_state = lead.conversation_state or "welcome"
    
    # Don't process AI if we're still gathering profile
    if current_state == "gathering_profile" or (lead.notes and lead.notes.startswith("profile_status:")):
        # Should have been handled above, but just in case
        return
    
    # Process message with AI (state-aware)
    # Load conversation history from database
    conversation_service = ConversationService(lead_service.db)
    conversation_history = conversation_service.get_conversation_history_for_ai(
        lead_id=lead.id,
        messenger_id=sender_id
    )
    
    ai_response = await chat_handler.process_message(
        user_message=message_text,
        conversation_history=conversation_history,
        customer_info={"name": lead.name, "phone": lead.phone},
        conversation_state=current_state
    )
    
    # Handle state transitions
    flow = ConversationFlow()
    booking_service = BookingService(lead_service.db)
    
    # Check if we should transition state
    if ai_response.get("should_proceed"):
        flow_result = await flow.handle_state_transition(
            lead=lead,
            current_state=current_state,
            user_message=message_text,
            intent=ai_response.get("intent"),
            lead_service=lead_service,
            booking_service=booking_service
        )
        
        # Update state if changed
        if flow_result.get("next_state") != current_state:
            lead.conversation_state = flow_result.get("next_state")
            lead_service.db.commit()
        
        # If flow handled the response, don't send AI response
        if flow_result.get("message"):
            return
    
    # Send AI response via Messenger/Instagram
    response_text = ai_response.get("response", "")
    
    # Use structured messages for better UX
    intent = ai_response.get("intent")
    next_state = ai_response.get("next_state")
    
    # Update conversation state
    if next_state and next_state != current_state:
        lead.conversation_state = next_state
        lead_service.db.commit()
    
    # Update inbound message with intent
    if intent:
        # Update the most recent inbound message with intent
        recent_conv = conversation_service.db.query(Conversation).filter(
            Conversation.lead_id == lead.id,
            Conversation.direction == MessageDirection.INBOUND,
            Conversation.messenger_id == sender_id
        ).order_by(desc(Conversation.created_at)).first()
        if recent_conv:
            recent_conv.intent = intent
            conversation_service.db.commit()
    
    # Check if user is asking for calendar link
    calendar_keywords = ["calendar", "full calendar", "available", "time slot", "time slots", "schedule", "appointment", "book time", "see calendar", "view calendar", "book", "booking"]
    is_calendar_request = any(keyword in message_text.lower() for keyword in calendar_keywords)
    
    # If user asks for calendar/booking, provide appointment schedule link
    if is_calendar_request and current_state in ["profile_complete", "recommending_booking", "collecting_booking_details"]:
        flow = ConversationFlow()
        
        # Provide appointment schedule link directly
        calendar_link = flow._get_calendar_link(datetime.now())
        
        calendar_msg = f"Perfect! Please use this link to book your appointment at a time that works best for you:\n{calendar_link}\n\nOnce you've booked, I'll confirm everything for you!"
        
        messenger_api.send_message(recipient_id=sender_id, message=calendar_msg)
        
        # Save outbound message
        conversation_service.save_message(
            lead_id=lead.id,
            channel=channel,
            direction=MessageDirection.OUTBOUND,
            message_text=calendar_msg,
            messenger_id=sender_id,
            ai_response=calendar_msg,
            intent="book"
        )
        
        lead.notes = "waiting_for_calendar_booking"
        lead.conversation_state = "recommending_booking"
        lead_service.db.commit()
        return
    
    # Send response with appropriate structure
    if intent == "book" and current_state in ["profile_complete", "recommending_booking"]:
        # Show booking options
        messenger_api.send_quick_replies(
            recipient_id=sender_id,
            message=response_text,
            quick_replies=[
                {"title": "Tomorrow", "payload": "BOOK_TOMORROW"},
                {"title": "This Week", "payload": "BOOK_THIS_WEEK"},
                {"title": "Next Week", "payload": "BOOK_NEXT_WEEK"}
            ]
        )
        # Save outbound message
        conversation_service.save_message(
            lead_id=lead.id,
            channel=channel,
            direction=MessageDirection.OUTBOUND,
            message_text=response_text,
            messenger_id=sender_id,
            ai_response=response_text,
            intent=intent
        )
    else:
        messenger_api.send_message(recipient_id=sender_id, message=response_text)
        # Save outbound message
        conversation_service.save_message(
            lead_id=lead.id,
            channel=channel,
            direction=MessageDirection.OUTBOUND,
            message_text=response_text,
            messenger_id=sender_id,
            ai_response=response_text,
            intent=intent
        )
    
    # Update lead
    lead_service.increment_message_count(lead.id)


async def handle_optin_event(event: Dict, channel: ConversationChannel):
    """
    Handle opt-in event (Click-to-Message ad click)
    This is triggered when user clicks on a Click-to-Message ad
    """
    sender_id = event.get("sender", {}).get("id")
    optin_data = event.get("optin", {})
    ref = optin_data.get("ref", "")  # Ad reference ID
    
    # Get or create lead
    db = next(get_db())
    lead_service = LeadService(db)
    
    # Check if lead already exists
    lead = lead_service.get_lead_by_messenger_id(sender_id)
    
    if not lead:
        user_info = await get_user_profile(sender_id)
        platform_name = "messenger" if channel == ConversationChannel.MESSENGER else "instagram"
        
        lead = lead_service.create_lead(
            name=user_info.get("first_name", "Customer"),
            messenger_id=sender_id,
            platform=platform_name,
            email=None,
            source="meta_ad",
            ad_campaign=ref
        )
    
    conversation_service = ConversationService(lead_service.db)
    
    lead.notes = None
    status = await gather_profile_info(sender_id, channel, lead, lead_service, conversation_service)
    if status != "complete":
        lead.notes = f"profile_status:{status}"
        lead.conversation_state = "gathering_profile"
    else:
        lead.conversation_state = "profile_complete"
    
    lead_service.db.commit()


async def handle_profile_gathering(
    sender_id: str,
    message_text: str,
    status: str,
    lead,
    lead_service: LeadService,
    channel: ConversationChannel
):
    """Handle profile information gathering"""
    conversation_service = ConversationService(lead_service.db)
    
    if status == "waiting_for_name":
        # Extract name from message
        if message_text.strip():
            lead.name = message_text.strip()
            lead_service.db.commit()
        
        # Move to next step (pass existing services)
        status = await gather_profile_info(sender_id, channel, lead, lead_service, conversation_service)
        lead.notes = f"profile_status:{status}" if status != "complete" else None
        lead_service.db.commit()
        
        if status == "complete":
            # All info gathered, transition to recommending booking
            lead.conversation_state = "profile_complete"
            lead.notes = None
            lead_service.db.commit()
            
            flow = ConversationFlow()
            booking_service = BookingService(lead_service.db)
            await flow._recommend_booking(lead, sender_id, lead_service)
    
    elif status == "waiting_for_email":
        # Extract email from message (simple validation)
        if "@" in message_text:
            lead.email = message_text.strip()
            lead_service.db.commit()
        
        # Move to next step (pass existing services)
        status = await gather_profile_info(sender_id, channel, lead, lead_service, conversation_service)
        lead.notes = f"profile_status:{status}" if status != "complete" else None
        lead_service.db.commit()
        
        if status == "complete":
            # Profile complete - transition to recommending booking
            lead.conversation_state = "profile_complete"
            lead.notes = None
            lead_service.db.commit()
            
            flow = ConversationFlow()
            booking_service = BookingService(lead_service.db)
            await flow._recommend_booking(lead, sender_id, lead_service)
    
    elif status == "waiting_for_phone":
        # Extract phone from message
        # Remove common separators
        phone = message_text.strip().replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
        if phone and (phone.isdigit() or phone.startswith("+")):
            lead.phone = phone
            lead_service.db.commit()
        
        # Profile gathering complete - transition to recommending booking
        lead.conversation_state = "profile_complete"
        lead.notes = None
        lead_service.db.commit()
        
        flow = ConversationFlow()
        booking_service = BookingService(lead_service.db)
        await flow._recommend_booking(lead, sender_id, lead_service)


async def handle_postback(sender_id: str, payload: str, channel: ConversationChannel):
    """Handle postback events (button clicks)"""
    db = next(get_db())
    lead_service = LeadService(db)
    booking_service = BookingService(db)
    lead = lead_service.get_lead_by_messenger_id(sender_id)
    
    if payload == "new_conversation_started":
        if not lead:
            user_info = await get_user_profile(sender_id)
            platform_name = "messenger" if channel == ConversationChannel.MESSENGER else "instagram"
            
            lead = lead_service.create_lead(
                name=user_info.get("first_name", "Customer"),
                messenger_id=sender_id,
                platform=platform_name,
                email=None,
                source="meta_ad",
                ad_campaign=None
            )
        
        conversation_service = ConversationService(lead_service.db)
        
        status = await gather_profile_info(sender_id, channel, lead, lead_service, conversation_service)
        if status != "complete":
            lead.notes = f"profile_status:{status}"
            lead.conversation_state = "gathering_profile"
        else:
            lead.conversation_state = "profile_complete"
        lead_service.db.commit()
        return
    
    if not lead:
        return
    
    current_state = lead.conversation_state or "welcome"
    
    # Handle booking-related postbacks
    if payload == "BOOK_NOW" or payload.startswith("BOOK_"):
        flow = ConversationFlow()
        
        if payload in ["BOOK_TOMORROW", "BOOK_THIS_WEEK", "BOOK_NEXT_WEEK"]:
            # User selected time preference
            await flow._collect_booking_details(lead, sender_id, booking_service)
            lead.conversation_state = "collecting_booking_details"
            lead_service.db.commit()
        elif payload.startswith("BOOK_TIME_"):
            # User selected specific time
            time_str = payload.replace("BOOK_TIME_", "")
            appointment_time = datetime.fromisoformat(time_str)
            lead.notes = f"proposed_booking:{appointment_time.isoformat()}"
            await flow._confirm_booking_details(lead, f"Time: {appointment_time.strftime('%H:%M')}", sender_id, booking_service)
            lead.conversation_state = "confirming_booking"
            lead_service.db.commit()
        elif payload == "CONFIRM_BOOKING":
            # User confirmed booking
            await flow._create_booking(lead, sender_id, booking_service, lead_service)
        elif payload == "BOOK_MORE_TIMES":
            tomorrow = datetime.now() + timedelta(days=1)
            slots = booking_service.get_available_slots(tomorrow)
            
            if len(slots) > 3:
                # Show next 3 slots
                time_buttons = []
                for slot in slots[3:6]:  # Next 3 slots
                    time_str = datetime.fromisoformat(slot["start"]).strftime("%H:%M")
                    time_buttons.append({
                        "type": "postback",
                        "title": time_str,
                        "payload": f"BOOK_TIME_{slot['start']}"
                    })
                
                # Always offer calendar link as option
                time_buttons.append({
                    "type": "web_url",
                    "title": "View Full Calendar",
                    "url": flow._get_calendar_link(tomorrow)
                })
                
                messenger_api.send_button_template(
                    recipient_id=sender_id,
                    text="Here are more available times:",
                    buttons=time_buttons
                )
            else:
                # No more slots, offer calendar link
                messenger_api.send_button_template(
                    recipient_id=sender_id,
                    text="For more time options, you can view our full calendar:",
                    buttons=[{
                        "type": "web_url",
                        "title": "Open Calendar",
                        "url": flow._get_calendar_link(tomorrow)
                    }]
                )
                # Set flag to follow up if user books via calendar
                lead.notes = "waiting_for_calendar_booking"
                lead.updated_at = datetime.utcnow()  # Update timestamp for follow-up task
                lead_service.db.commit()
        elif payload.startswith("BOOK_MORNING") or payload.startswith("BOOK_AFTERNOON") or payload.startswith("BOOK_EVENING"):
            tomorrow = datetime.now() + timedelta(days=1)
            
            time_range = {
                "BOOK_MORNING": (9, 12),
                "BOOK_AFTERNOON": (12, 17),
                "BOOK_EVENING": (17, 20)
            }[payload]
            
            slots = booking_service.get_available_slots(tomorrow)
            # Filter slots by time range
            filtered_slots = [
                s for s in slots 
                if time_range[0] <= datetime.fromisoformat(s["start"]).hour < time_range[1]
            ]
            
            if filtered_slots:
                # Show available slots in that range
                time_buttons = []
                for slot in filtered_slots[:3]:
                    time_str = datetime.fromisoformat(slot["start"]).strftime("%H:%M")
                    time_buttons.append({
                        "type": "postback",
                        "title": time_str,
                        "payload": f"BOOK_TIME_{slot['start']}"
                    })
                
                messenger_api.send_button_template(
                    recipient_id=sender_id,
                    text=f"Great! Here are available times in that range:",
                    buttons=time_buttons
                )
            else:
                # No slots in that range, offer calendar
                messenger_api.send_button_template(
                    recipient_id=sender_id,
                    text="I don't see available slots in that time range. Would you like to view the full calendar?",
                    buttons=[{
                        "type": "web_url",
                        "title": "View Calendar",
                        "url": flow._get_calendar_link(tomorrow)
                    }]
                )
                lead.notes = "waiting_for_calendar_booking"
                lead.updated_at = datetime.utcnow()  # Update timestamp for follow-up task
                lead_service.db.commit()
        else:
            # General book now
            await flow._collect_booking_details(lead, sender_id, booking_service)
            lead.conversation_state = "collecting_booking_details"
            lead_service.db.commit()
    
    elif payload == "LEARN_MORE":
        # Answer question but guide back to booking
        messenger_api.send_message(
            recipient_id=sender_id,
            message=f"We offer a {settings.free_trial_days}-day free trial period! You'll get full access to our gym, equipment, and group training classes. Would you like to book a tour?"
        )
        # Still in recommending state, guide back
        if current_state == "recommending_booking":
            await flow._continue_recommending(lead, sender_id)
    
    elif payload == "VIEW_PRICES":
        messenger_api.send_message(
            recipient_id=sender_id,
            message="Our membership prices start at [price]. Would you like to schedule a free trial first? It's completely free - no commitment!"
        )
        # Guide back to booking
        if current_state == "recommending_booking":
            await flow._continue_recommending(lead, sender_id)
    elif payload in ["SHARE_NAME", "SHARE_EMAIL", "SHARE_PHONE"]:
        # User wants to share info - they'll type it in next message
        if payload == "SHARE_NAME":
            messenger_api.send_message(
                recipient_id=sender_id,
                message="Perfect! Please type your full name."
            )
            # Set status to waiting for name
            if lead:
                lead.notes = "profile_status:waiting_for_name"
                lead_service.db.commit()
        elif payload == "SHARE_EMAIL":
            messenger_api.send_message(
                recipient_id=sender_id,
                message="Great! Please type your email address."
            )
            # Set status to waiting for email
            if lead:
                lead.notes = "profile_status:waiting_for_email"
                lead_service.db.commit()
        elif payload == "SHARE_PHONE":
            messenger_api.send_message(
                recipient_id=sender_id,
                message="Perfect! Please type your phone number."
            )
            # Set status to waiting for phone
            if lead:
                lead.notes = "profile_status:waiting_for_phone"
                lead_service.db.commit()
    elif payload in ["SKIP_NAME", "SKIP_EMAIL", "SKIP_PHONE"]:
        # User skipped this field, continue to next
        if lead:
            current_status = lead.notes.split(":")[1] if lead.notes and ":" in lead.notes else None
            if current_status:
                # Move to next step
                status = await gather_profile_info(sender_id, channel, lead)
                if status == "complete":
                    messenger_api.send_quick_replies(
                        recipient_id=sender_id,
                        message="Perfect! Now let's book your free trial appointment.",
                        quick_replies=[
                            {"title": "Book Now", "payload": "BOOK_NOW"},
                            {"title": "Learn More", "payload": "LEARN_MORE"},
                            {"title": "View Prices", "payload": "VIEW_PRICES"}
                        ]
                    )


async def get_user_profile(user_id: str, platform: str = "facebook") -> Dict:
    """
    Get user profile from META API
    Note: Facebook and Instagram have different user IDs and different available fields
    """
    # Use the global meta_api instance (which may be mock in test mode)
    return meta_api.get_user_profile(user_id, platform)


async def gather_profile_info(sender_id: str, channel: ConversationChannel, lead, lead_service: LeadService = None, conversation_service: ConversationService = None):
    """
    Gather user profile information: name, email, phone (in that order).
    """
    platform = "facebook" if channel == ConversationChannel.MESSENGER else "instagram"
    
    user_info = await get_user_profile(sender_id, platform)
    
    if not lead_service:
        db = next(get_db())
        lead_service = LeadService(db)
    if not conversation_service:
        conversation_service = ConversationService(lead_service.db)
    
    needs_info = []
    
    name_from_api = user_info.get("full_name") or user_info.get("first_name")
    if not lead.name or lead.name == "Customer" or (name_from_api and lead.name == name_from_api):
        needs_info.append("name")
    
    if not lead.email:
        needs_info.append("email")
    
    if not lead.phone:
        needs_info.append("phone")
    
    if (not lead.name or lead.name == "Customer") and (user_info.get("first_name") or user_info.get("full_name")):
        lead.name = user_info.get("full_name") or user_info.get("first_name", "Customer")
        lead_service.db.commit()
    
    if needs_info:
        if "name" in needs_info:
            profile_msg = "Please enter your name:"
            messenger_api.send_message(recipient_id=sender_id, message=profile_msg)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=channel,
                direction=MessageDirection.OUTBOUND,
                message_text=profile_msg,
                messenger_id=sender_id,
                intent="gather_profile_name"
            )
            return "waiting_for_name"
        elif "email" in needs_info:
            profile_msg = "Please enter your email address:"
            messenger_api.send_message(recipient_id=sender_id, message=profile_msg)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=channel,
                direction=MessageDirection.OUTBOUND,
                message_text=profile_msg,
                messenger_id=sender_id,
                intent="gather_profile_email"
            )
            return "waiting_for_email"
        elif "phone" in needs_info:
            profile_msg = "Please enter your phone number:"
            messenger_api.send_message(recipient_id=sender_id, message=profile_msg)
            conversation_service.save_message(
                lead_id=lead.id,
                channel=channel,
                direction=MessageDirection.OUTBOUND,
                message_text=profile_msg,
                messenger_id=sender_id,
                intent="gather_profile_phone"
            )
            return "waiting_for_phone"
    
    return "complete"

