"""
Twilio SMS webhook handler
"""
from fastapi import APIRouter, Request, Form
from typing import Optional
from app.integrations.twilio_sms import TwilioSMS
from app.services.lead_service import LeadService
from app.services.booking_service import BookingService
from app.ai.chat_handler import ChatHandler
from app.database.database import get_db
from datetime import datetime

router = APIRouter()
sms = TwilioSMS()
chat_handler = ChatHandler()


@router.post("/")
async def handle_sms_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(...),
    To: str = Form(...)
):
    """
    Handle incoming SMS webhook from Twilio
    
    Args:
        From: Sender phone number
        Body: Message text
        To: Recipient phone number (our Twilio number)
    """
    # Get or create lead
    db = next(get_db())
    lead_service = LeadService(db)
    
    # Get existing lead or create new
    lead = lead_service.get_lead_by_phone(From)
    
    if not lead:
        # New customer - create lead
        lead = lead_service.create_lead(
            name="Customer",  # Would extract from message or ask
            phone=From,
            source="sms"
        )
        
        # Send welcome message
        welcome_msg = chat_handler.get_welcome_message()
        sms.send_sms(From, welcome_msg)
        return {"status": "ok"}
    
    # Process message with AI
    conversation_history = []  # Would load from database
    ai_response = await chat_handler.process_message(
        user_message=Body,
        conversation_history=conversation_history,
        customer_info={"name": lead.name, "phone": lead.phone}
    )
    
    # Send AI response
    response_text = ai_response.get("response", "")
    sms.send_sms(From, response_text)
    
    # Update lead
    lead_service.increment_message_count(lead.id)
    
    # Handle booking intent
    intent = ai_response.get("intent")
    if intent == "book":
        # Extract booking details from conversation
        # For now, this is a placeholder - would need NLP to extract date/time
        booking_service = BookingService(db)
        
        # Example: Parse date/time from message or ask for it
        # This would be enhanced with proper date/time extraction
        pass
    
    return {"status": "ok"}

