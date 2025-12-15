"""
META (Facebook/Instagram) webhook handler
Supports both Facebook Messenger and Instagram Direct Messages
"""
from fastapi import APIRouter, Request, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, Dict
from app.config import settings
from app.integrations.meta_api import MetaAPI
from app.integrations.messenger_api import MessengerAPI

# Use real Meta APIs - only use mocks if explicitly enabled AND no access token
use_mocks = (settings.use_mock_apis or settings.test_mode) and not settings.meta_access_token

if use_mocks:
    print("[WARNING] Using MOCK APIs - messages will NOT be sent to real users!")
    from app.integrations.mock_meta_api import MockMetaAPI, MockMessengerAPI
    meta_api = MockMetaAPI()
    messenger_api = MockMessengerAPI()
else:
    if not settings.meta_access_token:
        print("[WARNING] META_ACCESS_TOKEN not set - messages cannot be sent!")
    else:
        print("[INFO] Using REAL Meta APIs")
    meta_api = MetaAPI()
    messenger_api = MessengerAPI()
from app.services.lead_service import LeadService
from app.services.booking_service import BookingService
from app.ai.chat_handler import ChatHandler
from app.database.database import get_db
from app.models.conversation import ConversationChannel
from datetime import datetime

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
        # Return challenge as plain text (Meta expects the challenge string)
        from fastapi.responses import PlainTextResponse
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
        # Instagram Direct Message events
        for entry in data.get("entry", []):
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
                
                await handle_messaging_event(event, ConversationChannel.MESSENGER)  # Same API
    
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
    
    # Find lead by messenger_id
    lead = lead_service.get_lead_by_messenger_id(sender_id)
    
    if not lead:
        # Create new lead from first message
        # Try to get user profile info from META API (but we'll still ask user for complete info)
        user_info = await get_user_profile(sender_id)
        platform_name = "messenger" if channel == ConversationChannel.MESSENGER else "instagram"
        # Don't use email from API - we'll ask user for it
        lead = lead_service.create_lead(
            name=user_info.get("first_name", "Customer"),  # May only be first name
            messenger_id=sender_id,
            platform=platform_name,
            email=None,  # Always ask user for email
            source="meta_ad" if event.get("referral") else platform_name
        )
        
        # Send welcome message ONLY - wait for user response
        welcome_msg = chat_handler.get_welcome_message(lead.name if lead.name != "Customer" else None)
        messenger_api.send_message(recipient_id=sender_id, message=welcome_msg)
        
        # Set state to wait for user response before asking profile questions
        lead.conversation_state = "welcome_sent"
        lead.notes = "waiting_for_first_response"
        lead_service.db.commit()
        
        # Don't process the message yet - wait for user to respond
        return
    
    # Check if we just sent welcome - now start profile gathering
    if lead.notes == "waiting_for_first_response":
        # User responded after welcome - ALWAYS start profile gathering
        # Force asking for profile info even if some exists
        lead.notes = None
        
        # Check what we need - always ask unless explicitly provided by user
        needs_info = []
        if not lead.name or lead.name == "Customer":
            needs_info.append("name")
        if not lead.email:
            needs_info.append("email")
        if not lead.phone:
            needs_info.append("phone")
        
        # If we need any info, start gathering
        if needs_info:
            if "name" in needs_info:
                messenger_api.send_quick_replies(
                    recipient_id=sender_id,
                    message="Great! To get started, could you please share your name?",
                    quick_replies=[
                        {"title": "Yes, my name is...", "payload": "SHARE_NAME"},
                        {"title": "Skip for now", "payload": "SKIP_NAME"}
                    ]
                )
                lead.notes = "profile_status:waiting_for_name"
                lead.conversation_state = "gathering_profile"
            elif "email" in needs_info:
                messenger_api.send_quick_replies(
                    recipient_id=sender_id,
                    message="Perfect! What's your email address? We'll send you a booking confirmation.",
                    quick_replies=[
                        {"title": "Share Email", "payload": "SHARE_EMAIL"},
                        {"title": "Skip", "payload": "SKIP_EMAIL"}
                    ]
                )
                lead.notes = "profile_status:waiting_for_email"
                lead.conversation_state = "gathering_profile"
            elif "phone" in needs_info:
                messenger_api.send_quick_replies(
                    recipient_id=sender_id,
                    message="And finally, what's your phone number? We'll send you reminders.",
                    quick_replies=[
                        {"title": "Share Phone", "payload": "SHARE_PHONE"},
                        {"title": "Skip", "payload": "SKIP_PHONE"}
                    ]
                )
                lead.notes = "profile_status:waiting_for_phone"
                lead.conversation_state = "gathering_profile"
        else:
            # All info already collected - move to booking
            lead.conversation_state = "profile_complete"
            lead.notes = None
        
        lead_service.db.commit()
        return
    
    # Check if we're in profile gathering mode - prioritize this over AI processing
    if lead.notes and lead.notes.startswith("profile_status:"):
        status = lead.notes.split(":")[1]
        await handle_profile_gathering(sender_id, message_text, status, lead, lead_service, channel)
        return
    
    # Check if profile is complete before processing AI messages
    # If profile is not complete, start gathering
    if not lead.conversation_state or lead.conversation_state == "welcome":
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
    
    # Check if user is confirming calendar booking
    if lead.notes == "waiting_for_calendar_booking":
        # User might be confirming they booked via calendar
        if any(word in message_text.lower() for word in ["booked", "done", "yes", "confirmed", "scheduled"]):
            messenger_api.send_message(
                recipient_id=sender_id,
                message="Great! I'll check the calendar and confirm your booking. You should receive a confirmation email shortly!"
            )
            # Try to match calendar event (simplified - would need proper implementation)
            # For now, just clear the flag and let staff verify
            lead.notes = "calendar_booking_pending_verification"
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
    conversation_history = []  # TODO: Load from database
    
    ai_response = await chat_handler.process_message(
        user_message=message_text,
        conversation_history=conversation_history,
        customer_info={"name": lead.name, "phone": lead.phone},
        conversation_state=current_state
    )
    
    # Handle state transitions
    from app.ai.conversation_flow import ConversationFlow
    from app.services.booking_service import BookingService
    
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
    else:
        messenger_api.send_message(recipient_id=sender_id, message=response_text)
    
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
        # Get user profile
        user_info = await get_user_profile(sender_id)
        platform_name = "messenger" if channel == ConversationChannel.MESSENGER else "instagram"
        
        # Create lead from ad click (but we'll still ask user for complete info)
        lead = lead_service.create_lead(
            name=user_info.get("first_name", "Customer"),  # May only be first name
            messenger_id=sender_id,
            platform=platform_name,
            email=None,  # Always ask user for email
            source="meta_ad",
            ad_campaign=ref
        )
    
    # Send welcome message ONLY - wait for user response
    welcome_msg = chat_handler.get_welcome_message(lead.name if lead.name != "Customer" else None)
    messenger_api.send_message(recipient_id=sender_id, message=welcome_msg)
    
    # Set state to wait for user response before asking profile questions
    lead.conversation_state = "welcome_sent"
    lead.notes = "waiting_for_first_response"
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
    
    if status == "waiting_for_name":
        if message_text.lower() not in ["skip", "skip for now"]:
            # Extract name from message
            lead.name = message_text.strip()
            lead_service.db.commit()
        
        # Move to next step
        status = await gather_profile_info(sender_id, channel, lead)
        lead.notes = f"profile_status:{status}" if status != "complete" else None
        lead_service.db.commit()
        
        if status == "complete":
            # All info gathered, transition to recommending booking
            lead.conversation_state = "profile_complete"
            lead.notes = None
            lead_service.db.commit()
            
            # Proactively recommend booking
            from app.ai.conversation_flow import ConversationFlow
            from app.services.booking_service import BookingService
            flow = ConversationFlow()
            booking_service = BookingService(lead_service.db)
            await flow._recommend_booking(lead, sender_id, lead_service)
    
    elif status == "waiting_for_email":
        if message_text.lower() not in ["skip"]:
            # Extract email from message (simple validation)
            if "@" in message_text:
                lead.email = message_text.strip()
                lead_service.db.commit()
        
        # Move to next step
        status = await gather_profile_info(sender_id, channel, lead)
        lead.notes = f"profile_status:{status}" if status != "complete" else None
        lead_service.db.commit()
        
        if status == "complete":
            # Profile complete - transition to recommending booking
            lead.conversation_state = "profile_complete"
            lead.notes = None
            lead_service.db.commit()
            
            # Proactively recommend booking
            from app.ai.conversation_flow import ConversationFlow
            from app.services.booking_service import BookingService
            flow = ConversationFlow()
            booking_service = BookingService(lead_service.db)
            await flow._recommend_booking(lead, sender_id, lead_service)
    
    elif status == "waiting_for_phone":
        if message_text.lower() not in ["skip"]:
            # Extract phone from message
            # Remove common separators
            phone = message_text.strip().replace("-", "").replace(" ", "").replace("(", "").replace(")", "")
            if phone.isdigit() or phone.startswith("+"):
                lead.phone = phone
                lead_service.db.commit()
        
        # Profile gathering complete - transition to recommending booking
        lead.conversation_state = "profile_complete"
        lead.notes = None
        lead_service.db.commit()
        
        # Proactively recommend booking (agent leads conversation)
        from app.ai.conversation_flow import ConversationFlow
        from app.services.booking_service import BookingService
        flow = ConversationFlow()
        booking_service = BookingService(lead_service.db)
        await flow._recommend_booking(lead, sender_id, lead_service)


