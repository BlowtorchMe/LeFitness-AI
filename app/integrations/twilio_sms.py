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
        # Handle missing Twilio credentials gracefully
        self.client = None
        self.from_number = None
        # Check if credentials are provided and not empty/placeholder values
        account_sid = settings.twilio_account_sid
        auth_token = settings.twilio_auth_token
        
        # Validate credentials exist and are not empty/None/placeholders
        has_valid_creds = (
            account_sid is not None and 
            auth_token is not None and
            str(account_sid).strip() != "" and 
            str(auth_token).strip() != "" and
            "your_twilio" not in str(account_sid).lower() and
            "your_twilio" not in str(auth_token).lower()
        )
        
        if has_valid_creds:
            try:
                self.client = Client(str(account_sid), str(auth_token))
                self.from_number = settings.twilio_phone_number
            except Exception:
                pass  # Will fail gracefully on first SMS send
    
    def send_sms(self, to: str, message: str) -> Dict[str, Any]:
        """
        Send SMS message
        
        Args:
            to: Recipient phone number (E.164 format)
            message: Message text
        
        Returns:
            Dict with status and message SID
        """
        if not self.client:
            return {
                "success": False,
                "error": "Twilio not configured"
            }
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

