"""
Twilio SMS integration
"""
from typing import Dict, Any, Optional
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
from app.config import settings


class TwilioSMS:
    """Handles SMS sending via Twilio"""
    
    def __init__(self):
        self.client = Client(
            settings.twilio_account_sid,
            settings.twilio_auth_token
        )
        self.from_number = settings.twilio_phone_number
    
    def send_sms(self, to: str, message: str) -> Dict[str, Any]:
        """
        Send SMS message
        
        Args:
            to: Recipient phone number (E.164 format)
            message: Message text
        
        Returns:
            Dict with status and message SID
        """
        try:
            message_obj = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=to
            )
            
            return {
                "success": True,
                "message_sid": message_obj.sid,
                "status": message_obj.status
            }
        
        except TwilioRestException as e:
            return {
                "success": False,
                "error": str(e),
                "error_code": e.code
            }
    
    def send_reminder(self, to: str, appointment_time: str, date: str) -> Dict[str, Any]:
        """Send appointment reminder"""
        message = f"Hi! Just a friendly reminder: You have an appointment at {settings.gym_name} on {date} at {appointment_time}. See you soon! If you need to reschedule, just let me know."
        return self.send_sms(to, message)
    
    def send_followup(self, to: str, message: str) -> Dict[str, Any]:
        """Send follow-up message"""
        return self.send_sms(to, message)