async def handle_postback(sender_id: str, payload: str, channel: ConversationChannel):
    """Handle postback events (button clicks)"""
    db = next(get_db())
    lead_service = LeadService(db)
    booking_service = BookingService(db)
    lead = lead_service.get_lead_by_messenger_id(sender_id)
    
    if not lead:
        return
    
    current_state = lead.conversation_state or "welcome"
    
    # Handle booking-related postbacks
    if payload == "BOOK_NOW" or payload.startswith("BOOK_"):
        # User wants to book - transition to collecting details
        from app.ai.conversation_flow import ConversationFlow
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
            # User wants to see more time slots
            # Show next set of slots or offer calendar link
            from datetime import datetime, timedelta
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
            # User selected time preference (morning/afternoon/evening)
            # Find available slot in that time range
            from datetime import datetime, timedelta
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


async def gather_profile_info(sender_id: str, channel: ConversationChannel, lead):
    """
    Gather user profile information after welcome message
    Uses quick replies to collect name, email, phone
    """
    platform = "instagram" if channel == ConversationChannel.MESSENGER and False else "facebook"  # Will be set properly
    platform = "facebook" if channel == ConversationChannel.MESSENGER else "instagram"
    
    # Try to get profile from API first
    user_info = await get_user_profile(sender_id, platform)
    
    # Check what info we already have
    db = next(get_db())
    lead_service = LeadService(db)
    
    # Always ask for profile info in order: name -> email -> phone
    # Meta API might provide first_name, but we still want to collect complete info from user
    needs_info = []
    
    # Check what we need - always ask unless user has already provided complete info
    # For name: ask if missing or if we only have first_name from API
    if not lead.name or lead.name == "Customer":
        needs_info.append("name")
    elif user_info.get("first_name") and lead.name == user_info.get("first_name"):
        # We only have first_name from API, ask for full name
        needs_info.append("name")
    
    # For email: always ask if missing
    if not lead.email:
        needs_info.append("email")
    
    # For phone: always ask if missing
    if not lead.phone:
        needs_info.append("phone")
    
    # If we got info from API, update lead (but we'll still ask user for complete info)
    if user_info.get("first_name") or user_info.get("full_name"):
        if not lead.name or lead.name == "Customer":
            lead.name = user_info.get("full_name") or user_info.get("first_name", "Customer")
            lead_service.db.commit()
    
    # Always ask for profile info - don't skip even if API provided some
    # If we still need info, ask for it
    if needs_info:
        if "name" in needs_info:
            messenger_api.send_quick_replies(
                recipient_id=sender_id,
                message="Great! To get started, could you please share your name?",
                quick_replies=[
                    {"title": "Yes, my name is...", "payload": "SHARE_NAME"},
                    {"title": "Skip for now", "payload": "SKIP_NAME"}
                ]
            )
            return "waiting_for_name"
        
        elif "email" in needs_info:
            messenger_api.send_quick_replies(
                recipient_id=sender_id,
                message="Perfect! What's your email address? We'll send you a booking confirmation.",
                quick_replies=[
                    {"title": "Share Email", "payload": "SHARE_EMAIL"},
                    {"title": "Skip", "payload": "SKIP_EMAIL"}
                ]
            )
            return "waiting_for_email"
        
        elif "phone" in needs_info:
            messenger_api.send_quick_replies(
                recipient_id=sender_id,
                message="And finally, what's your phone number? We'll send you reminders.",
                quick_replies=[
                    {"title": "Share Phone", "payload": "SHARE_PHONE"},
                    {"title": "Skip", "payload": "SKIP_PHONE"}
                ]
            )
            return "waiting_for_phone"
    
    # All info gathered, proceed to booking
    return "complete"

